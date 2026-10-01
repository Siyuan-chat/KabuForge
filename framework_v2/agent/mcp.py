"""MCP JSON-RPC stdio adapter. Core services are independent of this transport."""
from __future__ import annotations
import argparse
import json
import sys
from .core import AgentCommandService, AgentResourceService, AgentError, schema, STRING
from jsonschema import Draft202012Validator
from ..config import _unique_pairs, _reject_constant


class MCPAdapter:
    def __init__(self, service, *, expose_reserved_external=False):
        self.service = service
        self.expose_reserved_external = expose_reserved_external
        self.resources = AgentResourceService(service)

    def request(self, request):
        request_id = request.get('id')
        method = request.get('method')
        if 'id' not in request: return None
        def error(code, message): return {"jsonrpc":"2.0","id":request_id,"error":{"code":code,"message":message}}
        try:
            if request.get('jsonrpc') != '2.0' or not isinstance(method,str): return error(-32600,'Invalid request')
            params = request.get('params',{})
            if method == 'initialize':
                result = {"protocolVersion":"2024-11-05","capabilities":{"tools":{},"resources":{}},"serverInfo":{"name":"kabuforge","version":"0.1.0rc1"}}
            elif method == 'ping': result = {}
            elif method == 'tools/list':
                tools = []
                for item in self.service.tool_catalog():
                    properties = dict(item['inputSchema']['properties'])
                    required = list(item['inputSchema']['required'])
                    if item['risk_class']=='R2':
                        properties.update(agent_call_id=STRING,idempotency_key=STRING)
                        required.extend(['agent_call_id','idempotency_key'])
                    tools.append({"name":item['name'],"description":item['description'],
                                  "inputSchema":schema(properties,required),
                                  "annotations":{"readOnlyHint":item['risk_class']=='R0',"destructiveHint":False,"openWorldHint":False,"idempotentHint":item['risk_class']=='R2'}})
                result = {"tools":tools}
                if self.expose_reserved_external:
                    from .external import ReservedExternalActions
                    for item in ReservedExternalActions().catalog():
                        result['tools'].append({'name':item['name'],'description':'Reserved R3 broker action; disabled until trusted human approval and broker integration are implemented.','inputSchema':item['inputSchema'],'annotations':{'readOnlyHint':False,'destructiveHint':True,'openWorldHint':True}})
            elif method == 'tools/call':
                args = dict(params.get('arguments',{})); call_id = args.pop('agent_call_id',None); key = args.pop('idempotency_key',None)
                output = self.service.call(params['name'],args,agent_call_id=call_id,idempotency_key=key)
                result = {"content":[{"type":"text","text":json.dumps(output,ensure_ascii=False,allow_nan=False)}],"isError":not output['ok']}
            elif method == 'resources/list':
                uris = ['capabilities','factor-catalog','strategy-catalog','schemas/factor','schemas/strategy','schemas/run']
                result = {"resources":[{"uri":"kabuforge://"+x,"name":x,"mimeType":"application/json"} for x in uris]}
            elif method == 'resources/templates/list':
                result = {"resourceTemplates":[{"uriTemplate":"kabuforge://runs/{run_id}","name":"Run evidence"},{"uriTemplate":"kabuforge://docs/{locale}/{document}","name":"Localized documentation"}]}
            elif method == 'resources/read':
                output = self.resources.read(params['uri'])
                result = {"contents":[{"uri":params['uri'],"mimeType":"application/json","text":json.dumps(output,ensure_ascii=False,allow_nan=False)}]}
            else: return error(-32601,'Method not found')
            return {"jsonrpc":"2.0","id":request_id,"result":result}
        except Exception:
            return error(-32602,'Invalid parameters or unavailable resource')


def main(argv=None):
    # MCP stdio uses UTF-8 regardless of the host console or locale.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='KabuForge local MCP stdio server')
    parser.add_argument('--workspace',required=True)
    parser.add_argument('--enable-paper',action='store_true')
    parser.add_argument('--expose-reserved-external',action='store_true',help='Expose disabled submit/cancel extension stubs; never enables real trading')
    parser.add_argument('--locale',choices=['en_US','zh_CN','ja_JP'],default='en_US')
    args = parser.parse_args(argv)
    adapter = MCPAdapter(AgentCommandService(args.workspace,enable_paper=args.enable_paper,locale=args.locale),expose_reserved_external=args.expose_reserved_external)
    while True:
        line = sys.stdin.readline(1024*1024+1)
        if not line: break
        if len(line) > 1024*1024:
            while line and not line.endswith('\n'): line = sys.stdin.readline(1024*1024+1)
            response = {"jsonrpc":"2.0","id":None,"error":{"code":-32600,"message":"Request too large"}}
        else:
            try:
                value = json.loads(line,object_pairs_hook=_unique_pairs,parse_constant=_reject_constant)
                response = adapter.request(value) if isinstance(value,dict) else {"jsonrpc":"2.0","id":None,"error":{"code":-32600,"message":"Invalid request"}}
            except (ValueError,TypeError):
                response = {"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":"Parse error"}}
        if response is not None:
            sys.stdout.write(json.dumps(response,ensure_ascii=False,allow_nan=False)+'\n'); sys.stdout.flush()


if __name__ == '__main__': main()
