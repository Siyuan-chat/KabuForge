"""Deterministic fictional inputs for offline software demonstrations only."""
from __future__ import annotations
import numpy as np
import pandas as pd

def datasets():
    rng = np.random.default_rng(48217)
    dates = pd.bdate_range("2022-01-03", "2024-06-28")
    codes = [str(2000+i) for i in range(20)]
    prices = []
    for i, code in enumerate(codes + ["1306", "1617"]):
        close = (700+25*i)*np.cumprod(1+rng.normal(.0003,.018,len(dates)))
        prices.extend(dict(date=d, code=code, open=c*.999, high=c*1.01, low=c*.99,
            close=c, volume=int(rng.integers(250000,2000000)), adjustment_factor=1.,
            adjustment_close=c) for d,c in zip(dates,close))
    snaps = pd.date_range("2022-01-31", "2024-06-30", freq="ME")
    result = {"prices":pd.DataFrame(prices)}
    result["universe"] = pd.DataFrame([dict(asof_date=d,code=c,in_universe=True,
        ticker=c+".T",industry="Foods") for d in snaps for c in codes])
    result["market_cap"] = pd.DataFrame([dict(asof_date=d,code=c,market_cap=10e9+i*1e8,
        shares_outstanding=8e6+i*1e5) for d in snaps for i,c in enumerate(codes)])
    rows = []
    for i,c in enumerate(codes):
        a=60e9+i*1e9; r=a*.7; n=r*(.04+(i%7)*.005)
        for d in ["2022-08-15","2023-02-15","2023-08-15","2024-02-15"]:
            rows.append(dict(disclosed_date=d,code=c,total_revenue=r,gross_profit=r*.28,
                operating_income=r*.08,ebit=r*.08,ebitda=r*.1,net_income=n,total_assets=a,
                stockholders_equity=a*(.35+(i%5)*.03),total_debt=a*.22,
                cash_and_cash_equivalents=a*.08,operating_cash_flow=n*1.2,free_cash_flow=n*.8))
    result["financial_summary"] = pd.DataFrame(rows)
    result["margin"] = pd.DataFrame([dict(date=d,code=c,
        margin_buy_balance=float(rng.integers(150000,300000)),
        margin_sell_balance=float(rng.integers(40000,120000)),
        margin_buy_change=float(rng.integers(-20000,20000)),
        margin_sell_change=float(rng.integers(-10000,10000))) for d in dates[::5] for c in codes])
    result["index_prices"] = pd.DataFrame(dict(date=dates,index_code="TOPIX",
        close=1800*np.cumprod(1+rng.normal(.0002,.01,len(dates)))))
    for frame in result.values():
        column=next(c for c in ("date","asof_date","disclosed_date") if c in frame)
        frame["available_at"]=pd.to_datetime(frame[column]).dt.tz_localize("Asia/Tokyo")+pd.Timedelta(hours=16)
    return result
