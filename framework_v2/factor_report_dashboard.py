"""Offline Plotly dashboard for preregistered factor diagnostics (not a NAV report)."""
from __future__ import annotations

from collections import Counter
from datetime import date
import hashlib
import html
import json
from pathlib import Path
import re


class FactorDashboardUnavailable(RuntimeError):
    pass


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    import math
    return number if math.isfinite(number) else None


def _labels(language):
    return {
        "zh_CN": {
            "title": "因子研究诊断", "subtitle": "RESEARCH-ONLY · 描述性横截面统计；不是策略净值、投资评级或样本外结论",
            "ic": "每日 IC 与 Rank IC", "quantile": "组合分位的未来开盘收益（等权日均；非策略收益）",
            "coverage": "特征与标签覆盖率", "turnover": "最高分位成分换手率",
            "correlation": "因子横截面 Spearman 相关性（同日同证券）", "range": "各年已观察信号日数量",
            "date": "信号日期", "correlation_axis": "相关系数", "return": "未来开盘收益",
            "coverage_axis": "覆盖率", "turnover_axis": "换手率", "sessions": "信号日数",
            "feature_coverage": "特征覆盖", "label_coverage": "标签覆盖", "composite": "组合分数",
            "low": "低分位", "high": "高分位", "observed_range": "信号日期范围",
            "observed_sessions": "观察到的信号日", "recipe": "预注册配置", "identity": "输入身份",
            "warnings": "研究边界", "empty": "有效样本不足，无法绘制", "footer": "标签为信号日后固定交易日数的下一开盘收益；标签与特征分离，组合分数仅使用特征。历史可见性未验证。",
            "web_error": "本地 WebEngine 未能载入图表文件", "dom_error": "图表 DOM 未就绪",
        },
        "ja_JP": {
            "title": "ファクター研究診断", "subtitle": "RESEARCH-ONLY · 記述的横断面統計。戦略NAV、投資評価、またはアウト・オブ・サンプル結論ではありません",
            "ic": "日次 IC と Rank IC", "quantile": "スコア分位別の将来始値リターン（日次等加重平均；戦略リターンではありません）",
            "coverage": "特徴量とラベルのカバレッジ", "turnover": "上位分位の構成銘柄回転率",
            "correlation": "ファクター横断面 Spearman 相関（同日・同一銘柄）", "range": "年別の観測シグナル日数",
            "date": "シグナル日", "correlation_axis": "相関係数", "return": "将来始値リターン",
            "coverage_axis": "カバレッジ", "turnover_axis": "回転率", "sessions": "シグナル日数",
            "feature_coverage": "特徴量カバレッジ", "label_coverage": "ラベルカバレッジ", "composite": "合成スコア",
            "low": "低位分位", "high": "高位分位", "observed_range": "シグナル日範囲",
            "observed_sessions": "観測シグナル日数", "recipe": "事前登録設定", "identity": "入力識別情報",
            "warnings": "研究上の制約", "empty": "有効サンプルが不足しており描画できません", "footer": "ラベルはシグナル日から指定営業日後の次の始値リターンです。ラベルと特徴量は分離され、合成スコアは特徴量のみを使用します。過去の可視性は未検証です。",
            "web_error": "ローカル WebEngine がチャートファイルを読み込めません", "dom_error": "チャート DOM が準備できません",
        },
        "en_US": {
            "title": "Factor research diagnostics", "subtitle": "RESEARCH-ONLY · Descriptive cross-sectional statistics; not strategy NAV, an investment rating, or an out-of-sample conclusion",
            "ic": "Daily IC and Rank IC", "quantile": "Forward open returns by score quantile (equal-weight daily means; not strategy returns)",
            "coverage": "Feature and label coverage", "turnover": "Top-quantile constituent turnover",
            "correlation": "Cross-sectional factor Spearman correlation (same date and security)", "range": "Observed signal sessions by year",
            "date": "Signal date", "correlation_axis": "Correlation", "return": "Forward open return",
            "coverage_axis": "Coverage", "turnover_axis": "Turnover", "sessions": "Signal sessions",
            "feature_coverage": "Feature coverage", "label_coverage": "Label coverage", "composite": "Composite score",
            "low": "Low quantile", "high": "High quantile", "observed_range": "Signal-date range",
            "observed_sessions": "Observed signal sessions", "recipe": "Preregistered recipe", "identity": "Input identity",
            "warnings": "Research limitations", "empty": "Insufficient valid observations to plot", "footer": "Labels are next-open returns at the configured session horizon after each signal date. Labels are separated from features; composite scores use features only. Historical availability is unverified.",
            "web_error": "The local WebEngine could not load the chart file", "dom_error": "Chart DOM did not become ready",
        },
    }.get(language, {})


