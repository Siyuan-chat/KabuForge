"""Real process protocol smoke test: stdout must remain JSON-RPC only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from framework_v2.version import get_version


class MCPStdioTests(unittest.TestCase):
    def test_stdio_initialization_tools_and_reserved_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'test','version':'1'}}},
                      {'jsonrpc':'2.0','method':'notifications/initialized'},
                      {'jsonrpc':'2.0','id':2,'method':'tools/list'},
                      {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'submit_order','arguments':{}}},
                      {'jsonrpc':'2.0','id':4,'method':'resources/read','params':{'uri':'kabuforge://docs/zh_CN/AGENT_API'}}]
            process=subprocess.run([sys.executable,'-B','-m','framework_v2.agent.mcp','--workspace',temp,'--expose-reserved-external'],
                input=''.join(json.dumps(x)+'\n' for x in requests),text=True,capture_output=True,encoding='utf-8',timeout=60,
                env={**os.environ,'PYTHONIOENCODING':'cp1252'})
            self.assertEqual(process.returncode,0,process.stderr)
            responses=[json.loads(line) for line in process.stdout.splitlines()]
            self.assertEqual(len(responses),4)
            self.assertEqual(responses[0]['result']['serverInfo']['version'], get_version())
            self.assertTrue(responses[2]['result']['isError'])
            self.assertIn('contents',responses[3]['result'])
