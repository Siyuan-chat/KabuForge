"""Local v2 command line. No implicit downloads, account login or submission."""
from __future__ import annotations
import argparse
from datetime import datetime
import json
from pathlib import Path
from .application import ApplicationService
from .demo import create_demo
from .local_io import (account_from_file, context_from_file, execution_from_file,
                       research_marks, result_document, write_new)

def plan_file(path, execution, decision_at, now):
    service=ApplicationService(); path=Path(path).resolve()
    resolved=service.validate(path)
    context=context_from_file(path.parent/resolved.run["data_snapshot"],
        expected_hash=resolved.data_snapshot_hash,decision_at=decision_at)
    account=account_from_file(path.parent/resolved.run["account_ref"],expected_hash=resolved.account_hash)
    quotes,instruments,execution_hash=execution_from_file(execution)
    result=service.plan(resolved,context=context,account=account,research_marks=research_marks(context),
        quotes=quotes,instruments=instruments,now=datetime.fromisoformat(now))
    document=result_document(result)
    document["evidence"]={"file_hashes":dict(resolved.file_hashes),"execution_snapshot_hash":execution_hash,
        "mode":resolved.run["mode"],"status":"PLANNED_ONLY","submitted":False}
    return document

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    demo=sub.add_parser("demo",help="create and run fictional offline planning examples")
    demo.add_argument("--out",required=True,type=Path)
    val=sub.add_parser("validate",help="validate config graph without creating outputs")
    val.add_argument("run",type=Path)
    plan=sub.add_parser("plan",help="produce reviewable intents; does not execute them")
    plan.add_argument("run",type=Path); plan.add_argument("--execution",required=True,type=Path)
    plan.add_argument("--decision-at",required=True); plan.add_argument("--now",required=True)
    plan.add_argument("--out",required=True,type=Path)
    sim=sub.add_parser("simulate",help="execute one decision against a fictional local broker")
    sim.add_argument("run",type=Path); sim.add_argument("--execution",required=True,type=Path)
    sim.add_argument("--decision-at",required=True); sim.add_argument("--now",required=True)
    sim.add_argument("--journal",required=True,type=Path); sim.add_argument("--out",required=True,type=Path)
    sub.add_parser("factors",help="list installed implementation identities")
    sub.add_parser("doctor",help="report actual local capability level")
    convert=sub.add_parser("convert-factor",help="explicitly convert a legacy factor parameter JSON, retaining original bytes")
    convert.add_argument("source",type=Path); convert.add_argument("--out",required=True,type=Path)
    convert.add_argument("--name",required=True); convert.add_argument("--id",required=True)
    convert.add_argument("--lookback",required=True,type=int)
    history=sub.add_parser("history",help="simulate an explicit local execution timeline")
    history.add_argument("run",type=Path); history.add_argument("--timeline",required=True,type=Path)
    history.add_argument("--out",required=True,type=Path)
    args=parser.parse_args(argv)
    if args.command=="demo":
        root=create_demo(args.out)
        intents=[]
        for mode in ("backtest","paper","fake"):
            document=plan_file(root/(mode+".json"),root/"execution.json","2024-05-01T09:00:00+09:00","2024-05-01T09:00:00+09:00")
            write_new(root/(mode+"_plan.json"),document)
            intents.append(document["plan"]["intents"])
        if not intents[0] or not intents[0]==intents[1]==intents[2]:
            raise AssertionError("mode parity failed")
        print(json.dumps({"output":str(root),"intents":len(intents[0]),"mode_intent_parity":True,"submitted":False}))
    elif args.command=="validate":
        result=ApplicationService().validate(args.run)
        print(json.dumps({"valid":True,"strategy_hash":result.strategy_hash,"files":len(result.file_hashes)}))
    elif args.command=="plan":
        write_new(args.out,plan_file(args.run,args.execution,args.decision_at,args.now))
        print(json.dumps({"output":str(args.out.resolve()),"submitted":False}))
    elif args.command=="factors":
        print(json.dumps(ApplicationService().builtins.versions,indent=2))
    elif args.command=="simulate":
        from .runner import simulate_once
        # Fail before execution when the requested report already exists.
        if args.out.exists(): raise FileExistsError(args.out)
        document=simulate_once(args.run,args.execution,decision_at=args.decision_at,now=args.now,store_path=args.journal)
        write_new(args.out,document)
        print(json.dumps({"output":str(args.out.resolve()),"external_submission":False}))
    elif args.command=="doctor":
        print(json.dumps({"configuration":"available","public_factors":"synthetic_PIT_tested",
            "planning":"available","live_broker":"not_connected_or_tested",
            "excel_bridge":"not_installed_or_tested","automatic_submission":False},indent=2))
    elif args.command=="convert-factor":
        from .conversion import convert_factor
        output=convert_factor(args.source,args.out,name=args.name,factor_id=args.id,lookback=args.lookback)
        print(json.dumps({"output":str(output.resolve()),"original_preserved":True}))
    elif args.command=="history":
        from .history import run_history
        result=run_history(args.run,args.timeline,output_dir=args.out)
        print(json.dumps({"output":str(args.out.resolve()),"decisions":len(result["decisions"]),"nav_rows":len(result["nav"]),"external_submission":False}))

if __name__=="__main__": main()