def _feature_label(name, labels, language):
    if name == "composite_score":
        return labels["composite"]
    match = re.fullmatch(r"price_momentum_(\d+)", str(name))
    if not match:
        return str(name)
    window = match.group(1)
    return {"zh_CN": f"{window}日价格动量", "ja_JP": f"{window}日価格モメンタム",
            "en_US": f"{window}-session price momentum"}[language]


def _dark(figures):
    colors = ["#56B4E9", "#E69F00", "#009E73", "#CC79A7", "#F0E442", "#D55E00"]
    for figure in figures:
        figure.update_layout(template="plotly_dark", paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
            font={"color": "#E6EDF3"}, colorway=colors,
            hoverlabel={"bgcolor": "#161B22", "bordercolor": "#30363D", "font": {"color": "#E6EDF3"}},
            legend={"bgcolor": "rgba(22,27,34,0.82)", "bordercolor": "#30363D"},
            margin={"l": 70, "r": 22, "t": 74, "b": 55}, height=360)
        figure.update_xaxes(gridcolor="#30363D", zerolinecolor="#30363D", linecolor="#30363D",
                            tickfont={"color": "#A7B1C2"})
        figure.update_yaxes(gridcolor="#30363D", zerolinecolor="#30363D", linecolor="#30363D",
                            tickfont={"color": "#A7B1C2"})
    return figures


