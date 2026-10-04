"""Public command line, delegating decisions to shared application services."""
import argparse
import json
from pathlib import Path


def _main(argv=None):
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument('--locale',choices=['en_US','zh_CN','ja_JP'],default='en_US')
    locale = pre.parse_known_args(argv)[0].locale
    descriptions={'en_US':'KabuForge local Japanese equity research framework','zh_CN':'KabuForge 本地日本股票研究框架','ja_JP':'KabuForge ローカル日本株リサーチ基盤'}
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
    args = parser.parse_args(argv)
    from framework_v2.cli import main as legacy
    if args.command=='doctor':
        print(json.dumps({'version':'0.1.1','application_services':True,'mcp_stdio':True,'paper_requires_opt_in':True,'external_actions_enabled':False,'reserved_external_hooks':['request_order_approval','submit_order','cancel_order'],'distribution':'PUBLIC','strategy_readiness':'NOT_EVALUATED'}))
        return
    if args.command=='factors':
        from framework_v2.application import ApplicationService
        print(json.dumps(ApplicationService().registry.catalog()))
        return
    if args.command=='demo':
        return legacy([args.command]+(['--out',args.out] if args.command=='demo' else []))
    if args.command=='strategies':
        from framework_v2.application import ApplicationService
        from framework_v2.local_io import plain
        print(json.dumps(plain(ApplicationService().strategy_registry.catalog())))
    elif args.command in {'backtest','paper'}:
        from framework_v2.application import ApplicationService
        resolved = ApplicationService().validate(args.run)
        if resolved.run['mode'] != args.command: parser.error('run mode must match command')
        return legacy(['history',args.run,'--timeline',args.timeline,'--out',args.out])
    elif args.command=='mcp':
        from framework_v2.agent.mcp import main as serve
        options = ['--workspace',args.workspace,'--locale',args.locale]
        if args.enable_paper: options.append('--enable-paper')
        if args.expose_reserved_external: options.append('--expose-reserved-external')
        return serve(options)


def main(argv=None):
    try: return _main(argv)
    except Exception:
        import sys
        values = list(sys.argv[1:] if argv is None else argv)
        locale = values[values.index('--locale')+1] if '--locale' in values and values.index('--locale')+1<len(values) else 'en_US'
        messages={'en_US':'Local command failed; review inputs and retained evidence.','zh_CN':'本地命令未完成，请核对输入与留存证据。','ja_JP':'ローカル操作に失敗しました。入力と保存済み証拠を確認してください。'}
        print(json.dumps({'error_code':'KF_CLI_FAILED','message':messages.get(locale,messages['en_US'])},ensure_ascii=False),file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__': main()
