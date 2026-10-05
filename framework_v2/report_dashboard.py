"""Offline, report-derived Plotly dashboard backed by jQuantStats' Data API.

The adapter consumes return streams only. It never replays or changes orders,
positions, costs, or the execution assumptions recorded by KabuForge.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import date, datetime, time, timezone
import hashlib
import html
import importlib.metadata
import importlib.util
import json
import math
from pathlib import Path
import statistics
import tempfile

from .report_analysis import summarize_report
from .report_account_analysis import analyze_account_path


class DashboardUnavailable(RuntimeError):
    pass


def dependency_status() -> dict:
    """Cheap discovery only; never imports optional analytics libraries."""
    packages = {}
    for module, distribution in (("jquantstats", "jquantstats"), ("polars", "polars"), ("plotly", "plotly")):
        try:
            spec = importlib.util.find_spec(module)
            discoverable = spec is not None and spec.origin is not None and spec.loader is not None
        except (ImportError, ValueError):
            spec = None
            discoverable = False
        try:
            version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            version = None
        except (OSError, PermissionError, ValueError):
            version = None
        packages[module] = {"discoverable": discoverable, "version": version,
                            "origin": spec.origin if spec is not None else None,
                            "loader": type(spec.loader).__name__ if spec is not None and spec.loader is not None else None}
    try:
        webengine_spec=importlib.util.find_spec("PySide6.QtWebEngineWidgets")
        webengine = webengine_spec is not None and webengine_spec.origin is not None and webengine_spec.loader is not None
    except (ImportError, ValueError):
        webengine = False
    packages["qt_webengine"] = {"discoverable": webengine, "version": None}
    packages["available"] = (all(packages[name]["discoverable"] and packages[name]["version"]
                                 for name in ("jquantstats", "polars", "plotly"))
                             and packages["qt_webengine"]["discoverable"])
    # Discovery and distribution metadata are cheap UI hints, not proof a wheel
    # can import. The actual workflow runs in the report worker on user request.
    packages["runtime_verified"] = False
    packages["ready"] = False
    return packages


def _finite(value):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _date(value):
    if isinstance(value, datetime):
        return value.date()
    try:
        text = str(value)
        try:
            return date.fromisoformat(text)
        except ValueError:
            # Accept an explicit ISO datetime, but never silently truncate junk.
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None


def _timestamp(value):
    if isinstance(value, datetime):
        result = value
    else:
        text = str(value)
        try:
            result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                result = datetime.combine(date.fromisoformat(text), time.min)
            except ValueError:
                return None
    if result.tzinfo is not None:
        return result.astimezone(timezone.utc).replace(tzinfo=None)
    return result


def _nav_map(rows, *, label):
    result = {}
    if not isinstance(rows, list):
        raise ValueError(f"{label} must be a list of date/value records")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"{label} contains a non-object record")
        day = _date(row.get("at", row.get("date")))
        value = _finite(row.get("nav", row.get("value")))
        if day is None or value is None or value <= 0:
            raise ValueError(f"{label} contains an invalid date or positive NAV")
        if day in result:
            raise ValueError(f"{label} contains duplicate date {day.isoformat()}")
        result[day] = value
    return result


def _strategy_series(report: dict):
    nav = _nav_map(report.get("nav") or [], label="NAV")
    days = sorted(nav)
    if len(days) < 3:
        raise ValueError("At least three valid NAV observations are required for the interactive risk dashboard")
    returns = [(nav[right] / nav[left]) - 1 for left, right in zip(days, days[1:])]
    if not all(math.isfinite(value) for value in returns):
        raise ValueError("NAV contains a return that overflowed; no dashboard was generated")
    return days, days[1:], returns, nav


def benchmark_options(report: dict) -> list[str]:
    raw = report.get("benchmark_nav") if isinstance(report, dict) else None
    if raw in (None, [], {}):
        return []
    if isinstance(raw, dict) and not ("at" in raw or "date" in raw):
        return [str(name) for name, rows in raw.items() if isinstance(rows, list) and rows]
    if isinstance(raw, list):
        names = {str(row.get("name")) for row in raw if isinstance(row, dict) and row.get("name")}
        return sorted(names) if names else ["Benchmark"]
    if isinstance(raw, dict):
        return [str(raw.get("name") or "Benchmark")]
    return []


def _select_benchmark_rows(report: dict, benchmark_name=None):
    raw = report.get("benchmark_nav")
    if isinstance(raw, dict) and not ("at" in raw or "date" in raw):
        if benchmark_name is None:
            options = benchmark_options(report)
            benchmark_name = options[0] if options else None
        raw = raw.get(benchmark_name)
    if isinstance(raw, list) and benchmark_name not in (None, "Benchmark"):
        named = [row for row in raw if isinstance(row, dict) and str(row.get("name")) == benchmark_name]
        if named:
            raw = named
    return raw


def _benchmark_series(report: dict, strategy_observation_days, benchmark_name=None):
    raw = _select_benchmark_rows(report, benchmark_name)
    if raw in (None, [], {}):
        return None
    if isinstance(raw, dict):
        if "at" in raw or "date" in raw:
            raw = [raw]
        elif len(raw) == 1:
            raw = next(iter(raw.values()))
        else:
            raise ValueError("Multiple benchmarks require selecting one benchmark before rendering")
    levels = _nav_map(raw, label="benchmark NAV")
    result_days = []
    values = []
    for previous, current in zip(strategy_observation_days[:-1], strategy_observation_days[1:]):
        if previous in levels and current in levels:
            value = levels[current] / levels[previous] - 1
            if not math.isfinite(value):
                raise ValueError("Benchmark contains an overflowing return")
            result_days.append(current)
            values.append(value)
    if len(values) < 2:
        return None
    return result_days, values


def _closed_trades(report: dict):
    """FIFO long-only round trips with entry and exit fees allocated by quantity."""
    rows = report.get("trades")
    if rows is None:
        journal = report.get("journal") or report.get("execution", {}).get("view", {})
        rows = journal.get("fills") if isinstance(journal, dict) else None
    if rows is None:
        return {"available": False, "reason": "closed-trade evidence unavailable", "trades": []}
    if not isinstance(rows, list):
        return {"available": False, "reason": "trade evidence has an unsupported shape", "trades": []}
    lots = defaultdict(deque)
    cycles = defaultdict(lambda: {"entry_cost": 0.0, "net_pnl": 0.0, "matched_quantity": 0.0})
    closed = []
    last_time = None
    for row in rows:
        if not isinstance(row, dict):
            return {"available": False, "reason": "trade evidence contains a non-object record", "trades": []}
        if isinstance(row.get("payload"), str):
            try:
                row = json.loads(row["payload"])
            except (ValueError, TypeError):
                return {"available": False, "reason": "trade payload could not be parsed", "trades": []}
        timestamp = str(row.get("occurred_at") or row.get("at") or row.get("date") or "")
        parsed_time = _timestamp(timestamp) if timestamp else None
        if timestamp and parsed_time is None:
            return {"available": False, "reason": "trade evidence contains an invalid timestamp", "trades": []}
        if parsed_time is not None and last_time is not None and parsed_time < last_time:
            return {"available": False, "reason": "trade evidence is not ordered by occurrence date", "trades": []}
        if parsed_time is not None:
            last_time = parsed_time
        code = str(row.get("code") or "")
        side = str(row.get("side") or row.get("action") or "").lower()
        if side in {"buy", "b", "long"}:
            side = "buy"
        elif side in {"sell", "s", "close"}:
            side = "sell"
        quantity, price, fee = (_finite(row.get(name)) for name in ("quantity", "price", "fee"))
        if not code or side not in {"buy", "sell"} or quantity is None or price is None or fee is None or quantity <= 0 or price <= 0 or fee < 0:
            return {"available": False, "reason": "complete quantity, price, side and fee evidence is required", "trades": []}
        if side == "buy":
            lots[code].append({"quantity": quantity, "unit_cost": price + fee / quantity})
            continue
        remaining = quantity
        while remaining > 1e-9 and lots[code]:
            lot = lots[code][0]
            matched = min(remaining, lot["quantity"])
            entry_cost = matched * lot["unit_cost"]
            exit_fee = fee * matched / quantity
            net_pnl = matched * price - exit_fee - entry_cost
            cycles[code]["entry_cost"] += entry_cost
            cycles[code]["net_pnl"] += net_pnl
            cycles[code]["matched_quantity"] += matched
            remaining -= matched
            lot["quantity"] -= matched
            if lot["quantity"] <= 1e-9:
                lots[code].popleft()
        if remaining > 1e-9:
            return {"available": False, "reason": "sell quantity exceeds matched long inventory", "trades": []}
        if not lots[code] and cycles[code]["entry_cost"] > 0:
            cycle=cycles[code]
            closed.append({"date": timestamp, "code": code,
                "return": cycle["net_pnl"] / cycle["entry_cost"], "net_pnl": cycle["net_pnl"],
                "entry_cost": cycle["entry_cost"], "quantity": cycle["matched_quantity"]})
            cycles[code]={"entry_cost":0.0,"net_pnl":0.0,"matched_quantity":0.0}
    return {"available": True, "reason": None, "trades": closed,
            "open_lots": sum(len(items) for items in lots.values())}


def _trade_summary(closed):
    if not closed.get("available"):
        return {"closed_count": None, "win_rate": None, "mean_return": None, "median_return": None,
                "profit_factor": None, "gross_profit": None, "gross_loss": None}
    rows = closed.get("trades") or []
    if not rows:
        return {"closed_count": 0, "win_rate": None, "mean_return": None, "median_return": None,
                "profit_factor": None, "gross_profit": 0.0, "gross_loss": 0.0}
    values = [row["return"] for row in rows]
    pnl = [row["net_pnl"] for row in rows]
    gross_profit = sum(value for value in pnl if value > 0)
    gross_loss = -sum(value for value in pnl if value < 0)
    wins=[value for value in pnl if value>0]; losses=[-value for value in pnl if value<0]
    return {"closed_count": len(rows), "win_rate": sum(value > 0 for value in pnl) / len(pnl),
            "mean_return": statistics.mean(values), "median_return": statistics.median(values),
            "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
            "payoff_ratio": statistics.mean(wins)/statistics.mean(losses) if wins and losses else None,
            "net_positive_pnl": gross_profit, "net_negative_pnl": gross_loss}


def _drawdown_duration(nav_rows, initial_nav=None, initial_at=None):
    points = []
    for row in nav_rows:
        day = _date(row.get("at", row.get("date"))) if isinstance(row, dict) else None
        value = _finite(row.get("nav")) if isinstance(row, dict) else None
        if day is None or value is None or value <= 0:
            continue
        points.append((day, value))
    points.sort(key=lambda item:item[0])
    if len(points) < 2:
        return None
    base=_finite(initial_nav)
    base_day=_date(initial_at)
    full_base=base is not None and base>0 and base_day is not None and base_day<=points[0][0]
    if full_base and (base_day,base) not in points:
        points.insert(0,(base_day,base))
    peak, peak_day = points[0][1], points[0][0]
    episode_start = None; trough_day = None; trough_value = None
    worst = {"calendar_days": 0, "start": None, "recovered_at": None, "trough_at": None}
    for day, value in points:
        if value >= peak:
            if episode_start is not None:
                duration = (day - episode_start).days
                if duration > worst["calendar_days"]:
                    worst = {"calendar_days": duration, "start": episode_start,
                             "recovered_at": day, "trough_at": trough_day}
                episode_start = None; trough_day = None; trough_value = None
            peak, peak_day = value, day
        else:
            if episode_start is None: episode_start = peak_day
            if trough_value is None or value < trough_value:
                trough_value, trough_day = value, day
            duration = (day - episode_start).days
            if duration > worst["calendar_days"]:
                worst = {"calendar_days": duration, "start": episode_start,
                         "recovered_at": None, "trough_at": trough_day}
    return {"calendar_days": worst["calendar_days"], "start": worst["start"].isoformat() if worst["start"] else None,
            "recovered_at": worst["recovered_at"].isoformat() if worst["recovered_at"] else None,
            "trough_at": worst["trough_at"].isoformat() if worst["trough_at"] else None,
            "basis": "explicit initial NAV through report window" if full_base else "displayed NAV window"}


def _annual_returns(report):
    nav=_nav_map(report.get("nav") or [],label="NAV")
    days=sorted(nav)
    if not days: return []
    initial_nav=_finite(report.get("initial_nav")) if report.get("nav_base_includes_initial") is True else None
    initial_day=_date(report.get("initial_at")) if initial_nav is not None else None
    years=sorted({day.year for day in days})
    rows=[]
    for year in years:
        current=[day for day in days if day.year==year]
        if not current: continue
        first,last=current[0],current[-1]
        preceding=[day for day in days if day<first]
        if preceding:
            left=preceding[-1]; base=nav[left]; coverage="observed_window; calendar completeness unverified"
        elif initial_nav is not None and initial_day is not None and initial_day.year==year and initial_day<=first:
            left=initial_day; base=initial_nav; coverage="explicit initial capital to last observed point; calendar completeness unverified"
        else:
            left=first; base=nav[first]; coverage="partial_start_or_window_only; calendar completeness unverified"
        value=_finite(nav[last]/base-1) if base>0 else None
        rows.append({"year":year,"return":value,"start_at":left.isoformat(),"end_at":last.isoformat(),"coverage":coverage})
    return rows


def _execution_rows(report):
    rows=report.get("trades")
    if rows is None:
        journal=report.get("journal") or report.get("execution",{}).get("view",{})
        rows=journal.get("fills") if isinstance(journal,dict) else None
    if rows is None: return None
    if not isinstance(rows,list): return None
    parsed=[]
    for row in rows:
        if not isinstance(row,dict): continue
        if isinstance(row.get("payload"),str):
            try: row=json.loads(row["payload"])
            except (ValueError,TypeError): continue
        parsed.append(row)
    return parsed


def _safe_html_table(rows, columns, empty_text):
    if rows is None: return f'<p class="muted">{html.escape(empty_text)}</p>'
    if not rows: return f'<p class="muted">{html.escape(empty_text)}</p>'
    pairs=[column if isinstance(column,tuple) and len(column)==2 else (column,column) for column in columns]
    head="".join(f"<th>{html.escape(str(title))}</th>" for _,title in pairs)
    body=[]
    for row in rows:
        cells="".join(f'<td>{html.escape(str(row.get(key, "—")))}</td>' for key,_ in pairs)
        body.append(f"<tr>{cells}</tr>")
    return f'<div style="overflow:auto"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def _metric_value(value, series_name="Strategy"):
    if isinstance(value, dict):
        value = value.get(series_name, next(iter(value.values())) if len(value) == 1 else None)
    return _finite(value)


def _tracking_error(active_returns, annualization):
    """Sample standard deviation of paired active returns; no guessed cadence."""
    if annualization is None:
        return None
    values=[_finite(value) for value in active_returns]
    if len(values)<2 or any(value is None for value in values):
        return None
    value=statistics.stdev(values)*math.sqrt(annualization)
    return value if math.isfinite(value) else None


def _paired_correlation(strategy_returns, benchmark_returns):
    """Pearson correlation over exact-date paired observation returns."""
    left = [_finite(value) for value in strategy_returns]
    right = [_finite(value) for value in benchmark_returns]
    if len(left) < 2 or len(left) != len(right) or any(value is None for value in left + right):
        return None, "fewer than two finite exact-date paired returns"
    if statistics.pstdev(left) == 0 or statistics.pstdev(right) == 0:
        return None, "correlation is undefined because one paired return series has zero variance"
    value = statistics.correlation(left, right)
    if not math.isfinite(value):
        return None, "paired correlation is non-finite"
    return value, None


def _annualized_alpha(strategy_returns, benchmark_returns, beta, annualization):
    if annualization is None:
        return None, "sampling frequency is unknown; annualized alpha is unavailable"
    if beta is None:
        return None, "paired beta is unavailable"
    left = [_finite(value) for value in strategy_returns]
    right = [_finite(value) for value in benchmark_returns]
    if len(left) < 2 or len(left) != len(right) or any(value is None for value in left + right):
        return None, "fewer than two finite exact-date paired returns"
    value = (statistics.mean(left) - beta * statistics.mean(right)) * annualization
    if not math.isfinite(value):
        return None, "annualized alpha is non-finite"
    return value, None


def _library_stats(data, has_benchmark, strategy_label, annualization):
    stats = {}
    reasons = {}
    for key, method in (("sharpe", "sharpe"), ("sortino", "sortino"),
                        ("calmar", "calmar"), ("volatility", "volatility"),
                        ("max_drawdown", "max_drawdown")):
        try:
            if key == "max_drawdown":
                result=getattr(data.stats,method)()
            elif annualization is not None:
                import inspect
                function=getattr(data.stats,method)
                parameters=inspect.signature(function).parameters
                if "periods" in parameters:
                    result=function(periods=annualization)
                elif "periods_per_year" in parameters:
                    kwargs={"periods_per_year":annualization}
                    if "annualise" in parameters: kwargs["annualise"]=True
                    elif "annualize" in parameters: kwargs["annualize"]=True
                    result=function(**kwargs)
                elif abs(float(data.stats.periods_per_year)-annualization)<=1:
                    result=function()
                else:
                    result=None
            else:
                result=None
            stats[key] = _metric_value(result, strategy_label)
            if stats[key] is None:
                needs_frequency = key in {"sharpe", "sortino", "calmar", "volatility"}
                reasons[key] = ("sampling frequency is unknown or unsupported" if needs_frequency and annualization is None
                                else "library returned no finite value for this sample")
        except Exception as exc:
            stats[key] = None
            reasons[key] = f"{type(exc).__name__}: {exc}"
    if has_benchmark:
        try:
            import inspect
            function=data.stats.information_ratio
            parameters=inspect.signature(function).parameters
            if annualization is not None and "periods_per_year" in parameters:
                kwargs={"periods_per_year":annualization}
                if "annualise" in parameters: kwargs["annualise"]=True
                elif "annualize" in parameters: kwargs["annualize"]=True
                raw=function(**kwargs)
            elif annualization is not None and "periods" in parameters:
                raw=function(periods=annualization)
            elif annualization is not None and abs(float(data.stats.periods_per_year)-annualization)<=1:
                raw=function()
            else:
                raw=None
            stats["information_ratio"] = _metric_value(raw, strategy_label)
            if stats["information_ratio"] is None:
                reasons["information_ratio"] = ("sampling frequency is unknown or unsupported" if annualization is None
                                                 else "library returned no finite value for aligned benchmark sample")
        except Exception as exc:
            stats["information_ratio"] = None
            reasons["information_ratio"] = f"{type(exc).__name__}: {exc}"
        try:
            import inspect
            greeks_method=data.stats.greeks
            greeks_parameters=inspect.signature(greeks_method).parameters
            if annualization is not None and "periods_per_year" in greeks_parameters:
                greeks=greeks_method(periods_per_year=annualization)
            elif annualization is not None and abs(float(data.stats.periods_per_year)-annualization)<=1:
                greeks=greeks_method()
            else:
                greeks={}
            strategy = greeks.get(strategy_label, {}) if isinstance(greeks, dict) else {}
            stats["alpha"] = _finite(strategy.get("alpha")) if isinstance(strategy, dict) else None
            stats["beta"] = _finite(strategy.get("beta")) if isinstance(strategy, dict) else None
            stats["correlation"] = _finite(strategy.get("correlation")) if isinstance(strategy, dict) else None
            if stats["beta"] is None:
                reasons["beta"] = "jQuantStats did not return a finite beta"
            if stats["correlation"] is None:
                reasons["correlation"] = "jQuantStats did not expose a finite correlation; exact-date paired calculation required"
        except Exception as exc:
            stats.update(alpha=None, beta=None, correlation=None)
            reasons["benchmark_greeks"] = f"{type(exc).__name__}: {exc}"
    else:
        reasons["benchmark_metrics"] = "no benchmark series supplied"
        stats.update(tracking_error=None, information_ratio=None, alpha=None, beta=None, correlation=None)
        reasons["tracking_error"] = "no benchmark series supplied"
    # jQuantStats 0.12 exposes information ratio and benchmark Greeks, but not
    # tracking error. The adapter computes TE from exact-date paired active
    # returns and annualizes only when the NAV sampling frequency is explicit.
    if has_benchmark:
        stats["tracking_error"] = None
        reasons["tracking_error"] = ("sampling frequency is unknown or unsupported" if annualization is None
                                     else "tracking error requires the paired active-return series")
    stats["_unavailable_reasons"] = reasons
    return stats


_DASHBOARD_COLORS = {
    "blue": "#56B4E9",
    "orange": "#E69F00",
    "teal": "#009E73",
    "purple": "#CC79A7",
    "yellow": "#F0E442",
    "ink": "#0D1117",
    "panel": "#161B22",
    "grid": "#30363D",
    "text": "#E6EDF3",
    "muted": "#A7B1C2",
}


def _apply_dark_theme(figures):
    """Apply the product's dark palette to native and jQuantStats figures alike."""
    palette = [_DASHBOARD_COLORS[key] for key in ("blue", "orange", "teal", "purple", "yellow")]
    for index, figure in enumerate(figures):
        figure.update_layout(
            template="plotly_dark",
            paper_bgcolor=_DASHBOARD_COLORS["ink"],
            plot_bgcolor=_DASHBOARD_COLORS["panel"],
            font={"color": _DASHBOARD_COLORS["text"]},
            colorway=palette,
            hoverlabel={"bgcolor": _DASHBOARD_COLORS["panel"], "bordercolor": _DASHBOARD_COLORS["grid"],
                        "font": {"color": _DASHBOARD_COLORS["text"]}},
            legend={"bgcolor": "rgba(22,27,34,0.82)", "bordercolor": _DASHBOARD_COLORS["grid"]},
        )
        figure.update_xaxes(gridcolor=_DASHBOARD_COLORS["grid"], zerolinecolor=_DASHBOARD_COLORS["grid"],
                            linecolor=_DASHBOARD_COLORS["grid"], tickfont={"color": _DASHBOARD_COLORS["muted"]})
        figure.update_yaxes(gridcolor=_DASHBOARD_COLORS["grid"], zerolinecolor=_DASHBOARD_COLORS["grid"],
                            linecolor=_DASHBOARD_COLORS["grid"], tickfont={"color": _DASHBOARD_COLORS["muted"]})
        if index == 2:  # drawdown
            for trace in figure.data:
                trace.update(line={"color": _DASHBOARD_COLORS["orange"]},
                             fillcolor="rgba(230,159,0,0.24)")
        elif index == 3 and figure.data:  # monthly returns; negative=orange, positive=blue
            figure.data[0].update(colorscale=[[0, _DASHBOARD_COLORS["orange"]],
                                               [0.5, _DASHBOARD_COLORS["panel"]],
                                               [1, _DASHBOARD_COLORS["blue"]]])
        elif index == 5:  # rolling return, volatility, and Sharpe have distinct roles
            for trace, color in zip(figure.data, (_DASHBOARD_COLORS["blue"], _DASHBOARD_COLORS["orange"],
                                                  _DASHBOARD_COLORS["purple"])):
                trace.update(line={"color": color})
        elif index == 1:  # native NAV and benchmark
            for trace, color in zip(figure.data, (_DASHBOARD_COLORS["blue"], _DASHBOARD_COLORS["orange"])):
                trace.update(line={"color": color})
        elif index == 6:  # strategy and benchmark
            for trace, color in zip(figure.data, (_DASHBOARD_COLORS["blue"], _DASHBOARD_COLORS["orange"])):
                trace.update(line={"color": color})
        elif index in (1, 4, 7, 9):
            color = _DASHBOARD_COLORS["blue"] if index != 9 else _DASHBOARD_COLORS["purple"]
            for trace in figure.data:
                if trace.type == "bar":
                    trace.update(marker={"color": color})
                elif trace.type == "histogram":
                    trace.update(marker={"color": color, "line": {"color": _DASHBOARD_COLORS["ink"], "width": 1}})
                else:
                    trace.update(line={"color": _DASHBOARD_COLORS["teal"] if index == 9 else color})
        elif index == 10:
            for trace in figure.data:
                trace.update(line={"color": _DASHBOARD_COLORS["teal"]},
                             marker={"color": _DASHBOARD_COLORS["teal"]})
        elif index == 11:
            for trace in figure.data:
                trace.update(line={"color": _DASHBOARD_COLORS["yellow"]},
                             marker={"color": _DASHBOARD_COLORS["yellow"]})
        elif index == 12:
            for trace in figure.data:
                trace.update(marker={"color": _DASHBOARD_COLORS["purple"]})
    return figures