def build_factor_dashboard(report: dict, output_dir: str | Path, language: str = "zh_CN") -> dict:
    """Render six interactive, local-only charts from factor report artifacts."""
    if language not in {"zh_CN", "ja_JP", "en_US"}:
        raise ValueError("unsupported dashboard language")
    if not isinstance(report, dict) or report.get("schema") != "kabuforge.factor_research_report.v1":
        raise ValueError("factor report schema is unsupported")
    if report.get("readiness") != "RESEARCH-ONLY" or report.get("pit_guarantee") is not False:
        raise ValueError("factor report readiness contract is invalid")
    try:
        import plotly.graph_objects as go
        import plotly.io as pio
    except Exception as exc:
        raise FactorDashboardUnavailable(f"Plotly is unavailable: {type(exc).__name__}: {exc}") from exc

    labels = _labels(language)
    analysis = report.get("analysis") or {}
    factors = analysis.get("factors") or {}
    names = [name for name in factors if name != "composite_score"]
    dates = [str(value) for value in report.get("dates", [])]
    if any(not re.fullmatch(r"\d{4}-\d{2}-\d{2}", item) for item in dates):
        raise ValueError("factor signal dates must be ISO calendar dates")

    ic_fig = go.Figure()
    plotted = False
    for name in [*names, "composite_score"]:
        daily = factors.get(name, {}).get("daily") or []
        for key, suffix in (("ic", "IC"), ("rank_ic", "Rank IC")):
            by_date = {str(row["signal_date"]): _finite(row.get(key)) for row in daily
                       if row.get("signal_date")}
            if any(value is not None for value in by_date.values()):
                # Keep explicit nulls in the signal-date calendar so warm-up,
                # insufficient-cross-section, and constant-factor gaps remain visible.
                values = [by_date.get(day) for day in dates]
                ic_fig.add_trace(go.Scatter(x=dates, y=values,
                    mode="lines", name=f"{_feature_label(name, labels, language)} · {suffix}",
                    connectgaps=False, hovertemplate=f"{labels['date']} %{{x}}<br>{suffix} %{{y:.3f}}<extra></extra>"))
                plotted = True
    if not plotted:
        ic_fig.add_annotation(text=labels["empty"], x=.5, y=.5, xref="paper", yref="paper", showarrow=False)
    ic_fig.update_layout(title=labels["ic"], xaxis_title=labels["date"], yaxis_title=labels["correlation_axis"], hovermode="x unified")
    ic_fig.update_yaxes(tickformat=".2f")

    quantile_fig = go.Figure()
    composite_daily = factors.get("composite_score", {}).get("daily") or []
    q_numbers = sorted({int(item["bucket"]) for row in composite_daily
                        for item in row.get("quantile_returns", []) if item.get("bucket") is not None})
    q_count = max(q_numbers, default=0)
    for bucket in q_numbers:
        points = [(str(row["signal_date"]), _finite(item.get("mean_forward_return")))
                  for row in composite_daily for item in row.get("quantile_returns", [])
                  if int(item.get("bucket", -1)) == bucket and _finite(item.get("mean_forward_return")) is not None]
        quantile_fig.add_trace(go.Scatter(x=[point[0] for point in points], y=[point[1] for point in points],
            mode="lines", name=(labels["low"] if bucket == 1 else labels["high"] if bucket == q_count else f"Q{bucket}"),
            connectgaps=False, hovertemplate=f"{labels['date']} %{{x}}<br>{labels['return']} %{{y:.2%}}<extra></extra>"))
    if not quantile_fig.data:
        quantile_fig.add_annotation(text=labels["empty"], x=.5, y=.5, xref="paper", yref="paper", showarrow=False)
    quantile_fig.update_layout(title=labels["quantile"], xaxis_title=labels["date"], yaxis_title=labels["return"], hovermode="x unified")
    quantile_fig.update_yaxes(tickformat=".1%")

    coverage_fig = go.Figure()
    for key, title in (("feature_coverage", labels["feature_coverage"]), ("label_coverage", labels["label_coverage"])):
        points = [(str(row["signal_date"]), _finite(row.get(key))) for row in composite_daily
                  if row.get("signal_date") and _finite(row.get(key)) is not None]
        if points:
            coverage_fig.add_trace(go.Scatter(x=[point[0] for point in points], y=[point[1] for point in points],
                mode="lines", name=title, connectgaps=False,
                hovertemplate=f"{labels['date']} %{{x}}<br>{title} %{{y:.1%}}<extra></extra>"))
    if not coverage_fig.data:
        coverage_fig.add_annotation(text=labels["empty"], x=.5, y=.5, xref="paper", yref="paper", showarrow=False)
    coverage_fig.update_layout(title=labels["coverage"], xaxis_title=labels["date"], yaxis_title=labels["coverage_axis"], hovermode="x unified")
    coverage_fig.update_yaxes(tickformat=".1%", range=[0, 1])

    turnover_rows = factors.get("composite_score", {}).get("turnover") or []
    turnover_points = [(str(row["signal_date"]), _finite(row.get("turnover"))) for row in turnover_rows
                       if row.get("signal_date") and _finite(row.get("turnover")) is not None]
    turnover_fig = go.Figure()
    if turnover_points:
        turnover_fig.add_trace(go.Scatter(x=[point[0] for point in turnover_points], y=[point[1] for point in turnover_points],
            mode="lines+markers", name=labels["turnover"], connectgaps=False,
            hovertemplate=f"{labels['date']} %{{x}}<br>{labels['turnover_axis']} %{{y:.1%}}<extra></extra>"))
    else:
        turnover_fig.add_annotation(text=labels["empty"], x=.5, y=.5, xref="paper", yref="paper", showarrow=False)
    turnover_fig.update_layout(title=labels["turnover"], xaxis_title=labels["date"], yaxis_title=labels["turnover_axis"], hovermode="x unified")
    turnover_fig.update_yaxes(tickformat=".1%", range=[0, 1])

    correlation_names = [*names, "composite_score"]
    correlation_values = {(str(row.get("left")), str(row.get("right"))): _finite(row.get("mean_daily_spearman"))
                          for row in analysis.get("correlations", []) if isinstance(row, dict)}
    matrix = []
    correlation_observations = set()
    for left, right in correlation_values:
        correlation_observations.add((left, right))
        correlation_observations.add((right, left))
    for left in correlation_names:
        row_values = []
        for right in correlation_names:
            if left == right:
                # Only pairwise correlations are emitted by the research
                # service. A diagonal of 1.0 would imply valid, non-constant
                # observations that may not exist in sparse samples.
                value = None
            else:
                value = correlation_values.get((left, right), correlation_values.get((right, left)))
            row_values.append(value)
        matrix.append(row_values)
    corr_fig = go.Figure(go.Heatmap(x=[_feature_label(item, labels, language) for item in correlation_names],
        y=[_feature_label(item, labels, language) for item in correlation_names], z=matrix,
        zmin=-1, zmax=1, zmid=0, colorscale=[[0, "#E69F00"], [.5, "#161B22"], [1, "#56B4E9"]],
        colorbar={"title": labels["correlation_axis"], "tickformat": ".1f"},
        hovertemplate="%{y} × %{x}<br>ρ=%{z:.3f}<extra></extra>"))
    for index, name in enumerate(correlation_names):
        if (name, name) not in correlation_observations:
            corr_fig.add_annotation(x=index, y=index, text="—", showarrow=False,
                                    font={"color": "#A7B1C2"})
    corr_fig.update_layout(title=labels["correlation"], xaxis_title="", yaxis_title="")

    years = Counter(item[:4] for item in dates)
    year_items = sorted(years.items())
    range_fig = go.Figure(go.Bar(x=[year for year, _ in year_items], y=[count for _, count in year_items],
        name=labels["sessions"], hovertemplate=f"%{{x}}<br>{labels['sessions']} %{{y}}<extra></extra>"))
    range_fig.update_layout(title=labels["range"], xaxis_title="", yaxis_title=labels["sessions"], xaxis={"type": "category"})
    range_fig.update_yaxes(tickformat="d")

    figures = _dark([ic_fig, quantile_fig, coverage_fig, turnover_fig, corr_fig, range_fig])
    fragments = [pio.to_html(figure, full_html=False, include_plotlyjs="inline" if index == 0 else False,
                config={"scrollZoom": True, "displaylogo": False, "responsive": True})
                 for index, figure in enumerate(figures)]
    input_identity = report.get("input_identity") or {}
    selection = input_identity.get("selection") or {}
    first, last = (dates[0], dates[-1]) if dates else ("—", "—")
    recipe_text = html.escape(json.dumps(report.get("recipe"), ensure_ascii=False, sort_keys=True, indent=2))
    identity_selection = input_identity.get("selection") or {}
    identity_coverage = input_identity.get("coverage") or {}
    identity_text = html.escape(json.dumps({"manifest_sha256": input_identity.get("manifest_sha256"),
        "pinned_identity_sha256": input_identity.get("pinned_identity_sha256"),
        "recipe_sha256": report.get("recipe_sha256"),
        "codes": identity_selection.get("requested_codes", selection.get("requested_codes")),
        "source_dates": [identity_selection.get("start_date"), identity_selection.get("end_date")],
        "coverage": identity_coverage,
        "observed_signal_range": [first, last],
        "feature_rows": report.get("feature_row_count"), "evaluation_rows": report.get("evaluation_row_count"),
        "PIT": report.get("pit_guarantee"), "readiness": report.get("readiness")},
        ensure_ascii=False, sort_keys=True, indent=2))
    limitations = "<ul>" + "".join(f"<li>{html.escape(str(item))}</li>" for item in report.get("limitations", [])) + "</ul>"
    plot_fragment = "\n".join(f'<section class="chart">{fragment}</section>' for fragment in fragments)
    document = f'''<!doctype html><html lang="{language}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(labels['title'])}</title>
<style>html{{color-scheme:dark;scrollbar-color:#484f58 #0d1117;scrollbar-width:thin}}::-webkit-scrollbar{{width:12px;height:12px}}::-webkit-scrollbar-track{{background:#0d1117}}::-webkit-scrollbar-thumb{{background:#484f58;border:3px solid #0d1117;border-radius:8px}}body{{margin:0;padding:24px;background:#0d1117;color:#e6edf3;font:15px system-ui,sans-serif}}h1{{margin-bottom:6px}}.subtle{{color:#a7b1c2}}.summary{{display:flex;gap:28px;flex-wrap:wrap;background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px;margin:16px 0}}.chart{{margin:14px 0;padding:4px;background:#0d1117;border:1px solid #30363d;border-radius:6px;overflow:hidden}}details{{margin:12px 0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;color:#e6edf3}}</style></head><body>
<h1>{html.escape(labels['title'])}</h1><p class="subtle">{html.escape(labels['subtitle'])}</p><div class="summary"><span>{html.escape(labels['observed_range'])}: {html.escape(first)} — {html.escape(last)}</span><span>{html.escape(labels['observed_sessions'])}: {len(dates)}</span><span>RESEARCH-ONLY</span></div>
<p>{html.escape(labels['footer'])}</p>{plot_fragment}<details><summary>{html.escape(labels['recipe'])}</summary><pre>{recipe_text}</pre></details><details><summary>{html.escape(labels['identity'])}</summary><pre>{identity_text}</pre></details><details><summary>{html.escape(labels['warnings'])}</summary>{limitations}</details>
<script>document.documentElement.dataset.plotlyReady=String(typeof Plotly!=="undefined");document.documentElement.dataset.plotCount=String(document.querySelectorAll('.plotly-graph-div').length);</script></body></html>'''
    output = Path(output_dir).expanduser().resolve(strict=True)
    safe_language = language
    path = output / f"factor-dashboard-{safe_language}.html"
    if path.exists():
        raise FileExistsError("factor dashboard output already exists")
    path.write_text(document, encoding="utf-8", newline="")
    payload = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(payload).hexdigest(),
            "plot_count": len(figures), "bytes": len(payload), "language": language,
            "date_range": [first, last], "observed_signal_sessions": len(dates)}


__all__ = ["FactorDashboardUnavailable", "build_factor_dashboard"]
