"""Public command line, delegating decisions to shared application services."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath


def _main(argv=None):
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument('--locale',choices=['en_US','zh_CN','ja_JP'],default='en_US')
    locale = pre.parse_known_args(argv)[0].locale
    descriptions={'en_US':'KabuForge local-first Japanese equity research framework','zh_CN':'KabuForge 本地优先的日本股票研究框架','ja_JP':'KabuForge ローカル優先の日本株リサーチ基盤'}
    help_text={
        'en_US':['Inspect local capabilities','List factors','List strategies','Run a fictional offline demo','Run a local historical simulation','Run a local paper simulation','Start the stdio MCP server'],
        'zh_CN':['查看本地能力','列出因子','列出策略','运行离线合成演示','运行本地历史模拟','运行本地纸上模拟','启动 stdio MCP 服务'],
        'ja_JP':['ローカル機能を確認','ファクター一覧','戦略一覧','合成データのオフラインデモ','ローカル履歴シミュレーション','ローカルペーパーシミュレーション','stdio MCP サーバーを起動']}
    parser = argparse.ArgumentParser(description=descriptions[locale])
    parser.add_argument('--locale',choices=['en_US','zh_CN','ja_JP'],default='en_US')
    sub = parser.add_subparsers(dest='command',required=True)
    for index,name in enumerate(('doctor','factors','strategies')): sub.add_parser(name,help=help_text[locale][index])
    demo = sub.add_parser('demo',help=help_text[locale][3]); demo.add_argument('--out',required=True)
    for name in ('backtest','paper'):
        item = sub.add_parser(name,help=help_text[locale][4 if name=='backtest' else 5]); item.add_argument('run'); item.add_argument('--timeline',required=True); item.add_argument('--out',required=True)
    mcp = sub.add_parser('mcp',help=help_text[locale][6]); mcp.add_argument('--workspace',required=True); mcp.add_argument('--enable-paper',action='store_true'); mcp.add_argument('--expose-reserved-external',action='store_true')
    research = sub.add_parser('research',help={'en_US':'Run a fixed local research operation','zh_CN':'运行固定的本地研究操作','ja_JP':'固定されたローカル研究操作を実行'}[locale])
    research.add_argument('--workspace',required=True,help='Existing or new isolated local research workspace')
    research.add_argument('--enable-paper',action='store_true',help='First paper-write opt-in; paper mutation also requires --confirm-paper')
    commands = research.add_subparsers(dest='research_command',required=True)
    item=commands.add_parser('price'); item.add_argument('--manifest',required=True); item.add_argument('--recipe',required=True)
    item=commands.add_parser('factor'); item.add_argument('--manifest',required=True); item.add_argument('--recipe')
    item=commands.add_parser('strategy'); item.add_argument('--manifest',required=True); item.add_argument('--scores',required=True); item.add_argument('--score-sha',required=True); item.add_argument('--score-source',choices=['factor_feature_rows','model_predictions'],required=True); item.add_argument('--recipe')
    item=commands.add_parser('models'); item.add_argument('--manifest',required=True); item.add_argument('--factor-run-dir',required=True); item.add_argument('--model',choices=['lightgbm','catboost'],action='append',required=True)
    item=commands.add_parser('engines'); item.add_argument('--manifest',required=True); item.add_argument('--recipes',required=True,help='JSON object with one recipes array')
    item=commands.add_parser('indicator'); item.add_argument('--manifest',required=True); item.add_argument('--code',required=True); item.add_argument('--provider',choices=['talib','pandas-ta'],default='pandas-ta'); item.add_argument('--sma-period',type=int,default=20); item.add_argument('--rsi-period',type=int,default=14); item.add_argument('--atr-period',type=int,default=14)
    item=commands.add_parser('sensitivity'); item.add_argument('--run-directory',required=True); item.add_argument('--report-sha',required=True)
    item=commands.add_parser('paper-create'); item.add_argument('--confirm-paper',action='store_true',required=True); item.add_argument('--manifest',required=True); item.add_argument('--strategy-report',required=True); item.add_argument('--report-sha',required=True); item.add_argument('--call-id',required=True); item.add_argument('--idempotency-key',required=True)
    item=commands.add_parser('paper-query'); item.add_argument('--account-dir',required=True); item.add_argument('--include-events',action='store_true')
    item=commands.add_parser('paper-step'); item.add_argument('--confirm-paper',action='store_true',required=True); item.add_argument('--account-dir',required=True); item.add_argument('--cursor',type=int,required=True); item.add_argument('--call-id',required=True); item.add_argument('--idempotency-key',required=True)
    item=commands.add_parser('paper-run-all'); item.add_argument('--confirm-paper',action='store_true',required=True); item.add_argument('--account-dir',required=True); item.add_argument('--call-id',required=True); item.add_argument('--idempotency-key',required=True)
    item=commands.add_parser('broker-create'); item.add_argument('--config',required=True)
    item=commands.add_parser('broker-preview'); item.add_argument('--broker-workspace',required=True); item.add_argument('--intent',required=True); item.add_argument('--instrument',required=True); item.add_argument('--now',required=True)
    item=commands.add_parser('broker-readonly'); item.add_argument('--broker-workspace',required=True); item.add_argument('--confirm-read-only',action='store_true',required=True); item.add_argument('--timeout',type=float,default=2.0)
    args = parser.parse_args(argv)
    if args.command=='doctor':
        from framework_v2.version import get_version
        print(json.dumps({'version':get_version(),'application_services':True,'mcp_stdio':True,'paper_requires_opt_in':True,'external_actions_enabled':False,'reserved_external_hooks':['request_order_approval','submit_order','cancel_order'],'distribution':'PUBLIC','strategy_readiness':'NOT_EVALUATED'}))
        return
    if args.command=='factors':
        from framework_v2.application import ApplicationService
        print(json.dumps(ApplicationService().registry.catalog()))
        return
    if args.command=='demo':
        from framework_v2.cli import main as legacy
        return legacy([args.command]+(['--out',args.out] if args.command=='demo' else []))
    if args.command=='strategies':
        from framework_v2.application import ApplicationService
        from framework_v2.local_io import plain
        print(json.dumps(plain(ApplicationService().strategy_registry.catalog())))
    elif args.command in {'backtest','paper'}:
        from framework_v2.cli import main as legacy
        from framework_v2.application import ApplicationService
        resolved = ApplicationService().validate(args.run)
        if resolved.run['mode'] != args.command: parser.error('run mode must match command')
        return legacy(['history',args.run,'--timeline',args.timeline,'--out',args.out])
    elif args.command=='research':
        return _research(args)
    elif args.command=='mcp':
        from framework_v2.agent.mcp import main as serve
        options = ['--workspace',args.workspace,'--locale',args.locale]
        if args.enable_paper: options.append('--enable-paper')
        if args.expose_reserved_external: options.append('--expose-reserved-external')
        return serve(options)


def _strict_json(path):
    def unique_pairs(pairs):
        value={}
        for key,item in pairs:
            if key in value: raise ValueError('duplicate JSON key')
            value[key]=item
        return value
    raw=path.read_bytes()
    if len(raw)>64*1024*1024: raise ValueError('selected JSON file is too large')
    value=json.loads(raw.decode('utf-8'),object_pairs_hook=unique_pairs,
                     parse_constant=lambda _: (_ for _ in ()).throw(ValueError('non-finite JSON value')))
    if not isinstance(value,(dict,list)): raise ValueError('selected JSON root must be an object or array')
    from framework_v2.config import _check_secrets
    _check_secrets(value,path)
    return value


def _research_command_names():
    return ("price", "factor", "strategy", "models", "engines", "indicator", "sensitivity",
            "paper-create", "paper-query", "paper-step", "paper-run-all", "broker-create",
            "broker-preview", "broker-readonly")


def _selected_path(workspace, value):
    root=Path(workspace).expanduser().resolve()
    raw=str(value)
    windows=PureWindowsPath(raw)
    posix=PurePosixPath(raw.replace("\\", "/"))
    if not raw or any(part == ".." for part in (*windows.parts, *posix.parts)):
        raise ValueError('selected inputs must be explicit files/directories inside the research workspace')
    path=Path(raw).expanduser()
    if windows.drive and not path.is_absolute():
        raise ValueError('selected inputs must use a path native to this platform')
    root_lexical=Path(os.path.abspath(root))
    if path.is_absolute():
        # Reject external drives and UNC paths lexically before resolve/stat can
        # touch them (Windows may otherwise probe a network share).
        path=Path(os.path.abspath(path))
        if not path.is_relative_to(root_lexical) or path == root_lexical:
            raise ValueError('selected inputs must be explicit files/directories inside the research workspace')
    else:
        # Accept either separator in CLI arguments so traversal policy does not
        # change when a command moves between Windows and POSIX runners.
        path=root / raw.replace("\\", "/")
    resolved=path.resolve(strict=False)
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError('selected inputs must be explicit files/directories inside the research workspace')
    try:
        resolved=resolved.resolve(strict=True)
    except FileNotFoundError:
        raise ValueError('selected inputs must be existing files/directories inside the research workspace') from None
    if not path.is_file() and not path.is_dir():
        raise ValueError('selected inputs must be explicit files/directories inside the research workspace')
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError('selected inputs must be explicit files/directories inside the research workspace')
    return resolved


def _research(args):
    from framework_v2.research_application import ResearchApplicationService
    from framework_v2.local_io import plain
    from framework_v2.broker_research import BrokerResearchConfig
    from framework_v2.execution import Instrument, OrderIntent
    from dataclasses import fields
    from decimal import Decimal

    workspace=Path(args.workspace).expanduser().resolve()
    workspace.mkdir(parents=True,exist_ok=True)
    if not workspace.is_dir(): raise ValueError('research workspace must be a directory')
    service=ResearchApplicationService(workspace,enable_paper=args.enable_paper)
    cmd=args.research_command
    def source(name): return _selected_path(workspace,getattr(args,name))
    def payload(name): return _strict_json(source(name))
    if cmd=='price': result=service.run_price_research(source('manifest'),payload('recipe'))
    elif cmd=='factor': result=service.run_factor_diagnostics_task(source('manifest'),payload('recipe') if args.recipe else None)
    elif cmd=='strategy': result=service.run_factor_strategy(source('manifest'),source('scores'),score_source=args.score_source,expected_artifact_sha256=args.score_sha,recipe=payload('recipe') if args.recipe else None)
    elif cmd=='models': result=service.run_model_training(source('manifest'),source('factor_run_dir'),args.model)
    elif cmd=='engines':
        recipes=payload('recipes')
        if set(recipes)!={'recipes'} or not isinstance(recipes['recipes'],list): raise ValueError('engine input must contain only a recipes array')
        result=service.run_engine_comparison(source('manifest'),recipes['recipes'])
    elif cmd=='indicator': result=service.run_indicator_research(source('manifest'),args.code,sma_period=args.sma_period,rsi_period=args.rsi_period,atr_period=args.atr_period,provider=args.provider)
    elif cmd=='sensitivity': result=service.run_price_sensitivity(source('run_directory'),expected_report_sha256=args.report_sha)
    elif cmd=='paper-create':
        if not args.enable_paper or not args.confirm_paper: raise PermissionError('paper writes require --enable-paper and --confirm-paper')
        result=service.create_historical_paper(source('manifest'),source('strategy_report'),args.report_sha,enable_paper=True,call_id=args.call_id,idempotency_key=args.idempotency_key)
    elif cmd=='paper-query': result=service.query_historical_paper(source('account_dir'),include_events=args.include_events)
    elif cmd=='paper-step':
        if not args.enable_paper or not args.confirm_paper: raise PermissionError('paper writes require --enable-paper and --confirm-paper')
        result=service.advance_historical_paper(source('account_dir'),expected_cursor=args.cursor,enable_paper=True,call_id=args.call_id,idempotency_key=args.idempotency_key)
    elif cmd=='paper-run-all':
        if not args.enable_paper or not args.confirm_paper: raise PermissionError('paper writes require --enable-paper and --confirm-paper')
        result=service.run_historical_paper_all(source('account_dir'),enable_paper=True,call_id=args.call_id,idempotency_key=args.idempotency_key)
    elif cmd=='broker-create':
        config=payload('config')
        if not isinstance(config,dict) or set(config)!={'environment','endpoint','account_id','account_type','exchange','credential_ref'}: raise ValueError('broker config has unknown or missing fields')
        result=service.create_broker_workspace(BrokerResearchConfig(**config))
    elif cmd=='broker-preview':
        intent=payload('intent'); instrument=payload('instrument')
        if not isinstance(intent,dict) or set(intent)!={field.name for field in fields(OrderIntent)}: raise ValueError('intent has unknown or missing fields')
        if not isinstance(instrument,dict) or set(instrument)-{'code','lot_size','tick_size','expires_at'} or not {'code','lot_size','tick_size'}<=set(instrument): raise ValueError('instrument has unknown or missing fields')
        for name in ('created_at','valid_until'): intent[name]=datetime.fromisoformat(intent[name])
        for name in ('limit_price','estimated_price','estimated_fee'): intent[name]=None if intent[name] is None else Decimal(str(intent[name]))
        if instrument.get('expires_at') is not None: instrument['expires_at']=datetime.fromisoformat(instrument['expires_at'])
        instrument['tick_size']=Decimal(str(instrument['tick_size']))
        result=service.preview_broker_order(source('broker_workspace'),OrderIntent(**intent),Instrument(**instrument),now=datetime.fromisoformat(args.now))
    elif cmd=='broker-readonly':
        if not args.confirm_read_only: raise PermissionError('broker read-only GET requires explicit --confirm-read-only')
        result=service.check_broker_read_only(source('broker_workspace'),timeout=args.timeout)
    else: raise ValueError('unknown fixed research operation')
    print(json.dumps(plain(result),ensure_ascii=False,allow_nan=False,default=str))


def main(argv=None):
    try: return _main(argv)
    except Exception as exc:
        import sys
        values = list(sys.argv[1:] if argv is None else argv)
        locale = values[values.index('--locale')+1] if '--locale' in values and values.index('--locale')+1<len(values) else 'en_US'
        messages={'en_US':'Local command failed; review inputs and retained evidence.','zh_CN':'本地命令未完成，请核对输入与留存证据。','ja_JP':'ローカル操作に失敗しました。入力と保存済み証拠を確認してください。'}
        failure={'error_code':'KF_CLI_FAILED','message':messages.get(locale,messages['en_US'])}
        stage=getattr(exc,'stage',None); task_dir=getattr(exc,'task_dir',None)
        if isinstance(stage,str) and stage: failure['stage']=stage[:100]
        if task_dir is not None: failure['task_dir']=str(task_dir)
        print(json.dumps(failure,ensure_ascii=False),file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__': main()