def _concentration_axes(security_counts, labels):
    """Return bounded, readable axes for holdings count and concentration."""
    valid_counts = [value for value in security_counts if isinstance(value, (int, float)) and value >= 0]
    count_top = max(1, int(max(valid_counts, default=0)) + 1)
    return {
        "yaxis": {"title": labels["security_count_axis"], "range": [0, count_top], "dtick": 1,
                  "tickformat": "d", "automargin": True},
        "yaxis2": {"title": {"text": labels["max_weight_axis"], "standoff": 8}, "overlaying": "y",
                   "side": "right", "tickformat": ".0%", "range": [0, 1], "position": .98,
                   "automargin": True},
        "yaxis3": {"title": {"text": labels["hhi_axis"], "standoff": 8}, "overlaying": "y",
                   "side": "right", "tickformat": ".2f", "range": [0, 1], "position": .82,
                   "automargin": True},
        "legend": {"orientation": "h", "x": .5, "xanchor": "center", "y": 1.18, "yanchor": "bottom"},
        "margin": {"l": 82, "r": 118, "t": 125, "b": 55},
    }


def _diagnostic_labels(language):
    return {
        "zh_CN": {"price_title":"价格、前收信号与次日执行", "price_unavailable":"没有可核验的冻结行情与订单证据；本图不可用",
                  "close":"研究收盘价", "raw_close":"原始收盘价", "fast":"快线 SMA", "slow":"慢线 SMA",
                  "scheduled":"前收盘计划信号", "fill":"实际开盘成交（非信号价）", "skip":"跳过订单（没有成交）",
                  "date":"日期", "price_axis":"价格（研究输入单位）", "source":"输入 SHA256", "pit":"历史可见性未认证 · RESEARCH-ONLY",
                  "regime_title":"历史 Regime（报告证据）", "regime_unavailable":"报告未提供合格的历史重建时间线；当前 Store 不用于回填历史",
                  "state":"报告记录的状态", "groups":"NAV 日期区间分组统计（仅原报告）", "fee":"成交费用（报告账户单位）", "fee_missing":"费用证据不可用",
                  "side":"方向", "quantity":"数量", "signal_date":"信号日", "execution_date":"执行日", "reason":"跳过原因", "adjusted":"复权研究价格", "orders_hash":"订单计划 SHA256"},
        "ja_JP": {"price_title":"価格・前日シグナル・翌日執行", "price_unavailable":"検証可能な凍結データと注文根拠がなく、この図は利用できません",
                  "close":"研究終値", "raw_close":"原終値", "fast":"短期 SMA", "slow":"長期 SMA",
                  "scheduled":"前日終値時点の注文計画", "fill":"実際の始値約定（シグナル価格ではない）", "skip":"スキップ注文（約定なし）",
                  "date":"日付", "price_axis":"価格（研究入力単位）", "source":"入力 SHA256", "pit":"過去の可視性は未認証 · RESEARCH-ONLY",
                  "regime_title":"過去の Regime（レポート根拠）", "regime_unavailable":"レポートに適格な過去再構築タイムラインがありません。現在のStoreで過去を補完しません",
                  "state":"レポート記録の状態", "groups":"NAV日付区間のグループ統計（元レポートのみ）", "fee":"約定手数料（レポート口座単位）", "fee_missing":"手数料証拠なし",
                  "side":"売買", "quantity":"数量", "signal_date":"シグナル日", "execution_date":"執行日", "reason":"スキップ理由", "adjusted":"調整後の研究価格", "orders_hash":"注文計画 SHA256"},
        "en_US": {"price_title":"Price, prior-close signals and next-session execution", "price_unavailable":"Verified frozen bars and order evidence are missing; this chart is unavailable",
                  "close":"Research close", "raw_close":"Raw close", "fast":"Fast SMA", "slow":"Slow SMA",
                  "scheduled":"Prior-close scheduled order", "fill":"Actual open fill (not signal price)", "skip":"Skipped order (no fill)",
                  "date":"Date", "price_axis":"Price (research input units)", "source":"Input SHA256", "pit":"Historical visibility unverified · RESEARCH-ONLY",
                  "regime_title":"Historical regime (report evidence)", "regime_unavailable":"No qualified historical reconstruction timeline is in this report; current Store state is never backfilled",
                  "state":"State recorded by report", "groups":"NAV-date interval group statistics (source report only)", "fee":"Fill fee (reported account units)", "fee_missing":"fee evidence unavailable",
                  "side":"Side", "quantity":"Quantity", "signal_date":"Signal date", "execution_date":"Execution date", "reason":"Skip reason", "adjusted":"Adjusted research price", "orders_hash":"Order schedule SHA256"},
    }.get(language, {})


