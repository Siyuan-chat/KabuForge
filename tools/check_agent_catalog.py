"""Ensure the reviewed tool/risk/schema surface has not silently changed."""
from pathlib import Path
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from framework_v2.agent.core import TOOLS
from framework_v2.agent.external import EXTERNAL_TOOLS


def catalog():
    return {"tools":{name:{"risk_class":"R"+str(risk),"inputSchema":spec} for name,(risk,spec) in sorted(TOOLS.items())},
            "reserved_external_tools":EXTERNAL_TOOLS}


if __name__=='__main__':
    expected=json.loads((Path(__file__).parents[1]/'framework_v2/schemas/agent_catalog.json').read_text())
    if catalog()!=expected: raise SystemExit('Agent tool contract changed; explicitly review and update snapshot')
    print('Agent catalog matches reviewed contract')
