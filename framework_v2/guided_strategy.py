"""Bounded local sentence parsing and isolated guided demo creation."""
from __future__ import annotations
import re
from pathlib import Path
import json
from .demo import create_demo

def parse_sentence(text):
    text=text.strip().lower().rstrip("。.!！")
    patterns=[
        (r"(每日|每周|每月)\s*(?:选|选择)?\s*(\d+)\s*只(?:股票)?\s*[,，、]?\s*等权",{"每日":"daily","每周":"weekly","每月":"monthly"},False),
        (r"(毎日|毎週|毎月)\s*(\d+)\s*銘柄(?:を)?\s*[,，、]?\s*均等配分",{"毎日":"daily","毎週":"weekly","毎月":"monthly"},False),
        (r"(?:select\s+)?(\d+)\s+stocks?\s+(daily|weekly|monthly)\s*,?\s*equal\s+weight",{"daily":"daily","weekly":"weekly","monthly":"monthly"},True),
    ]
    for pattern,frequencies,reverse in patterns:
        match=re.fullmatch(pattern,text)
        if match:
            count=int(match[1 if reverse else 2]); frequency=frequencies[match[2 if reverse else 1]]
            if not 1<=count<=100: raise ValueError("count_out_of_range")
            return {"count":count,"frequency":frequency,"weighting":"equal_weight"}
    raise ValueError("unsupported_sentence")

def create_guided_demo(directory, settings):
    count=int(settings["count"])
    if not 1<=count<=5: raise ValueError("Synthetic demo supports 1–5 holdings")
    if settings["frequency"] not in {"daily","weekly","monthly"}: raise ValueError("frequency")
    quality=float(settings["quality"])/100
    cash=float(settings["cash"]); fee=float(settings["fee"])/100
    if not 0<=quality<=1 or cash<=0 or not 0<=fee<=.05: raise ValueError("invalid settings")
    root=create_demo(directory)
    def read(name): return json.loads((root/name).read_text(encoding="utf-8"))
    def write(name,obj): (root/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
    strategy=read("strategy.json"); strategy["metadata"]={"display_name":settings["name"],"source":"synthetic"}
    strategy["scoring"]["formula"]=f"{quality} * quality + {1-quality} * dual_ma"
    strategy["portfolio"]["parameters"]["top_n"]=count
    strategy["risk"]["max_position_weight"]=max(.2,1/count)
    strategy["rebalance"]={"frequency":settings["frequency"]}; write("strategy.json",strategy)
    account=read("account.json"); account.update(equity=str(cash),available_cash=str(cash)); write("account.json",account)
    for mode in ("backtest","paper","fake"):
        run=read(mode+".json"); run["fees"]["commission_rate"]=fee; write(mode+".json",run)
    return root