def _matched_fill_fees(fill_events, report):
    """Return fees only for uniquely matched, explicitly recorded report fills."""
    import math
    trades = report.get("trades") if isinstance(report, dict) else None
    if not isinstance(trades, list):
        return [None] * len(fill_events)
    output = []
    for event in fill_events:
        candidates = []
        for trade in trades:
            if not isinstance(trade, dict):
                continue
            day = trade.get("execution_date", trade.get("date", trade.get("at")))
            if str(day)[:10] != str(event.get("execution_date", ""))[:10]:
                continue
            if str(trade.get("code", "")) != str(event.get("code", "")):
                continue
            if str(trade.get("side", "")).lower() != str(event.get("side", "")).lower():
                continue
            try:
                same_qty = math.isclose(float(trade.get("quantity")), float(event.get("quantity")), rel_tol=1e-10, abs_tol=1e-10)
                same_price = math.isclose(float(trade.get("price")), float(event.get("price")), rel_tol=1e-10, abs_tol=1e-10)
            except (TypeError, ValueError, OverflowError):
                continue
            if same_qty and same_price:
                candidates.append(trade)
        if len(candidates) != 1:
            output.append(None)
            continue
        try:
            fee = float(candidates[0].get("fee"))
            output.append(fee if math.isfinite(fee) else None)
        except (TypeError, ValueError, OverflowError):
            output.append(None)
    return output


def _price_execution_figures(payload, language, report=None):
    import plotly.graph_objects as go
    labels = _diagnostic_labels(language)
    figures = []
    if not isinstance(payload, dict) or payload.get("status") != "available":
        figure = go.Figure()
        figure.add_annotation(text=labels["price_unavailable"], x=.5, y=.5, xref="paper", yref="paper", showarrow=False)
        figure.update_layout(title=labels["price_title"], xaxis_title=labels["date"], yaxis_title=labels["price_axis"])
        return [figure]
    identity = str(payload.get("input_hash") or "")
    diag_labels = payload.get("labels") or {}
    for series in payload.get("series", []):
        if not isinstance(series, dict) or not series.get("dates"):
            continue
        days = series["dates"]
        closes = series["research_close"]
        close_by_day = dict(zip(days, closes))
        figure = go.Figure()
        close_label = diag_labels.get("close", labels["close"])
        if series.get("price_basis") == "adjusted":
            close_label = labels["adjusted"]
        figure.add_trace(go.Scatter(x=days, y=closes, mode="lines", name=close_label,
            hovertemplate=f"{labels['date']} %{{x}}<br>{close_label} %{{y:,.3f}}<extra></extra>"))
        if series.get("fast_sma"):
            for key, fallback in (("fast_sma", labels["fast"]), ("slow_sma", labels["slow"])):
                values = series.get(key)
                if values and any(value is not None for value in values):
                    name = diag_labels.get("fast" if key == "fast_sma" else "slow", fallback)
                    figure.add_trace(go.Scatter(x=days, y=values, mode="lines", name=name,
                        connectgaps=False, hovertemplate=f"{labels['date']} %{{x}}<br>{name} %{{y:,.3f}}<extra></extra>"))
        scheduled = series.get("scheduled_orders") or []
        if scheduled:
            scheduled_days = [event["signal_date"] for event in scheduled]
            scheduled_y = [close_by_day.get(day) for day in scheduled_days]
            custom = [[event.get("side"), event.get("quantity"), event.get("execution_date")] for event in scheduled]
            name = diag_labels.get("signal", labels["scheduled"])
            figure.add_trace(go.Scatter(x=scheduled_days, y=scheduled_y, mode="markers", name=name,
                marker={"symbol":"diamond-open","size":10}, customdata=custom,
                hovertemplate=f"{labels['date']} %{{x}}<br>{name}<br>{labels['side']}=%{{customdata[0]}} · {labels['quantity']}=%{{customdata[1]:.6g}}<br>{labels['execution_date']}=%{{customdata[2]}}<extra></extra>"))
        fills = series.get("actual_fills") or []
        if fills:
            fill_days = [event["execution_date"] for event in fills]
            fees = _matched_fill_fees(fills, report)
            custom = [[event.get("side"), event.get("quantity"), event.get("signal_date"),
                       fee if fee is not None else labels["fee_missing"]] for event, fee in zip(fills, fees)]
            name = diag_labels.get("fill", labels["fill"])
            figure.add_trace(go.Scatter(x=fill_days, y=[event["price"] for event in fills], mode="markers", name=name,
                marker={"symbol":"triangle-up","size":11}, customdata=custom,
                hovertemplate=f"{labels['date']} %{{x}}<br>{name} %{{y:,.3f}}<br>{labels['side']}=%{{customdata[0]}} · {labels['quantity']}=%{{customdata[1]:.6g}}<br>{labels['signal_date']}=%{{customdata[2]}}<br>{labels['fee']}: %{{customdata[3]}}<extra></extra>"))
        skipped = series.get("skipped_orders") or []
        if skipped:
            skipped_days = [event["execution_date"] for event in skipped]
            custom = [[event.get("side"), event.get("quantity"), event.get("signal_date"), event.get("reason")] for event in skipped]
            name = diag_labels.get("skip", labels["skip"])
            figure.add_trace(go.Scatter(x=skipped_days, y=[event["price"] for event in skipped], mode="markers", name=name,
                marker={"symbol":"x","size":11}, customdata=custom,
                hovertemplate=f"{labels['date']} %{{x}}<br>{name} %{{y:,.3f}}<br>{labels['side']}=%{{customdata[0]}} · {labels['quantity']}=%{{customdata[1]:.6g}}<br>{labels['signal_date']}=%{{customdata[2]}}<br>{labels['reason']}: %{{customdata[3]}}<extra></extra>"))
        source_caption = f"{labels['source']}: {identity} · {labels['orders_hash']}: {payload.get('order_schedule_hash') or '—'} · {diag_labels.get('pit', labels['pit'])}"
        figure.add_annotation(text=source_caption, x=0, y=-.23, xref="paper", yref="paper", showarrow=False,
                              xanchor="left", font={"size":10})
        figure.update_layout(title=f"{labels['price_title']} · {series['code']}", xaxis_title=labels["date"],
            yaxis_title=f"{labels['price_axis']} · {series.get('price_basis','raw')}", hovermode="x unified",
            legend={"orientation":"h","y":1.18,"x":.5,"xanchor":"center"}, margin={"t":110,"b":105,"l":85,"r":35})
        figure.update_xaxes(rangeslider={"visible":True})
        figures.append(figure)
    if figures:
        return figures
    empty = go.Figure()
    empty.add_annotation(text=labels["price_unavailable"], x=.5, y=.5, showarrow=False)
    return [empty]


def _regime_history_figure(report, language):
    import plotly.graph_objects as go
    labels = _diagnostic_labels(language)
    figure = go.Figure()
    regime = report.get("regime_observer") if isinstance(report, dict) else None
    timeline = regime.get("timeline") if isinstance(regime, dict) else None
    qualified = (isinstance(regime, dict) and regime.get("mode") == "historical_reconstruction"
        and isinstance(regime.get("input_sha256"), str) and len(regime.get("input_sha256")) == 64
        and isinstance(timeline, list) and bool(timeline)
        and all(isinstance(row, dict) and row.get("active_state") not in (None, "")
                and row.get("market_date", row.get("session_date")) for row in timeline))
    if not qualified:
        figure.add_annotation(text=labels["regime_unavailable"], x=.5, y=.5, xref="paper", yref="paper", showarrow=False)
    else:
        dates = [str(row.get("market_date", row.get("session_date"))) for row in timeline]
        states = [str(row["active_state"]) for row in timeline]
        custom = [[row.get("decision_time"), row.get("knowledge_status", regime.get("knowledge_status")),
                   row.get("source_health"), row.get("snapshot_hash")] for row in timeline]
        figure.add_trace(go.Scatter(x=dates, y=states, mode="lines+markers", name=labels["state"],
            connectgaps=False, customdata=custom,
            hovertemplate=f"{labels['date']} %{{x}}<br>{labels['state']}: %{{y}}<br>decision=%{{customdata[0]}}<br>knowledge=%{{customdata[1]}}<br>health=%{{customdata[2]}}<br>snapshot=%{{customdata[3]}}<extra></extra>"))
        groups = regime.get("grouped_returns") or []
        if groups:
            rows = [f"{row.get('active_state','—')}: n={row.get('interval_count','—')}, mean={row.get('mean_interval_return'):.2%}"
                    for row in groups if isinstance(row, dict) and isinstance(row.get("mean_interval_return"), (int, float))]
            if rows:
                figure.add_annotation(text=labels["groups"] + "<br>" + "<br>".join(rows), x=1, y=1,
                    xref="paper", yref="paper", xanchor="right", yanchor="top", showarrow=False,
                    bgcolor="rgba(22,27,34,0.82)")
        figure.add_annotation(text=f"input SHA256: {regime['input_sha256']} · {regime.get('knowledge_status','')} · RESEARCH-ONLY",
            x=0, y=-.2, xref="paper", yref="paper", xanchor="left", showarrow=False, font={"size":10})
    figure.update_layout(title=labels["regime_title"], xaxis_title=labels["date"], yaxis_title=labels["state"],
        hovermode="closest", margin={"t":95,"b":95,"l":85,"r":50})
    return figure


