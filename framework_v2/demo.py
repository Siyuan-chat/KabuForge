"""Materialize an isolated offline demonstration, never production state."""
from pathlib import Path
from .synthetic import datasets
from .legacy_provider import BuiltinFactors, REQUIRED_DATASETS
from .local_io import write_new, plain

def create_demo(path):
    root=Path(path).resolve()
    root.mkdir(parents=True,exist_ok=False)
    frames=datasets(); builtins=BuiltinFactors()
    write_new(root/"snapshot.json",{"format":"snapshot.inline.v1","datasets":frames})
    references=[]
    for name in ("quality","dual_ma"):
        implementation=("public.momentum_12_1" if name == "residual_momentum" else "public."+name)
        filename=name+".json"; references.append(filename)
        write_new(root/filename,{"schema_version":"1.0","id":name,"kind":"factor","version":"1",
            "implementation":{"id":implementation,"version":builtins.versions[implementation],"parameters":{}},
            "lookback":800,"data_requirements":[{"dataset":d,"fields":list(frames[d].columns)} for d in REQUIRED_DATASETS[name]],
            "output":{"name":name,"description":"Fictional offline demonstration"}})
    write_new(root/"strategy.json",{"schema_version":"1.0","id":"demo","kind":"strategy","version":"1",
        "universe":{"snapshot":"universe"},"factors":references,"scoring":{"formula":"quality + dual_ma"},
        "portfolio":{"construction":"equal_weight","parameters":{"top_n":5,"long_gross":0.9,"preprocess":"zscore","missing_policy":"reject"}},
        "risk":{"max_position_weight":0.2,"max_gross_exposure":1,"turnover_budget":1,"allow_short":False},
        "rebalance":{"frequency":"monthly"}})
    write_new(root/"account.json",{"account_id":"synthetic-only","revision":"0","equity":"2000000",
        "available_cash":"2000000","positions":[]})
    for mode in ("backtest","paper","fake"):
        write_new(root/(mode+".json"),{"schema_version":"1.0","id":"demo_"+mode,"kind":"run","version":"1",
            "strategy":"strategy.json","data_snapshot":"snapshot.json","account_ref":"account.json",
            "clock":{"start":"2024-05-01","end":"2024-05-31","timezone":"Asia/Tokyo"},"mode":mode,
            "fees":{"commission_rate":0.001,"minimum_fee":0},"output_dir":"results_"+mode})
    quotes=[]; instruments=[]
    latest=frames["prices"].loc[frames["prices"].date.eq("2024-04-30")]
    for row in latest.itertuples():
        quotes.append({"code":row.code,"bid":str(row.close*.999),"ask":str(row.close*1.001),"asof":"2024-05-01T09:00:00+09:00"})
        instruments.append({"code":row.code,"lot_size":100,"tick_size":"1"})
    write_new(root/"execution.json",{"quotes":quotes,"instruments":instruments})
    sessions=[]
    for day in ("2024-05-01","2024-05-15","2024-05-31"):
        import pandas as pd
        known=frames["prices"].loc[frames["prices"].date<pd.Timestamp(day)].sort_values("date").groupby("code").tail(1)
        stamp=day+"T09:00:00+09:00"
        session_quotes=[{"code":row.code,"bid":str(row.close*.999),"ask":str(row.close*1.001),"asof":stamp} for row in known.itertuples()]
        sessions.append({"decision_at":stamp,"now":stamp,"quotes":session_quotes,"instruments":instruments})
    write_new(root/"timeline.json",{"format":"execution.timeline.v1","sessions":sessions})
    return root
