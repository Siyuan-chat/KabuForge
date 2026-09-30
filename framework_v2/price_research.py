"""Explicitly assumption-based daily-bar research, separate from strict PIT execution.

No available_at timestamps are invented. Input bars and recipe are snapshotted.
Only a complete common calendar with unchanged split factors is accepted.
"""
from __future__ import annotations
import math,json,hashlib
from pathlib import Path

def research_bars(rows, recipe):
    count=int(recipe["count"]); lookback=int(recipe["lookback"])
    cash=float(recipe["cash"]); initial=cash; fee=float(recipe["fee"])/100
    frequency=recipe["frequency"]
    if count<1 or lookback<2 or not math.isfinite(cash) or cash<=0 or not math.isfinite(fee) or not 0<=fee<=.05 or frequency not in {"daily","weekly","monthly"}: raise ValueError("Invalid research settings")
    by_code={}
    for row in rows:
        code=str(row["code"]); day=str(row["date"])
        from datetime import date
        date.fromisoformat(day)
        if day in by_code.setdefault(code,{}): raise ValueError("Duplicate bar: "+code+" "+day)
        for field in ("open","close"):
            value=float(row[field]) if row.get(field) is not None else float("nan")
            if not math.isfinite(value) or value<=0: raise ValueError("Missing or invalid "+field+": "+code+" "+day)
        by_code[code][day]=row
    if not by_code or count>len(by_code): raise ValueError("Not enough stocks for the selected holding count")
    dates=sorted(set.union(*(set(v) for v in by_code.values())))
    if len(dates)<lookback+2: raise ValueError("Not enough sessions for lookback and next-open execution")
    for code,items in by_code.items():
        if set(items)!=set(dates): raise ValueError("Incomplete common calendar: "+code)
        if any(r.get("adjustment_factor") is None for r in items.values()):
            raise ValueError("Adjustment-factor evidence missing: "+code)
        factors={float(r["adjustment_factor"]) for r in items.values()}
        if factors!={1.0}: raise ValueError("Split-adjusted periods require a corporate-action model: "+code)
    positions={code:0.0 for code in by_code}; previous_period=None; nav=[]; trades=[]; peak=initial
    for i,day in enumerate(dates):
        from datetime import date
        at=date.fromisoformat(day)
        period=day if frequency=="daily" else at.isocalendar()[:2] if frequency=="weekly" else day[:7]
        if i>=lookback+1 and period!=previous_period:
            # Decisions use data strictly before today's open.
            scored=sorted(by_code,key=lambda code:(-float(by_code[code][dates[i-1]]["close"])/float(by_code[code][dates[i-1-lookback]]["close"]),code))[:count]
            opens={code:float(data[day]["open"]) for code,data in by_code.items()}
            known_prices={c:float(by_code[c][dates[i-1]]["close"]) for c in by_code}
            equity=cash+sum(positions[c]*known_prices[c] for c in positions)
            # Conservative reserve covers both sides of a full rebalance.
            investable=equity/(1+2*fee)
            target={c:investable/count/known_prices[c] if c in scored else 0.0 for c in positions}
            for code in sorted(positions,key=lambda c:target[c]-positions[c]):
                delta=target[code]-positions[code]
                if abs(delta)<1e-10: continue
                notional=delta*opens[code]; cost=abs(notional)*fee
                if delta>0 and notional+cost>cash+1e-8:
                    # Actual opening gaps may invalidate the cash reservation;
                    # skip the pre-sized order, never resize with future prices.
                    continue
                cash-=notional+cost; positions[code]=target[code]
                trades.append({"date":day,"code":code,"side":"buy" if delta>0 else "sell","quantity":abs(delta),"price":opens[code],"fee":cost,"signal_date":dates[i-1]})
            if cash < -1e-6: raise ValueError("Research cash invariant failed")
            previous_period=period
        equity=cash+sum(positions[c]*float(by_code[c][day]["close"]) for c in positions)
        peak=max(peak,equity); nav.append({"at":day,"nav":equity/initial,"drawdown":equity/peak-1,"cash":cash})
    return {"model":"daily_bar_next_open_research_v1","pit_guarantee":False,"mode":"research",
            "readiness":"RESEARCH-ONLY",
            "assumptions":["prior-close signal and sizing / next-open execution; unaffordable buys skipped","current downloaded data vintage; historical visibility unverified",
                           "continuous shares; no board lots, slippage, market impact or dividends","complete common calendar; split events rejected"],
            "nav":nav,"trades":trades,"fees":sum(t["fee"] for t in trades),"recipe":recipe,
            "decisions":[],"submitted":False}

def run_price_research(manifest_path,recipe,output_dir):
    from .data_connection import load_bars
    rows=load_bars(manifest_path)
    root=Path(output_dir); root.mkdir(parents=True,exist_ok=False)
    raw=json.dumps({"bars":rows,"recipe":recipe},ensure_ascii=False,sort_keys=True,allow_nan=False).encode()
    (root/"research_inputs.json").write_bytes(raw)
    report=research_bars(rows,recipe)
    report["input_hash"]=hashlib.sha256(raw).hexdigest()
    report["workbench_configs"]={"recipe":recipe}
    (root/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    return root/"report.json"