def _build_figures(report, dates, returns, monthly, rolling_window, benchmark, jqs_data, language,
                   benchmark_name=None, price_diagnostics=None):
    import plotly.graph_objects as go
    import plotly.io as pio

    labels = {
        "zh_CN": {"nav": "策略净值（报告原始观测）", "jqs_snapshot":"jQuantStats净值（相邻N-1收益；不含初始资金至首个NAV）", "return": "区间收益", "dd": "水下回撤（显示窗口）", "dd_full":"水下回撤（报告完整口径）",
                  "heat": "月收益热力图（窗口覆盖）", "annual": "年度观察窗口收益（完整性未验证）", "roll": f"滚动收益 / 波动 / Sharpe（{rolling_window}期）",
                  "hist": "区间收益分布", "hold": "现金与持仓权重", "trades": "已平仓交易收益（FIFO、扣费用）", "realized": "已实现净盈亏累计值（账户原始单位）", "fees_chart":"累计实际费用（账户金额单位）", "fees_axis":"累计费用（报告账户金额单位）", "turnover_chart":"总成交换手率（买卖成交额合计 / 前收盘权益）", "turnover_axis":"换手率（%）", "account_missing":"缺少逐日账户路径", "fee_missing":"缺少逐日实际费用证据", "turnover_missing":"缺少实际成交换手证据",
                  "benchmark_missing": "基准未提供；相对表现不可评估", "benchmark_insufficient":"基准存在，但相邻NAV日期对齐样本不足", "benchmark_rebased":"TOPIX价格指数（虚线；对齐首个NAV重设）", "topix_benchmark":"TOPIX价格指数（不含股息）", "position_missing": "无实际持仓路径",
                  "closed_missing": "已平仓交易证据不足，未计算交易统计", "period_return": "区间收益",
                  "period_volatility": "年化波动", "period_sharpe": "Sharpe（RF=0）", "relative": "策略与基准累计收益",
                  "strategy": "策略", "benchmark": "基准", "date": "日期", "nav_axis": "净值", "drawdown_axis": "回撤",
                  "month_axis": "月份", "year_axis": "年份", "ratio_axis": "比率 / 收益", "sharpe_axis":"Sharpe比率（独立轴）", "observations": "观测次数", "weight_axis": "权重", "mean": "均值", "single_trade":"单笔已平仓周期",
                  "year_hover":"年份", "month_hover":"月份", "coverage_hover":"覆盖情况","annual_coverage":"观察区间：%{customdata[0]} 至 %{customdata[1]}<br>覆盖：%{customdata[2]}",
                  "cash":"现金", "concentration":"持仓数量与集中度", "security_count":"持仓证券数", "security_count_axis":"证券数", "max_weight":"最大证券权重", "max_weight_axis":"最大证券权重", "hhi":"证券权重HHI", "hhi_axis":"HHI（0–1）", "contribution":"证券累计价格贡献（占初始权益）", "contribution_axis":"占初始权益比例", "fees_negative":"累计费用（负贡献）", "nav_change":"净值变化（校验）", "turnover_events":"实际成交日", "unavailable":"不可用", "account_analysis_missing":"缺少可核对的逐日持仓/成交价格证据"},
        "ja_JP": {"nav": "戦略NAV（レポート原観測値）", "jqs_snapshot":"jQuantStats NAV（隣接N-1リターン；初期資本から最初のNAVを除外）", "return": "期間リターン", "dd": "表示期間の水中ドローダウン", "dd_full":"レポート全期間の水中ドローダウン",
                  "heat": "月次リターンヒートマップ（観測範囲）", "annual": "年次の観測期間リターン（完全性未検証）", "roll": f"ローリング収益 / 変動率 / Sharpe（{rolling_window}期）",
                  "hist": "期間リターン分布", "hold": "現金と保有比率", "trades": "完了取引リターン（FIFO・費用控除）", "realized": "実現純損益の累計（口座単位）", "fees_chart":"実際の累計手数料（口座単位）", "fees_axis":"累計手数料（レポートの口座通貨単位）", "turnover_chart":"グロス売買回転率（買い・売り約定額合計 / 前日終値時の評価額）", "turnover_axis":"売買回転率（%）", "account_missing":"日次口座パスがありません", "fee_missing":"日次の実手数料データがありません", "turnover_missing":"実績回転率データがありません",
                  "benchmark_missing": "ベンチマーク未提供；相対評価は利用できません", "benchmark_insufficient":"ベンチマークはありますが、隣接NAV日付の整列サンプルが不足しています", "benchmark_rebased":"TOPIX価格指数（破線；最初のNAVに再基準化）", "topix_benchmark":"TOPIX価格指数（配当なし）", "position_missing": "実保有データがありません",
                  "closed_missing": "完了取引の根拠が不足しているため統計を計算しません", "period_return": "期間リターン",
                  "period_volatility": "年率変動率", "period_sharpe": "Sharpe（RF=0）", "relative": "戦略とベンチマークの累積リターン",
                  "strategy": "戦略", "benchmark": "ベンチマーク", "date": "日付", "nav_axis": "NAV", "drawdown_axis": "ドローダウン",
                  "month_axis": "月", "year_axis": "年", "ratio_axis": "比率 / リターン", "sharpe_axis":"Sharpe比率（独立軸）", "observations": "観測数", "weight_axis": "比率", "mean": "平均", "single_trade":"単一完了ポジション",
                  "year_hover":"年", "month_hover":"月", "coverage_hover":"カバレッジ","annual_coverage":"観測期間：%{customdata[0]} ～ %{customdata[1]}<br>範囲：%{customdata[2]}",
                  "cash":"現金", "concentration":"保有銘柄数と集中度", "security_count":"保有銘柄数", "security_count_axis":"銘柄数", "max_weight":"最大銘柄ウェイト", "max_weight_axis":"最大銘柄ウェイト", "hhi":"銘柄ウェイトHHI", "hhi_axis":"HHI（0–1）", "contribution":"銘柄累積価格損益（初期資本比）", "contribution_axis":"初期資本比", "fees_negative":"累積手数料（負の寄与）", "nav_change":"NAV変化（照合）", "turnover_events":"実約定日", "unavailable":"利用不可", "account_analysis_missing":"日次保有・約定価格の照合根拠が不足しています"},
        "en_US": {"nav": "Strategy NAV (raw report observations)", "jqs_snapshot":"jQuantStats NAV (adjacent N-1 returns; excludes initial capital to first NAV)", "return": "Period return", "dd": "Underwater drawdown (display window)", "dd_full":"Underwater drawdown (full report basis)",
                  "heat": "Monthly return heatmap (observed coverage)", "annual": "Observed annual windows (completeness unverified)", "roll": f"Rolling return / volatility / Sharpe ({rolling_window} periods)",
                  "hist": "Period-return distribution", "hold": "Cash and holding weights", "trades": "Closed-trade returns (FIFO, net of fees)", "realized": "Cumulative realized net P&L (reported account units)", "fees_chart":"Cumulative realized fees (reported account units)", "fees_axis":"Cumulative fees (reported account currency/unit)", "turnover_chart":"Gross traded turnover (buy + sell notional / prior-close equity)", "turnover_axis":"Turnover ratio (%)", "account_missing":"Daily account path unavailable", "fee_missing":"Daily realized-fee evidence unavailable", "turnover_missing":"Realized turnover evidence unavailable",
                  "benchmark_missing": "No benchmark supplied; relative performance is unavailable", "benchmark_insufficient":"Benchmark supplied, but too few adjacent NAV-date pairs align", "benchmark_rebased":"TOPIX price index (dashed; rebased at first aligned NAV)", "topix_benchmark":"TOPIX price index (excluding dividends)", "position_missing": "No actual holdings path supplied",
                  "closed_missing": "Closed-trade evidence is incomplete; trade statistics are unavailable", "period_return": "Period return",
                  "period_volatility": "Annualized volatility", "period_sharpe": "Sharpe (RF=0)", "relative": "Strategy and benchmark cumulative return",
                  "strategy": "Strategy", "benchmark": "Benchmark", "date": "Date", "nav_axis": "NAV", "drawdown_axis": "Drawdown",
                  "month_axis": "Month", "year_axis": "Year", "ratio_axis": "Ratio / return", "sharpe_axis":"Sharpe ratio (separate axis)", "observations": "Observations", "weight_axis": "Weight", "mean": "mean", "single_trade":"Single closed position cycle",
                  "year_hover":"Year", "month_hover":"Month", "coverage_hover":"Coverage","annual_coverage":"Observed window: %{customdata[0]} to %{customdata[1]}<br>Coverage: %{customdata[2]}",
                  "cash":"Cash", "concentration":"Holdings count and concentration", "security_count":"Held securities", "security_count_axis":"Security count", "max_weight":"Maximum security weight", "max_weight_axis":"Maximum security weight", "hhi":"Security-weight HHI", "hhi_axis":"HHI (0–1)", "contribution":"Cumulative security price contribution (% initial equity)", "contribution_axis":"Share of initial equity", "fees_negative":"Cumulative fees (negative contribution)", "nav_change":"NAV change (reconciliation)", "turnover_events":"Actual fill dates", "unavailable":"Unavailable", "account_analysis_missing":"Daily holdings and fill-price reconciliation evidence is incomplete"},
    }.get(language, {})
    figures = []

    # This is the jQuantStats Data API output from the supplied return stream.
    try:
        figures.append(jqs_data.plots.snapshot(title=labels["jqs_snapshot"]))
    except Exception as exc:
        raise DashboardUnavailable(f"jQuantStats snapshot rendering failed: {exc}") from exc

    nav_rows = report.get("nav") or []
    nav_by_date = {_date(row.get("at", row.get("date"))): _finite(row.get("nav")) for row in nav_rows}
    nav_days = sorted(day for day, value in nav_by_date.items() if day is not None and value is not None)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[day.isoformat() for day in nav_days], y=[nav_by_date[day] for day in nav_days],
                             name=labels["nav"], mode="lines"))
    if benchmark:
        benchmark_levels = _nav_map(_select_benchmark_rows(report, benchmark_name), label="benchmark NAV")
        aligned = [day for day in nav_days if day in benchmark_levels]
        if aligned:
            base = benchmark_levels[aligned[0]]
            nav_base = nav_by_date[aligned[0]]
            benchmark_label=(labels["topix_benchmark"] if benchmark_name=="TOPIX" else
                             str(benchmark_name) if benchmark_name else labels["benchmark_rebased"])
            fig.add_trace(go.Scatter(x=[day.isoformat() for day in nav_days],
                                     y=[nav_base * benchmark_levels[day] / base if day in benchmark_levels else None for day in nav_days],
                                     name=benchmark_label, mode="lines", line={"dash":"dash"}, connectgaps=False))
    fig.update_layout(title=labels["nav"], xaxis_title=labels["date"], yaxis_title=labels["nav_axis"], hovermode="x unified")
    figures.append(fig)

    # Preserve full reported drawdown when complete; otherwise label this as a displayed-window calculation.
    drawdowns = [_finite(row.get("drawdown")) for row in nav_rows if isinstance(row, dict)]
    complete_dd = len(drawdowns) == len(nav_rows) and all(value is not None for value in drawdowns)
    if not complete_dd:
        peak = None; drawdowns = []
        for day in nav_days:
            value = nav_by_date[day]; peak = value if peak is None else max(peak, value)
            drawdowns.append(value / peak - 1)
    initial_value=_finite(report.get("initial_nav"))
    initial_known=report.get("nav_base_includes_initial") is True and initial_value is not None and initial_value>0
    if not complete_dd and initial_known:
        peak=initial_value; drawdowns=[]
        for day in nav_days:
            value=nav_by_date[day]; peak=max(peak,value)
            drawdowns.append(value/peak-1)
    dd_title=labels["dd_full"] if complete_dd or initial_known else labels["dd"]
    dd_fig = go.Figure(go.Scatter(x=[day.isoformat() for day in nav_days], y=drawdowns,
                                  mode="lines", fill="tozeroy", name=dd_title,
                                  hovertemplate=f"{labels['date']} %{{x}}<br>{labels['drawdown_axis']} %{{y:.2%}}<extra></extra>"))
    dd_fig.update_layout(title=dd_title, xaxis_title=labels["date"], yaxis_title=labels["drawdown_axis"], hovermode="x unified")
    dd_fig.update_yaxes(tickformat=".1%")
    figures.append(dd_fig)

    monthly_rows = {item["month"]: item for item in monthly if item.get("return") is not None}
    years = sorted({int(key[:4]) for key in monthly_rows})
    months = list(range(1, 13))
    z = [[monthly_rows.get(f"{year}-{month:02}", {}).get("return") for month in months] for year in years]
    coverage_terms={
        "zh_CN":{"start_partial":"起始月为部分窗口","initial_capital_to_month_end_observed":"明确初始资金至本月最后观察点；日历覆盖未验证","month_end_not_observed":"未观察到月末","calendar_month_end_observed_trading_day_completeness_unverified":"观察到月末日期；交易日完整性未验证"},
        "ja_JP":{"start_partial":"開始月は部分期間","initial_capital_to_month_end_observed":"明示初期資本から月内最終観測点まで；暦月カバレッジ未検証","month_end_not_observed":"月末未観測","calendar_month_end_observed_trading_day_completeness_unverified":"月末日観測済み；営業日データの完全性未検証"},
        "en_US":{"start_partial":"Partial start window","initial_capital_to_month_end_observed":"Explicit initial capital to last observed point; calendar coverage unverified","month_end_not_observed":"Month end not observed","calendar_month_end_observed_trading_day_completeness_unverified":"Month-end date observed; trading-day completeness unverified"},
    }.get(language,{})
    coverage = [["; ".join(coverage_terms.get(term,term) for term in monthly_rows.get(f"{year}-{month:02}", {}).get("coverage", [])) for month in months] for year in years]
    month_ticks=[f"{month:02}" for month in months]
    year_ticks=[str(year) for year in years]
    heat = go.Figure(go.Heatmap(x=month_ticks, y=year_ticks, z=z, customdata=coverage, colorscale="RdYlGn", zmid=0,
        colorbar={"tickformat":".1%"},
        hovertemplate=f"{labels['year_hover']} %{{y}} · {labels['month_hover']} %{{x}}<br>{labels['return']} %{{z:.2%}}<br>{labels['coverage_hover']} %{{customdata}}<extra></extra>"))
    heat.update_layout(title=labels["heat"], xaxis_title=labels["month_axis"], yaxis_title=labels["year_axis"],
                       xaxis={"type":"category","categoryorder":"array","categoryarray":month_ticks},
                       yaxis={"type":"category","categoryorder":"array","categoryarray":year_ticks,"tickmode":"array","tickvals":year_ticks,"ticktext":year_ticks})
    figures.append(heat)

    annual_rows=_annual_returns(report)
    annual_coverage={
        "zh_CN":{"observed_window; calendar completeness unverified":"观测窗口；日历覆盖完整性未验证",
            "explicit initial capital to last observed point; calendar completeness unverified":"明确初始资金至最后观测点；日历覆盖完整性未验证",
            "partial_start_or_window_only; calendar completeness unverified":"起始部分窗口或仅显示窗口；日历覆盖完整性未验证"},
        "ja_JP":{"observed_window; calendar completeness unverified":"観測ウィンドウ；暦カバレッジ完全性は未検証",
            "explicit initial capital to last observed point; calendar completeness unverified":"明示初期資本から最終観測点まで；暦カバレッジ完全性は未検証",
            "partial_start_or_window_only; calendar completeness unverified":"開始部分または表示ウィンドウのみ；暦カバレッジ完全性は未検証"},
        "en_US":{"observed_window; calendar completeness unverified":"Observed window; calendar completeness unverified",
            "explicit initial capital to last observed point; calendar completeness unverified":"Explicit initial capital through last observed point; calendar completeness unverified",
            "partial_start_or_window_only; calendar completeness unverified":"Partial start or displayed window only; calendar completeness unverified"},
    }.get(language,{})
    annual_custom=[[row["start_at"],row["end_at"],annual_coverage.get(row["coverage"],row["coverage"])] for row in annual_rows]
    annual=go.Figure(go.Bar(x=[str(row["year"]) for row in annual_rows],y=[row["return"] for row in annual_rows],
        customdata=annual_custom,name=labels["annual"],hovertemplate=f"{labels['year_hover']} %{{x}}<br>{labels['return']} %{{y:.2%}}<br>{labels['annual_coverage']}<extra></extra>"))
    annual.update_layout(title=labels["annual"],xaxis_title=labels["year_axis"],yaxis_title=labels["return"],xaxis={"type":"category"})
    annual.update_yaxes(tickformat=".1%")
    figures.append(annual)

    annualization={"daily":252,"weekly":52,"monthly":12}.get(report.get("nav_frequency"))
    rolling_returns = [None] * len(returns); rolling_vol = [None] * len(returns); rolling_sharpe = [None] * len(returns)
    if rolling_window <= len(returns):
        for end in range(rolling_window - 1, len(returns)):
            window = returns[end - rolling_window + 1:end + 1]
            try: growth = _finite(math.prod(1 + value for value in window) - 1)
            except OverflowError: growth = None
            try: deviation = statistics.stdev(window) if len(window) > 1 else None
            except (OverflowError, statistics.StatisticsError): deviation = None
            vol = _finite(deviation * math.sqrt(annualization)) if deviation is not None and annualization else None
            avg = statistics.mean(window)
            sharpe = _finite(avg / deviation * math.sqrt(annualization)) if deviation is not None and deviation > 0 and annualization else None
            rolling_returns[end] = growth
            rolling_vol[end] = vol
            rolling_sharpe[end] = sharpe
    from plotly.subplots import make_subplots
    roll = make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.1,row_heights=[.62,.38],
                         subplot_titles=(labels["period_return"]+" / "+labels["period_volatility"],labels["sharpe_axis"]))
    roll.add_trace(go.Scatter(x=[day.isoformat() for day in dates], y=rolling_returns, name=labels["period_return"],
        hovertemplate=f"{labels['date']} %{{x}}<br>{labels['period_return']} %{{y:.2%}}<extra></extra>"),row=1,col=1)
    roll.add_trace(go.Scatter(x=[day.isoformat() for day in dates], y=rolling_vol, name=labels["period_volatility"],
        hovertemplate=f"{labels['date']} %{{x}}<br>{labels['period_volatility']} %{{y:.2%}}<extra></extra>"),row=1,col=1)
    roll.add_trace(go.Scatter(x=[day.isoformat() for day in dates], y=rolling_sharpe, name=labels["period_sharpe"],
        hovertemplate=f"{labels['date']} %{{x}}<br>{labels['period_sharpe']} %{{y:.3f}}<extra></extra>"),row=2,col=1)
    roll.update_layout(title=labels["roll"],hovermode="x unified",yaxis={"title":labels["ratio_axis"],"tickformat":".1%"},
                       yaxis2={"title":labels["sharpe_axis"]})
    roll.update_xaxes(title_text=labels["date"],row=2,col=1)
    figures.append(roll)

    if benchmark:
        benchmark_dates, benchmark_returns = benchmark
        benchmark_by_day = dict(zip(benchmark_dates, benchmark_returns))
        strategy_by_day = dict(zip(dates, returns))
        aligned_days=[]; strategy_growth=[]; benchmark_growth=[]; strategy_level=1.0; benchmark_level=1.0
        for day in dates:
            aligned_days.append(day)
            if day not in benchmark_by_day:
                strategy_growth.append(None); benchmark_growth.append(None)
                strategy_level=1.0; benchmark_level=1.0
                continue
            strategy_level *= 1 + strategy_by_day[day]
            benchmark_level *= 1 + benchmark_by_day[day]
            strategy_growth.append(strategy_level - 1); benchmark_growth.append(benchmark_level - 1)
        if any(value is not None for value in benchmark_growth):
            relative = go.Figure()
            relative.add_trace(go.Scatter(x=[day.isoformat() for day in aligned_days], y=strategy_growth, name=labels["strategy"], connectgaps=False))
            relative.add_trace(go.Scatter(x=[day.isoformat() for day in aligned_days], y=benchmark_growth, name=labels["benchmark"], connectgaps=False))
            relative.update_layout(title=labels["relative"], xaxis_title=labels["date"], yaxis_title=labels["return"], hovermode="x unified")
            relative.update_yaxes(tickformat=".1%")
        else:
            relative = go.Figure()
            relative.add_annotation(text=labels["benchmark_insufficient"] if benchmark_options(report) else labels["benchmark_missing"], x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
            relative.update_layout(title=labels["relative"])
        figures.append(relative)
    else:
        relative = go.Figure()
        relative.add_annotation(text=labels["benchmark_insufficient"] if benchmark_options(report) else labels["benchmark_missing"], x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
        relative.update_layout(title=labels["relative"])
        figures.append(relative)

    hist = go.Figure(go.Histogram(x=returns, nbinsx=30, name=labels["return"],
        hovertemplate=f"{labels['return']} %{{x:.2%}}<br>{labels['observations']} %{{y}}<extra></extra>"))
    hist.update_layout(title=labels["hist"], xaxis_title=labels["return"], yaxis_title=labels["observations"])
    hist.update_xaxes(tickformat=".1%"); hist.update_yaxes(tickformat="d")
    figures.append(hist)

    accounts = report.get("account_path") or []
    weight_rows = []
    for row in accounts:
        day = _date(row.get("at")) if isinstance(row, dict) else None
        equity = _finite(row.get("equity")) if isinstance(row, dict) else None
        if day is None or equity is None or equity <= 0:
            continue
        weights = {"cash": _finite(row.get("cash")) / equity if _finite(row.get("cash")) is not None else None}
        universe=row.get("position_universe")
        if isinstance(universe,list):
            for code in universe:
                weights[str(code)]=0.0
        for position in row.get("positions") or []:
            market_value = _finite(position.get("market_value"))
            if market_value is None and _finite(position.get("quantity")) is not None and _finite(position.get("mark_price")) is not None:
                market_value = _finite(position.get("quantity")) * _finite(position.get("mark_price"))
            if market_value is not None:
                weights[str(position.get("code") or "(unknown)")] = market_value / equity
        weight_rows.append((day, weights))
    if weight_rows:
        series = sorted({name for _, row in weight_rows for name in row})
        holding = go.Figure()
        for name in series:
            display_name = labels["cash"] if name == "cash" else name
            holding.add_trace(go.Scatter(x=[day.isoformat() for day, _ in weight_rows],
                y=[weights.get(name) for _, weights in weight_rows], name=display_name, stackgroup="weights", mode="lines"))
        holding.update_layout(title=labels["hold"], xaxis_title=labels["date"], yaxis_title=labels["weight_axis"], hovermode="x unified")
    else:
        holding = go.Figure()
        holding.add_annotation(text=labels["position_missing"], x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
        holding.update_layout(title=labels["hold"])
    figures.append(holding)

    closed = _closed_trades(report)
    if closed["trades"]:
        trade_returns = [item["return"] for item in closed["trades"]]
        mean_return = statistics.mean(trade_returns)
        if len(trade_returns)==1:
            item=closed["trades"][0]
            width=max(0.005,abs(mean_return)*0.1)
            trade_fig=go.Figure(go.Bar(x=trade_returns,y=[1],width=[width],name=labels["single_trade"],
                customdata=[[item.get("code"),item.get("date"),item.get("net_pnl")]],
                hovertemplate=f"{labels['single_trade']}<br>{labels['return']} %{{x:.2%}}<br>{labels['observations']} %{{y:d}}<br>%{{customdata[0]}} · %{{customdata[1]}}<extra></extra>"))
            margin=max(width*2,0.005)
            trade_fig.update_xaxes(range=[mean_return-margin,mean_return+margin])
            trade_fig.update_yaxes(range=[0,1.2],dtick=1)
        else:
            trade_fig = go.Figure(go.Histogram(x=trade_returns, nbinsx=30, name=labels["trades"],
                hovertemplate=f"{labels['return']} %{{x:.2%}}<br>{labels['observations']} %{{y}}<extra></extra>"))
        trade_fig.add_vline(x=mean_return, line_dash="dash", annotation_text=f"{labels['mean']} {mean_return:.2%}")
    else:
        trade_fig = go.Figure()
        trade_fig.add_annotation(text=labels["closed_missing"], x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
    trade_fig.update_layout(title=labels["trades"], xaxis_title=labels["return"], yaxis_title=labels["observations"])
    trade_fig.update_xaxes(tickformat=".1%"); trade_fig.update_yaxes(tickformat="d")
    figures.append(trade_fig)

    realized=go.Figure()
    dated=sorted((( _date(item.get("date")),item) for item in closed["trades"] if _date(item.get("date")) is not None),key=lambda pair:pair[0])
    if dated:
        cumulative=0.0; values=[]; days=[]
        for day,item in dated:
            cumulative+=item["net_pnl"]; days.append(day.isoformat()); values.append(cumulative)
        realized.add_trace(go.Scatter(x=days,y=values,mode="lines+markers",name=labels["realized"],
            hovertemplate=f"{labels['date']} %{{x}}<br>{labels['realized']} %{{y:.2f}}<extra></extra>"))
    else:
        realized.add_annotation(text=labels["closed_missing"],x=.5,y=.5,xref="paper",yref="paper",showarrow=False)
    realized.update_layout(title=labels["realized"],xaxis_title=labels["date"],yaxis_title=labels["realized"],hovermode="x unified")
    figures.append(realized)

    fee_rows=report.get("account_path")
    fee_days=[]; fee_values=[]
    if isinstance(fee_rows,list) and fee_rows:
        for row in fee_rows:
            day=_date(row.get("at")) if isinstance(row,dict) else None
            value=_finite(row.get("cumulative_fees")) if isinstance(row,dict) else None
            if day is not None and value is not None:
                fee_days.append(day.isoformat()); fee_values.append(value)
    fee_fig=go.Figure()
    if len(fee_days)==len(nav_days) and fee_days==[day.isoformat() for day in nav_days]:
        fee_fig.add_trace(go.Scatter(x=fee_days,y=fee_values,mode="lines",name=labels["fees_chart"],
            hovertemplate=f"{labels['date']} %{{x}}<br>{labels['fees_chart']} %{{y:.2f}}<extra></extra>"))
    else:
        fee_fig.add_annotation(text=labels["fee_missing"],x=.5,y=.5,xref="paper",yref="paper",showarrow=False)
    fee_fig.update_layout(title=labels["fees_chart"],xaxis_title=labels["date"],yaxis_title=labels["fees_axis"],hovermode="x unified")
    turnover_rows=report.get("daily_turnover")
    turnover_by_day={}
    if isinstance(turnover_rows,list):
        for row in turnover_rows:
            if not isinstance(row,dict): continue
            day=_date(row.get("at")); value=_finite(row.get("gross_traded_turnover"))
            if day is not None and value is not None: turnover_by_day[day]=value
    turnover_fig=go.Figure()
    if all(day in turnover_by_day for day in nav_days) and len(turnover_by_day)==len(nav_days):
        turnover_dates=[day.isoformat() for day in nav_days]
        turnover_values=[turnover_by_day[day] for day in nav_days]
        turnover_fig.add_trace(go.Bar(x=[day.isoformat() for day in nav_days],
            y=turnover_values,name=labels["turnover_chart"],
            hovertemplate=f"{labels['date']} %{{x}}<br>{labels['turnover_chart']} %{{y:.2%}}<extra></extra>"))
        nonzero=[(day,value) for day,value in zip(turnover_dates,turnover_values) if value > 0]
        if nonzero:
            turnover_fig.add_trace(go.Scatter(x=[day for day,_ in nonzero],y=[value for _,value in nonzero],
                mode="markers",name=labels["turnover_events"],marker={"size":8,"symbol":"circle-open","line":{"width":2}},
                hovertemplate=f"{labels['date']} %{{x}}<br>{labels['turnover_events']} %{{y:.2%}}<extra></extra>"))
    else:
        turnover_fig.add_annotation(text=labels["turnover_missing"],x=.5,y=.5,xref="paper",yref="paper",showarrow=False)
    turnover_fig.update_layout(title=labels["turnover_chart"],xaxis_title=labels["date"],yaxis_title=labels["turnover_axis"],hovermode="x unified",margin={"l":70,"r":20,"t":65,"b":50})
    turnover_fig.update_yaxes(tickformat=".1%")
    figures.extend((fee_fig,turnover_fig))

    account_analysis = analyze_account_path(report)
    concentration = go.Figure()
    if account_analysis["available"]:
        rows = account_analysis["holdings"]
        x = [row["at"] for row in rows]
        concentration.add_trace(go.Bar(x=x, y=[row["security_count"] for row in rows],
            name=labels["security_count"], yaxis="y", opacity=.42))
        concentration.add_trace(go.Scatter(x=x, y=[row["max_security_weight"] for row in rows],
            name=labels["max_weight"], yaxis="y2", mode="lines+markers", marker={"size":4}))
        concentration.add_trace(go.Scatter(x=x, y=[row["security_hhi"] for row in rows],
            name=labels["hhi"], yaxis="y3", mode="lines"))
        concentration.update_layout(title=labels["concentration"], xaxis_title=labels["date"],
            **_concentration_axes([row["security_count"] for row in rows], labels), hovermode="x unified")
    else:
        concentration.add_annotation(text=labels["account_analysis_missing"],
            x=.5,y=.5,xref="paper",yref="paper",showarrow=False)
        concentration.update_layout(title=labels["concentration"])
    figures.append(concentration)

    contribution = go.Figure()
    if account_analysis["available"]:
        cumulative_fees = 0.0
        fee_points = []
        nav_points = []
        running_equity_change = 0.0
        for row in account_analysis["daily_contributions"]:
            cumulative_fees += row["fees"]
            fee_points.append(-cumulative_fees / account_analysis["reconciliation"]["initial_equity"])
            running_equity_change += row["equity_change"]
            nav_points.append(running_equity_change / account_analysis["reconciliation"]["initial_equity"])
        dates = [row["at"] for row in account_analysis["daily_contributions"]]
        for item in account_analysis["contributions"]:
            code = item["code"]
            running=0.0; values=[]
            for value in account_analysis["per_security_daily"].get(code, []):
                running += value
                values.append(running / account_analysis["reconciliation"]["initial_equity"])
            contribution.add_trace(go.Scatter(x=dates,y=values,name=code,mode="lines"))
        contribution.add_trace(go.Scatter(x=dates,y=fee_points,name=labels["fees_negative"],mode="lines",line={"dash":"dash"}))
        contribution.add_trace(go.Scatter(x=dates,y=nav_points,
            name=labels["nav_change"],mode="lines",line={"dash":"dot"}))
        contribution.update_layout(title=labels["contribution"],xaxis_title=labels["date"],
            yaxis_title=labels["contribution_axis"],hovermode="x unified")
        contribution.update_yaxes(tickformat=".1%")
    else:
        contribution.add_annotation(text=labels["account_analysis_missing"],
            x=.5,y=.5,xref="paper",yref="paper",showarrow=False)
        contribution.update_layout(title=labels["contribution"])
    figures.append(contribution)
    figures.extend(_price_execution_figures(price_diagnostics, language, report))
    figures.append(_regime_history_figure(report, language))
    return _apply_dark_theme(figures), closed


def build_dashboard_html(report: dict, output_dir, *, rolling_window=21, language="zh_CN", benchmark_name=None,
                         research_run_directory=None, progress_callback=None):
    """Create a fully local, self-contained HTML report using jQuantStats and Plotly."""
    missing = [name for name, state in dependency_status().items()
               if isinstance(state, dict) and not state["discoverable"]]
    if missing:
        raise DashboardUnavailable("Missing optional dependencies: " + ", ".join(missing))
    if not isinstance(report, dict):
        raise ValueError("report must be an object")
    if not isinstance(rolling_window, int) or rolling_window < 2 or rolling_window > 504:
        raise ValueError("rolling_window must be an integer between 2 and 504")
    if progress_callback:
        progress_callback("validating")
    diag_locale = language if language in {"zh_CN", "ja_JP", "en_US"} else "en_US"
    if report.get("model") != "daily_bar_next_open_research_v1":
        price_diagnostics = {"status":"unavailable", "reason_code":"unsupported_report_model",
            "input_hash":None, "order_schedule_hash":None, "series":[], "labels":{}}
    elif research_run_directory is None:
        price_diagnostics = {"status":"unavailable", "reason_code":"exact_run_directory_missing",
            "input_hash":None, "order_schedule_hash":None, "series":[], "labels":{}}
    else:
        try:
            from .price_execution_diagnostics import build_price_execution_diagnostics
            price_diagnostics = build_price_execution_diagnostics(research_run_directory, report, language=diag_locale)
        except (OSError, ValueError, TypeError):
            # Integrity failures must produce an unavailable chart, never a
            # plausible overlay from another run or a partially verified file.
            price_diagnostics = {"status":"unavailable", "reason_code":"frozen_input_integrity_failed",
                "input_hash":None, "order_schedule_hash":None, "series":[], "labels":{}}
    frequency = report.get("nav_frequency")
    annualization={"daily":252,"weekly":52,"monthly":12}.get(frequency)
    observation_days, dates, returns, _ = _strategy_series(report)
    benchmark = _benchmark_series(report, observation_days, benchmark_name)
    import polars as pl
    from jquantstats import Data
    import plotly.io as pio

    series_names = {"zh_CN": ("策略", "基准"), "ja_JP": ("戦略", "ベンチマーク"), "en_US": ("Strategy", "Benchmark")}
    strategy_label, benchmark_label = series_names.get(language, series_names["en_US"])
    # Full-period figures and strategy-only risk always use every strategy NAV
    # observation. jQuantStats aligns benchmark inputs with an inner join, so
    # relative statistics are calculated from a second, explicitly paired view.
    returns_frame = pl.DataFrame({"Date": dates, strategy_label: returns})
    jqs_data = Data.from_returns(returns=returns_frame, rf=0.0, benchmark=None, null_strategy="raise")
    library_metrics = _library_stats(jqs_data, False, strategy_label, annualization)
    if progress_callback:
        progress_callback("calculating")
    if benchmark is not None:
        benchmark_dates, benchmark_returns = benchmark
        benchmark_by_day = dict(zip(benchmark_dates, benchmark_returns))
        strategy_by_day = dict(zip(dates, returns))
        paired_days = [day for day in dates if day in benchmark_by_day]
        if len(paired_days) >= 2:
            paired_returns = pl.DataFrame({"Date": paired_days,
                strategy_label: [strategy_by_day[day] for day in paired_days]})
            paired_benchmark = pl.DataFrame({"Date": paired_days,
                benchmark_label: [benchmark_by_day[day] for day in paired_days]})
            relative_data=Data.from_returns(returns=paired_returns,rf=0.0,benchmark=paired_benchmark,null_strategy="raise")
            relative_metrics=_library_stats(relative_data,True,strategy_label,annualization)
            reasons=library_metrics.setdefault("_unavailable_reasons",{})
            library_metrics["information_ratio"] = relative_metrics.get("information_ratio")
            library_metrics["beta"] = relative_metrics.get("beta")
            if library_metrics["beta"] is None:
                reasons["beta"] = relative_metrics.get("_unavailable_reasons",{}).get("beta", "jQuantStats beta is unavailable")
            else:
                reasons.pop("beta", None)
            corr, corr_reason = _paired_correlation(
                [strategy_by_day[day] for day in paired_days],
                [benchmark_by_day[day] for day in paired_days])
            library_metrics["correlation"] = corr
            if corr is None:
                reasons["correlation"] = corr_reason
            else:
                reasons.pop("correlation", None)
            alpha, alpha_reason = _annualized_alpha(
                [strategy_by_day[day] for day in paired_days],
                [benchmark_by_day[day] for day in paired_days],library_metrics["beta"],annualization)
            library_metrics["alpha"] = alpha
            if alpha is None:
                reasons["alpha"] = alpha_reason
            else:
                reasons.pop("alpha", None)
            if annualization is not None and len(paired_days) > 1:
                active = [strategy_by_day[day] - benchmark_by_day[day] for day in paired_days]
                library_metrics["tracking_error"] = _tracking_error(active, annualization)
                library_metrics.setdefault("_unavailable_reasons", {}).pop("tracking_error", None)
            else:
                library_metrics["tracking_error"] = None
                library_metrics.setdefault("_unavailable_reasons", {})["tracking_error"] = (
                    "sampling frequency is unknown or fewer than two aligned returns")
            for key,value in relative_metrics.get("_unavailable_reasons",{}).items():
                if key == "information_ratio" and library_metrics.get("information_ratio") is None:
                    reasons[key]=value
            if library_metrics.get("information_ratio") is not None:
                reasons.pop("information_ratio",None)
            if any(library_metrics.get(key) is not None for key in ("information_ratio","alpha","beta","correlation","tracking_error")):
                reasons.pop("benchmark_metrics",None)
            if library_metrics.get("alpha") is not None and library_metrics.get("beta") is not None:
                reasons.pop("benchmark_greeks",None)
        else:
            library_metrics.update(tracking_error=None,information_ratio=None,alpha=None,beta=None,correlation=None)
            library_metrics.setdefault("_unavailable_reasons",{})["benchmark_metrics"]="fewer than two adjacent NAV-date pairs align"
    summary = summarize_report(report)
    account_analysis = analyze_account_path(report)
    if progress_callback:
        progress_callback("rendering")
    figures, closed = _build_figures(report, dates, returns, summary["monthly_returns"], rolling_window,
                                     benchmark, jqs_data, language, benchmark_name, price_diagnostics)

    titles = {
        "zh_CN": ("策略绩效报告", "由 jQuantStats Data API 对报告收益序列进行统计与图表渲染；原执行模型、持仓、费用不被重算。"),
        "ja_JP": ("戦略パフォーマンスレポート", "jQuantStats Data APIが報告済みリターンを集計・描画します。実行モデル、保有、費用は再計算しません。"),
        "en_US": ("Strategy performance report", "jQuantStats Data API analyzes reported returns only; execution, holdings and fees are not replayed."),
    }.get(language, ("Strategy performance report", "jQuantStats Data API analyzes reported returns only."))
    metric_names = {"zh_CN": {"period_return": "区间收益", "annualized_return": "年化收益", "sharpe": "Sharpe（RF=0）", "sortino": "Sortino", "calmar": "Calmar", "volatility": "波动率", "max_drawdown": "最大回撤", "max_drawdown_days": "最长回撤持续（日历日）", "tracking_error":"跟踪误差", "information_ratio": "信息比率", "alpha": "年化 Alpha（RF=0）", "beta": "Beta", "correlation": "相关性"},
                    "ja_JP": {"period_return": "期間リターン", "annualized_return": "年率リターン", "sharpe": "Sharpe（RF=0）", "sortino": "Sortino", "calmar": "Calmar", "volatility": "変動率", "max_drawdown": "最大ドローダウン", "max_drawdown_days": "最長DD期間（日）", "tracking_error":"トラッキングエラー", "information_ratio": "情報比率", "alpha": "年率Alpha（RF=0）", "beta": "Beta", "correlation": "相関"},
                    "en_US": {"period_return": "Period return", "annualized_return": "Annualized return", "sharpe": "Sharpe (RF=0)", "sortino": "Sortino", "calmar": "Calmar", "volatility": "Volatility", "max_drawdown": "Maximum drawdown", "max_drawdown_days": "Longest drawdown (calendar days)", "tracking_error":"Tracking error", "information_ratio": "Information ratio", "alpha": "Annualized alpha (RF=0)", "beta": "Beta", "correlation": "Correlation"}}.get(language, {})
    trade_summary = _trade_summary(closed)
    dd_detail = _drawdown_duration(report.get("nav") or [],
        report.get("initial_nav") if report.get("nav_base_includes_initial") is True else None,
        report.get("initial_at"))
    summary_metrics = {**library_metrics,
        "period_return": summary.get("period_return") if summary.get("period_return") is not None else summary.get("observed_window_return"),
        "annualized_return": summary.get("annualized_return"),
        "max_drawdown": summary.get("max_drawdown"),
        "max_drawdown_days": dd_detail.get("calendar_days") if dd_detail else None}
    library_unavailable = library_metrics.get("_unavailable_reasons", {})
    # Period return/annualization/max drawdown cards share the native report's
    # explicit initial-capital/window basis. Calmar is recomputed on that same
    # basis instead of mixing the jQuantStats N-1 return stream with native NAV.
    annual_return = summary_metrics.get("annualized_return")
    native_dd = summary_metrics.get("max_drawdown")
    if annual_return is not None and native_dd is not None and native_dd < 0:
        summary_metrics["calmar"] = annual_return / abs(native_dd)
        library_unavailable.pop("calmar", None)
    elif annual_return is not None and native_dd == 0:
        summary_metrics["calmar"] = None
        library_unavailable["calmar"] = "native report maximum drawdown is zero"
    else:
        summary_metrics["calmar"] = None
        library_unavailable["calmar"] = "native full-window annual return or drawdown basis unavailable"
    metric_cards = []
    for key, name in metric_names.items():
        value = summary_metrics.get(key)
        text = "—" if value is None else (f"{value:.2%}" if key in {"period_return", "annualized_return", "volatility", "max_drawdown", "tracking_error", "alpha"} else f"{value:.4f}")
        metric_cards.append(f'<div class="metric"><span>{html.escape(name)}</span><b>{text}</b></div>')
    trade_names = {"zh_CN": {"closed_count":"已平仓交易数", "win_rate":"胜率", "mean_return":"平均净收益", "median_return":"中位净收益", "profit_factor":"净利润因子", "payoff_ratio":"盈亏比"},
                   "ja_JP": {"closed_count":"完了取引数", "win_rate":"勝率", "mean_return":"平均純リターン", "median_return":"純リターン中央値", "profit_factor":"純利益ファクター", "payoff_ratio":"ペイオフ比"},
                   "en_US": {"closed_count":"Closed position cycles", "win_rate":"Win rate", "mean_return":"Mean net return", "median_return":"Median net return", "profit_factor":"Net profit factor", "payoff_ratio":"Payoff ratio"}}.get(language, {})
    trade_cards=[]
    for key, name in trade_names.items():
        value=trade_summary.get(key)
        if key=="closed_count": text=str(value)
        elif value is None: text="—"
        elif key in {"win_rate","mean_return","median_return"}: text=f"{value:.2%}"
        else: text=f"{value:.3f}"
        trade_cards.append(f'<div class="metric"><span>{html.escape(name)}</span><b>{text}</b></div>')
    plot_fragments = []
    for index, figure in enumerate(figures):
        plot_fragments.append(pio.to_html(figure, full_html=False, include_plotlyjs="inline" if index == 0 else False,
                                          config={"scrollZoom": True, "displaylogo": False, "responsive": True}))
    if progress_callback:
        progress_callback("writing")
    identity = {key: report.get(key) for key in ("strategy_hash", "data_snapshot_hash", "input_hash", "order_schedule_hash", "engine", "model", "pit_guarantee", "nav_frequency") if key in report}
    identity["rolling_window"] = rolling_window
    identity["annualization_periods_per_year"] = annualization
    identity["strategy_library_return_basis"] = "consecutive reported NAV observations; N-1 returns; initial capital to first NAV excluded"
    identity["strategy_library_return_count"] = len(returns)
    identity["strategy_library_return_start"] = dates[0].isoformat() if dates else None
    identity["strategy_library_return_end"] = dates[-1].isoformat() if dates else None
    identity["native_summary_return_basis"] = summary.get("return_basis")
    identity["risk_free_rate"] = 0.0
    identity["risk_free_rate_basis"] = "fixed at zero; no excess-return adjustment"
    identity["account_path_sha256"] = hashlib.sha256(json.dumps(report.get("account_path"),sort_keys=True,
        ensure_ascii=False,separators=(",",":"),allow_nan=False,default=str).encode()).hexdigest() if "account_path" in report else None
    identity["trades_sha256"] = hashlib.sha256(json.dumps(report.get("trades"),sort_keys=True,
        ensure_ascii=False,separators=(",",":"),allow_nan=False,default=str).encode()).hexdigest() if "trades" in report else None
    identity["account_analysis_available"] = account_analysis["available"]
    identity["account_analysis_reason"] = account_analysis["reason"]
    identity["daily_turnover_sha256"] = hashlib.sha256(json.dumps(report.get("daily_turnover"),sort_keys=True,
        ensure_ascii=False,separators=(",",":"),allow_nan=False,default=str).encode()).hexdigest() if "daily_turnover" in report else None
    identity["order_schedule_sha256"] = hashlib.sha256(json.dumps(report.get("order_schedule"),sort_keys=True,
        ensure_ascii=False,separators=(",",":"),allow_nan=False,default=str).encode()).hexdigest() if "order_schedule" in report else None
    identity["benchmark_supplied"] = benchmark is not None
    identity["benchmark_requested"] = bool(benchmark_options(report))
    identity["benchmark_unavailable_reason"] = ("fewer than two adjacent strategy NAV return pairs aligned" if identity["benchmark_requested"] and benchmark is None else None)
    selected_benchmark_name = benchmark_name
    if benchmark is not None and selected_benchmark_name is None:
        options = benchmark_options(report)
        selected_benchmark_name = options[0] if options else "Benchmark"
    identity["benchmark_name"] = selected_benchmark_name if benchmark is not None else None
    identity["benchmark_provenance"] = report.get("benchmark_provenance")
    identity["benchmark_alignment"] = {"observation_count":len(benchmark[0]),
        "first_return_at":benchmark[0][0].isoformat(),"last_return_at":benchmark[0][-1].isoformat(),
        "basis":"same left/right adjacent strategy NAV dates; missing levels are not bridged"} if benchmark is not None else None
    identity["initial_nav"] = report.get("initial_nav") if report.get("nav_base_includes_initial") is True else None
    identity["initial_at"] = report.get("initial_at")
    identity["fee_evidence"] = report.get("fees")
    identity["closed_trade_count"] = len(closed["trades"])
    identity["price_execution_diagnostics"] = {
        "status":price_diagnostics.get("status"), "reason_code":price_diagnostics.get("reason_code"),
        "input_hash":price_diagnostics.get("input_hash"),
        "order_schedule_hash":price_diagnostics.get("order_schedule_hash"),
        "event_counts":price_diagnostics.get("event_counts"),
        "source_basis":"verified sibling research_inputs.json; schedule and fill/skip markers remain distinct",
    }
    regime = report.get("regime_observer") if isinstance(report.get("regime_observer"), dict) else {}
    identity["regime_history"] = {
        "available":bool(regime.get("mode") == "historical_reconstruction" and regime.get("input_sha256")
                          and isinstance(regime.get("timeline"), list) and regime.get("timeline")),
        "mode":regime.get("mode"), "knowledge_status":regime.get("knowledge_status"),
        "input_sha256":regime.get("input_sha256"),
        "timeline_count":len(regime.get("timeline", [])) if isinstance(regime.get("timeline"), list) else 0,
        "basis":"read-only report timeline; current Store is never used to reconstruct history",
    }
    identity["strategy_parameters"] = report.get("strategy_parameters")
    identity["assumptions"] = report.get("assumptions")
    identity_json = html.escape(json.dumps(identity, ensure_ascii=False, sort_keys=True, default=str))
    assumptions_json=html.escape(json.dumps({"assumptions":report.get("assumptions"),"warnings":summary.get("warnings"),
        "fee_reason":summary.get("fees_reason"),"trade_evidence":closed.get("reason"),"drawdown_duration":dd_detail,
        "library_stat_unavailable_reasons":library_unavailable,
        "account_analysis":{"available":account_analysis["available"],"reason":account_analysis["reason"],
            "reconciliation":account_analysis.get("reconciliation")},
        "closed_trade_summary":trade_summary},ensure_ascii=False,indent=2,default=str))
    title = html.escape(titles[0])
    subtitle = html.escape(titles[1])
    nav_count = len(report.get("nav") or [])
    dependency_versions = dependency_status()
    version_line = html.escape("jquantstats " + str(dependency_versions["jquantstats"]["version"]) +
                                " · Plotly " + str(dependency_versions["plotly"]["version"]))
    metadata_labels={
        "zh_CN": f"{nav_count} 个NAV观察点 · {frequency or '频率未知'} · 滚动窗口 {rolling_window} 期 · 年化周期 {annualization if annualization else '不可用'} · jQuantStats风险收益使用相邻NAV的N-1期，不含初始资金至首个NAV区间",
        "ja_JP": f"NAV観測 {nav_count} 件 · 頻度 {frequency or '不明'} · ローリング窓 {rolling_window} 期 · 年率換算 {annualization if annualization else '利用不可'} · jQuantStatsのリスク/リターンは隣接NAVのN-1区間で、初期資本から最初のNAVまでを含みません",
        "en_US": f"{nav_count} NAV observations · {frequency or 'frequency unknown'} · rolling window {rolling_window} periods · annualization {annualization if annualization else 'unavailable'} · jQuantStats risk/returns use N-1 adjacent NAV periods and exclude initial capital to first NAV",
    }
    metadata = html.escape(metadata_labels.get(language, metadata_labels["en_US"]))
    executions = _execution_rows(report)
    skipped = report.get("skipped_orders")
    fee_value = summary.get("fees")
    fee_reason = summary.get("fees_reason")
    basis = {"zh_CN": {
        "execution": "成交与跳过订单（订单条数不等于已平仓交易数）", "filled": "实际成交", "skipped": "跳过的订单",
        "fee": "已知总费用", "fee_missing": "费用不可用", "turnover": "平均单边实际换手",
        "basis": "NAV 估值时点", "dd": "最长回撤：{days} 个日历日，{start} 至 {end}；口径：{basis}",
        "missing_stats": "统计不可用原因", "no_execution": "没有可用的成交明细", "no_skipped": "没有跳过订单记录",
        "open_sample": "开盘采样", "no_closed":"没有完整平仓仓位周期", "fill_columns": ["时间", "代码", "方向", "数量", "成交价", "费用"], "closed_columns":["平仓时间","代码","数量","净盈亏","净收益"],
        "skip_columns": {"at":"时间","date":"日期","signal_date":"信号日","execution_date":"执行日","code":"代码","side":"方向","quantity":"数量","sizing_price":"定量参考价","price":"成交价","open_price":"开盘价","fee":"费用","cash_available":"可用现金","cash_required":"所需现金","reason":"原因"},
        "buy":"买入", "sell":"卖出", "gap_reason":"开盘跳空超过前收盘现金预算"},
        "ja_JP": {
        "execution": "約定とスキップ注文（注文数は完了取引数ではありません）", "filled": "実約定", "skipped": "スキップ注文",
        "fee": "確認済み総手数料", "fee_missing": "手数料を確認できません", "turnover": "平均片道実績回転率",
        "basis": "NAV評価時点", "dd": "最長ドローダウン：{days}暦日、{start}から{end}；基準：{basis}",
        "missing_stats": "統計を利用できない理由", "no_execution": "約定明細がありません", "no_skipped": "スキップ注文の記録がありません",
        "open_sample": "始値時点サンプル", "no_closed":"完了したポジションサイクルはありません", "fill_columns": ["時刻", "コード", "売買", "数量", "約定価格", "手数料"], "closed_columns":["決済時刻","コード","数量","純損益","純リターン"],
        "skip_columns": {"at":"時刻","date":"日付","signal_date":"シグナル日","execution_date":"執行日","code":"コード","side":"売買","quantity":"数量","sizing_price":"数量計算価格","price":"約定価格","open_price":"始値","fee":"手数料","cash_available":"利用可能現金","cash_required":"必要現金","reason":"理由"},
        "buy":"買い", "sell":"売り", "gap_reason":"寄り付きギャップが前日終値時点の現金予算を超過"},
        "en_US": {
        "execution": "Fills and skipped orders (order count is not closed-trade count)", "filled": "Executed fills", "skipped": "Skipped orders",
        "fee": "Known total fees", "fee_missing": "Fees unavailable", "turnover": "Average realized one-way turnover",
        "basis": "NAV valuation sampling", "dd": "Longest drawdown: {days} calendar days, {start} to {end}; basis: {basis}",
        "missing_stats": "Unavailable-statistic reasons", "no_execution": "No fill detail is available", "no_skipped": "No skipped-order records",
        "open_sample": "Open-sampled", "no_closed":"No fully closed position cycles", "fill_columns": ["Time", "Code", "Side", "Quantity", "Fill price", "Fee"], "closed_columns":["Close time","Code","Quantity","Net P&L","Net return"],
        "skip_columns": {"at":"Time","date":"Date","signal_date":"Signal date","execution_date":"Execution date","code":"Code","side":"Side","quantity":"Quantity","sizing_price":"Sizing reference","price":"Fill price","open_price":"Open price","fee":"Fee","cash_available":"Cash available","cash_required":"Cash required","reason":"Reason"},
        "buy":"Buy", "sell":"Sell", "gap_reason":"Opening gap exceeded prior-close cash budget"}}.get(language, {})
    fill_rows = []
    if executions is not None:
        for row in executions:
            side = str(row.get("side", row.get("action", "—"))).lower()
            fill_rows.append({"at": row.get("occurred_at", row.get("at", row.get("date", "—"))), "code": row.get("code", "—"),
                "side": basis.get(side, side), "quantity": row.get("quantity", "—"),
                "price": row.get("price", "—"), "fee": row.get("fee", "—")})
    execution_table = _safe_html_table(fill_rows if executions is not None else None,
        list(zip(("at", "code", "side", "quantity", "price", "fee"), basis["fill_columns"])), basis["no_execution"])
    completed_rows=[{"date":row.get("date"),"code":row.get("code"),"quantity":row.get("quantity"),
                     "net_pnl":row.get("net_pnl"),"return":row.get("return")} for row in closed.get("trades",[])]
    completed_table=_safe_html_table(completed_rows,list(zip(("date","code","quantity","net_pnl","return"),basis["closed_columns"])),basis["no_closed"])
    skipped_rows = skipped if isinstance(skipped, list) else None
    skipped_columns = sorted({key for row in skipped_rows or [] if isinstance(row, dict) for key in row})
    localized_skipped=[]
    for row in skipped_rows or []:
        if not isinstance(row,dict): continue
        translated=dict(row)
        translated["side"]=basis.get(str(row.get("side","")).lower(),row.get("side","—"))
        if row.get("reason")=="opening gap exceeds prior-close cash budget": translated["reason"]=basis["gap_reason"]
        localized_skipped.append(translated)
    localized_columns=[(key,basis["skip_columns"].get(key,key)) for key in skipped_columns]
    skipped_table = (_safe_html_table(localized_skipped, localized_columns, basis["no_skipped"])
                     if skipped_rows is not None else f'<p class="muted">{html.escape(basis["no_skipped"])}</p>')
    account_path = report.get("account_path") or []
    valuation_basis = next((row.get("valuation_basis") for row in account_path if isinstance(row, dict) and row.get("valuation_basis")), None)
    if valuation_basis is None and account_path:
        valuation_basis = basis["open_sample"] if report.get("model") == "daily_bar_next_open_research_v1" else "unknown"
    fee_line = (f'{basis["fee"]}: {fee_value}' if fee_value is not None else f'{basis["fee_missing"]}: {fee_reason or "unknown"}')
    turnover_rows=report.get("daily_turnover")
    turnover_values=[]
    if isinstance(turnover_rows,list):
        turnover_values=[_finite(row.get("gross_traded_turnover")) for row in turnover_rows if isinstance(row,dict)]
    turnover=(statistics.mean(turnover_values) if turnover_values and all(value is not None for value in turnover_values)
              and len(turnover_values)==len(report.get("nav") or []) else None)
    turnover_line=f'{basis["turnover"]}: {turnover:.2%}' if turnover is not None else f'{basis["turnover"]}: —'
    dd_basis_labels={
        "zh_CN":{"explicit initial NAV through report window":"从明确的初始NAV至报告窗口","displayed NAV window":"当前显示的NAV窗口"},
        "ja_JP":{"explicit initial NAV through report window":"明示された初期NAVからレポート期間まで","displayed NAV window":"表示中のNAV期間"},
        "en_US":{"explicit initial NAV through report window":"Explicit initial NAV through report window","displayed NAV window":"Displayed NAV window"},
    }.get(language,{})
    dd_line = basis["dd"].format(days=dd_detail["calendar_days"], start=dd_detail["start"] or "—",
                                end=dd_detail["recovered_at"] or dd_detail["trough_at"] or "—",
                                basis=dd_basis_labels.get(dd_detail["basis"],dd_detail["basis"])) if dd_detail else ""
    unavailable_line = " · ".join(f"{key}: {value}" for key, value in library_unavailable.items())
    operational_lines = [fee_line, turnover_line]
    if annualization is None:
        operational_lines.append({"zh_CN": "未声明日/周/月频率；不年化滚动风险或风险比率。",
                                  "ja_JP": "日次・週次・月次の頻度が未指定のため、リスク指標を年率換算しません。",
                                  "en_US": "NAV frequency is undeclared; rolling risk and risk ratios are not annualized."}.get(language, "NAV frequency is undeclared; risk ratios are not annualized."))
    if valuation_basis:
        operational_lines.append(f'{basis["basis"]}: {valuation_basis}')
    if dd_line:
        operational_lines.append(dd_line)
    if unavailable_line:
        operational_lines.append(f'{basis["missing_stats"]}: {unavailable_line}')
    operational_html = "".join(f'<li>{html.escape(str(line))}</li>' for line in operational_lines)
    reason_details = html.escape(json.dumps(library_unavailable, ensure_ascii=False, indent=2, default=str))
    content = "\n".join(plot_fragments)
    document = f'''<!doctype html><html lang="{html.escape(language)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>html{{color-scheme:dark;scrollbar-color:#484f58 #0d1117;scrollbar-width:thin}}::-webkit-scrollbar{{width:12px;height:12px}}::-webkit-scrollbar-track{{background:#0d1117}}::-webkit-scrollbar-thumb{{background:#484f58;border:3px solid #0d1117;border-radius:8px}}::-webkit-scrollbar-thumb:hover{{background:#6e7681}}body{{margin:0;padding:24px;background:#0d1117;color:#e6edf3;font:15px system-ui,sans-serif}}h1{{margin:0 0 8px}}.muted{{color:#a7b1c2}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:20px 0}}.metric{{padding:14px;background:#161b22;border:1px solid #30363d;border-radius:8px;display:flex;flex-direction:column;gap:8px}}.metric b{{font-size:1.2rem}}.chart{{margin:14px 0;padding:6px;background:#0d1117;border:1px solid #30363d;border-radius:6px;overflow:hidden}}details{{margin:12px 0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}</style></head><body>
<h1>{title}</h1><p>{subtitle}</p><p class="muted">{metadata} · {version_line}</p><div class="metrics">{''.join(metric_cards)}</div>
<h2>{html.escape({"zh_CN":"已平仓交易统计","ja_JP":"完了取引の統計","en_US":"Closed-trade statistics"}.get(language,"Closed-trade statistics"))}</h2><div class="metrics">{''.join(trade_cards)}</div>
<section><h2>{html.escape(basis["execution"])}</h2><h3>{html.escape(basis["filled"])}</h3>{execution_table}<h3>{html.escape({"zh_CN":"已平仓仓位周期","ja_JP":"完了したポジションサイクル","en_US":"Closed position cycles"}.get(language,"Closed position cycles"))}</h3>{completed_table}<h3>{html.escape(basis["skipped"])}</h3>{skipped_table}<ul>{operational_html}</ul></section>
<div id="dashboard-plots">{content}</div><details><summary>{html.escape({"zh_CN":"运行身份","ja_JP":"実行識別子","en_US":"Run identity"}.get(language,"Run identity"))}</summary><pre>{identity_json}</pre></details>
<details><summary>{html.escape({"zh_CN":"方法、回撤持续期与缺失证据","ja_JP":"手法・ドローダウン期間・不足データ","en_US":"Methodology, drawdown duration and evidence gaps"}.get(language,"Methodology and evidence"))}</summary><pre>{assumptions_json}</pre><h3>{html.escape(basis["missing_stats"])}</h3><pre>{reason_details}</pre></details>
<script>document.documentElement.dataset.plotlyReady=String(typeof Plotly!=="undefined");document.documentElement.dataset.plotCount=String(document.querySelectorAll('.plotly-graph-div').length);</script></body></html>'''
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256((json.dumps(identity, ensure_ascii=False, sort_keys=True, default=str) + document).encode("utf-8")).hexdigest()[:16]
    base = output_dir / f"performance-dashboard-{digest}.html"
    path = base
    suffix = 1
    while path.exists():
        path = output_dir / f"performance-dashboard-{digest}-{suffix}.html"; suffix += 1
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=output_dir, delete=False, suffix=".tmp") as stream:
        temp_path = Path(stream.name)
        stream.write(document)
    temp_path.replace(path)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "plot_count": len(figures), "bytes": path.stat().st_size, "library_metrics": library_metrics,
            "closed_trades": closed, "benchmark_available": benchmark is not None,
            "jquantstats_version": dependency_versions["jquantstats"]["version"],
            "plotly_version": dependency_versions["plotly"]["version"], "input_identity": identity}


def open_dashboard(report: dict, workspace, *, rolling_window=21, language="zh_CN", benchmark_name=None,
                   research_run_directory=None, parent=None, status_callback=None):
    """Open an asynchronous local HTML report and verify Plotly DOM readiness."""
    from PySide6.QtCore import QObject, QThread, QUrl, QTimer, Signal, Slot
    from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                                   QFileDialog)
    from PySide6.QtWebEngineWidgets import QWebEngineView
    import shutil

    from .i18n import tr

    strings = {
        "zh_CN": {"title": "交互式绩效报告", "building": "正在生成本地报告…", "validating":"正在验证报告输入…", "calculating":"正在计算整体风险与对齐基准指标…", "rendering":"正在生成交互图表…", "writing":"正在写入独立离线 HTML…", "loading": "正在本地加载图表…", "ready": "图表已渲染", "plots":"张图表", "failed": "报告失败", "save": "另存为 HTML", "close": "关闭", "timeout": "图表 DOM 校验未通过"},
        "ja_JP": {"title": "インタラクティブなパフォーマンスレポート", "building": "ローカルレポートを作成中…", "validating":"レポート入力を検証中…", "calculating":"全期間リスクと整列済みベンチマーク指標を計算中…", "rendering":"インタラクティブチャートを作成中…", "writing":"オフラインHTMLを保存中…", "loading": "ローカルでチャートを読み込み中…", "ready": "チャート描画完了", "plots":"個のチャート", "failed": "レポート生成失敗", "save": "HTMLを保存", "close": "閉じる", "timeout": "チャートDOMの検証に失敗しました"},
        "en_US": {"title": "Interactive performance report", "building": "Building local report…", "validating":"Validating report inputs…", "calculating":"Calculating full-period risk and aligned benchmark metrics…", "rendering":"Rendering interactive charts…", "writing":"Writing self-contained local HTML…", "loading": "Loading charts locally…", "ready": "Charts rendered", "plots":"plots", "failed": "Report failed", "save": "Save HTML as", "close": "Close", "timeout": "Chart DOM check failed"},
    }.get(language, {})

    class BuildWorker(QObject):
        finished = Signal(object)
        failed = Signal(str)
        progress = Signal(str)
        def __init__(self):
            super().__init__(); self.snapshot = json.loads(json.dumps(report, ensure_ascii=False, default=str))
        @Slot()
        def run(self):
            try:
                result = build_dashboard_html(self.snapshot, Path(workspace) / "reports",
                                              rolling_window=rolling_window, language=language, benchmark_name=benchmark_name,
                                              research_run_directory=research_run_directory,
                                              progress_callback=self.progress.emit)
                self.finished.emit(result)
            except Exception as exc:
                import traceback
                self.failed.emit(f"{exc}\n{traceback.format_exc()}")

    class DashboardDialog(QDialog):
        def closeEvent(self,event):
            thread=getattr(self,"_dashboard_thread",None)
            if thread is not None and thread.isRunning():
                status_widget=getattr(self,"_dashboard_status",None)
                if status_widget is not None: status_widget.setText(strings["building"])
                event.ignore()
            else:
                self._dashboard_closed=True
                timer=getattr(self,"_dashboard_dom_timer",None)
                if timer is not None: timer.stop()
                event.accept()

    dialog = DashboardDialog(parent)
    dialog.setWindowTitle(strings["title"]); dialog.resize(1100, 820)
    layout = QVBoxLayout(dialog)
    status = QLabel(strings["building"]); layout.addWidget(status)
    dialog._dashboard_status=status
    view = QWebEngineView(dialog); layout.addWidget(view, 1)
    controls = QHBoxLayout(); save = QPushButton(strings["save"]); save.setEnabled(False); close = QPushButton(strings["close"])
    controls.addWidget(save); controls.addStretch(1); controls.addWidget(close); layout.addLayout(controls)
    result_holder = {"path": None, "ready": False, "polls": 0, "last_dom": None}
    dialog._dashboard_closed=False

    def save_report():
        if not result_holder["path"]: return
        destination, _ = QFileDialog.getSaveFileName(dialog, strings["save"], "performance-report.html", "HTML (*.html)")
        if destination:
            shutil.copyfile(result_holder["path"], destination)
            status.setText(strings["ready"] + f" · {destination}")

    save.clicked.connect(save_report); close.clicked.connect(dialog.close)

    def loaded(ok):
        if dialog._dashboard_closed: return
        if not ok:
            failure = {"zh_CN": "本地 HTML 加载失败", "ja_JP": "ローカルHTMLの読み込みに失敗しました",
                       "en_US": "Local HTML load failed"}.get(language, "Local HTML load failed")
            status.setText(strings["failed"] + ": " + failure)
            if status_callback: status_callback(status.text())
            return
        status.setText(strings["loading"])
        if status_callback: status_callback(status.text())
        poll_dom()

    def poll_dom():
        if dialog._dashboard_closed: return
        result_holder["polls"] += 1
        view.page().runJavaScript("JSON.stringify({ready:document.documentElement.dataset.plotlyReady,count:Number(document.documentElement.dataset.plotCount),plots:Array.from(document.querySelectorAll('.plotly-graph-div')).filter(x=>x._fullLayout&&x.querySelector('.main-svg')).length})",
            check_dom)

    def check_dom(value):
        if dialog._dashboard_closed: return
        if isinstance(value, str):
            try: value=json.loads(value)
            except (ValueError, TypeError): pass
        result_holder["last_dom"] = value
        expected=result_holder.get("plot_count", 1)
        if isinstance(value, dict) and value.get("ready") == "true" and value.get("plots", 0) >= expected:
            result_holder["ready"] = True; save.setEnabled(True)
            status.setText(_localized_ready_status(strings, value["plots"], result_holder.get("sha256", "")))
            if status_callback: status_callback(status.text())
            return
        if result_holder["polls"] < 80:
            dom_timer.start(250)
            return
        status.setText(strings["timeout"] + ": " + json.dumps(value, ensure_ascii=False, default=str))
        if status_callback: status_callback(status.text())

    view.loadFinished.connect(loaded)
    dom_timer=QTimer(dialog); dom_timer.setSingleShot(True); dom_timer.timeout.connect(poll_dom)
    dialog._dashboard_dom_timer=dom_timer
    thread = QThread(dialog); worker = BuildWorker(); worker.moveToThread(thread)
    thread.started.connect(worker.run)
    def built(result):
        result_holder.update(result); status.setText(strings["loading"])
        view.load(QUrl.fromLocalFile(result["path"]))
        thread.quit()
        if status_callback: status_callback(status.text())
    def progress(message):
        translated=strings.get(message,message)
        status.setText(translated)
        if status_callback: status_callback(translated)
    def failed(message):
        status.setText(strings["failed"] + ": " + message); thread.quit()
        if status_callback: status_callback(status.text())

    class UiBridge(QObject):
        @Slot(object)
        def built(self,result): built(result)
        @Slot(str)
        def failed(self,message): failed(message)
        @Slot(str)
        def progress(self,message): progress(message)

    bridge=UiBridge(dialog)
    worker.finished.connect(bridge.built); worker.failed.connect(bridge.failed); worker.progress.connect(bridge.progress)
    thread.finished.connect(worker.deleteLater)
    dialog._dashboard_thread = thread; dialog._dashboard_worker = worker; dialog._dashboard_bridge=bridge
    if status_callback: status_callback(strings["building"])
    thread.start(); dialog.show()
    return dialog


def _localized_ready_status(strings: dict, plot_count: int, digest: str) -> str:
    """Format the terminal renderer status using the selected locale's unit."""
    return strings["ready"] + f" · {int(plot_count)} {strings['plots']} · SHA256 {digest}"
