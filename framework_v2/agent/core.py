"""Schema validated, workspace bounded application facade with durable receipts."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path, PureWindowsPath
import hashlib
import json
import sqlite3
import threading
import uuid
import os
from contextlib import closing
from jsonschema import Draft202012Validator
from ..application import ApplicationService
from ..config import _read_json_snapshot, _check_secrets, load_config
from ..local_io import plain, write_new


def now(): return datetime.now(timezone.utc).isoformat()
def digest(value): return hashlib.sha256(json.dumps(plain(value),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


class _Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try: return super().__exit__(*args)
        finally: self.close()


class AgentCapability(IntEnum):
    R0 = 0
    R1 = 1
    R2 = 2
    R3 = 3


class AgentError(ValueError):
    def __init__(self, code, message="Agent request rejected"):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class AgentCallRecord:
    agent_call_id: str
    idempotency_key: str | None
    input_hash: str
    result_hash: str | None
    run_id: str | None
    timestamp: str
    tool: str
    state: str


STRING = {"type":"string", "minLength":1, "maxLength":256}
PATH = {"type":"string", "minLength":1, "maxLength":512}


def schema(properties=None, required=()):
    return {"type":"object", "properties":properties or {}, "required":list(required), "additionalProperties":False}


# Risk classes are authoritative; external action tools are deliberately absent.
TOOLS = {
    "get_capabilities":(0,schema()), "list_factors":(0,schema()),
    "describe_factor":(0,schema({"implementation_id":STRING,"implementation_version":STRING},["implementation_id","implementation_version"])),
    "list_strategies":(0,schema()), "describe_strategy":(0,schema({"implementation_id":STRING,"implementation_version":STRING},["implementation_id","implementation_version"])),
    "inspect_snapshot":(0,schema({"path":PATH},["path"])),
    **{name:(0,schema({"run_id":STRING},["run_id"])) for name in ("inspect_run","get_run_status","get_run_report","list_orders","list_fills","get_account_snapshot")},
    "inspect_broker_capabilities":(0,schema()),
    "validate_config":(1,schema({"path":PATH},["path"])),
    "validate_factor":(1,schema({"path":PATH},["path"])),
    "analyze_factor":(1,schema({"run_id":STRING,"factor_id":STRING,"quantiles":{"type":"integer","minimum":2,"maximum":20}},["run_id","factor_id"])),
    "plan_strategy":(1,schema({"path":PATH,"execution":PATH,"decision_at":STRING,"now":STRING},["path","execution","decision_at","now"])),
    "run_demo":(1,schema()),
    "run_backtest":(1,schema({"path":PATH,"timeline":PATH},["path","timeline"])),
    "start_backtest":(1,schema({"path":PATH,"timeline":PATH},["path","timeline"])),
    **{name:(0,schema({"job_id":STRING},["job_id"])) for name in ("get_job_status","get_job_result")},
    "cancel_job":(1,schema({"job_id":STRING},["job_id"])),
    "compare_runs":(1,schema({"left":STRING,"right":STRING},["left","right"])),
    **{name:(1,schema({"path":PATH,"decision_at":STRING},["path","decision_at"])) for name in ("check_point_in_time","check_lookahead")},
    "create_workspace":(2,schema({"name":STRING},["name"])),
    "save_strategy_draft":(2,schema({"name":STRING,"config":{"type":"object"}},["name","config"])),
    "start_paper_simulation":(2,schema({"path":PATH,"timeline":PATH},["path","timeline"])),
    "stop_paper_simulation":(2,schema({"job_id":STRING},["job_id"])),
    "reconcile_local_state":(2,schema({"run_id":STRING},["run_id"])),
}

MESSAGES = {
    "en_US":{"KF_AGENT_REJECTED":"Request rejected; inspect the validated input and capability boundary.","KF_AGENT_PATH":"Path must remain inside the configured workspace.","KF_AGENT_IDEMPOTENCY":"Idempotency key conflicts or previous completion is uncertain.","KF_AGENT_DISABLED":"This capability is disabled."},
    "zh_CN":{"KF_AGENT_REJECTED":"请求未通过，请核对输入格式与能力边界。","KF_AGENT_PATH":"路径必须位于指定工作区之内。","KF_AGENT_IDEMPOTENCY":"幂等键冲突，或此前调用完成状态不明。","KF_AGENT_DISABLED":"此项能力尚未启用。"},
    "ja_JP":{"KF_AGENT_REJECTED":"入力形式と機能の境界を確認してください。","KF_AGENT_PATH":"パスは指定されたワークスペース内に限られます。","KF_AGENT_IDEMPOTENCY":"冪等キーが競合しているか、前回の完了状態が不明です。","KF_AGENT_DISABLED":"この機能は無効です。"},
}


class AgentCommandService:
    def __init__(self, workspace, *, enable_paper=False, locale="en_US", application=None):
        if locale not in MESSAGES: raise ValueError("unsupported locale")
        self.root = Path(workspace).resolve()
        self.root.mkdir(parents=True,exist_ok=True)
        self.application = application or ApplicationService()
        self.enable_paper = enable_paper
        self.locale = locale
        self.lock = threading.RLock()
        self.jobs = {}
        self.cancellations = {}
        self.db_path = self.root / "agent_audit.sqlite"
        if self.db_path.is_symlink(): raise AgentError("KF_AGENT_PATH")
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS calls (call_id TEXT PRIMARY KEY, idem TEXT UNIQUE, input_hash TEXT, result_hash TEXT, run_id TEXT, timestamp TEXT, tool TEXT, state TEXT, result TEXT)")
        self.job_dir = self._path("agent_jobs")
        self.job_dir.mkdir(exist_ok=True)
        for file in self.job_dir.glob('*.json'):
            job = self._json(file)
            if job.get('state') in {'QUEUED','RUNNING'} and not self._owner_alive(job):
                job.update(state='FAILED',finished_at=now(),error_code='KF_JOB_INTERRUPTED')
                self._persist_job(job)
            self.jobs[job['job_id']] = job

    def _db(self): return sqlite3.connect(self.db_path,timeout=30,factory=_Connection)

    @staticmethod
    def _owner_alive(job):
        pid = job.get('owner_pid')
        if type(pid) is not int or pid <= 0: return False
        if pid == os.getpid():
            return any(thread.name=='kabuforge-'+job['job_id'] and thread.is_alive() for thread in threading.enumerate())
        if os.name=='nt':
            import ctypes
            kernel = ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            handle = kernel.OpenProcess(0x1000,False,pid)
            if not handle: return False
            try:
                status = ctypes.c_ulong()
                return bool(kernel.GetExitCodeProcess(ctypes.c_void_p(handle),ctypes.byref(status))) and status.value==259
            finally: kernel.CloseHandle(ctypes.c_void_p(handle))
        try: os.kill(pid,0); return True
        except OSError: return False

    def _path(self, value):
        if not isinstance(value,str) or ':' in value or Path(value).is_absolute() or PureWindowsPath(value).is_absolute():
            raise AgentError("KF_AGENT_PATH")
        target = (self.root/value).resolve()
        if not target.is_relative_to(self.root) or target == self.root:
            raise AgentError("KF_AGENT_PATH")
        # Do not allow agent reads of credential-like locations or its own audit DB.
        if any(part.lower() in {'.git','.aws','.codex','secrets','credentials'} for part in target.relative_to(self.root).parts):
            raise AgentError("KF_AGENT_PATH")
        return target

    def _json(self, file):
        relative = str(Path(file).resolve().relative_to(self.root))
        target = self._path(relative)
        if target.suffix != '.json' or target.stat().st_size > 64*1024*1024: raise AgentError("KF_AGENT_REJECTED")
        return _read_json_snapshot(target)[0]

    def _graph(self, value):
        """Check every dependency before application code opens the graph."""
        visited = set()
        def visit(file):
            file = self._path(str(file.relative_to(self.root)))
            if file in visited: return
            visited.add(file); doc = self._json(file)
            refs = []
            if doc.get('kind') == 'run': refs.extend(doc.get(k) for k in ('strategy','data_snapshot','account_ref'))
            if doc.get('kind') == 'strategy':
                refs.extend(doc.get('factors',[]))
                if 'path' in doc.get('universe',{}): refs.append(doc['universe']['path'])
            for ref in refs:
                if not isinstance(ref,str): raise AgentError('KF_AGENT_REJECTED')
                child = self._path(str((file.parent/ref).relative_to(self.root)))
                visit(child)
            if doc.get('format') == 'snapshot.parquet.v1':
                for item in doc['datasets'].values():
                    self._path(str((file.parent/item['path']).relative_to(self.root)))
            if doc.get('kind') == 'run' and doc.get('mode') not in {'backtest','paper','fake'}:
                raise AgentError('KF_AGENT_DISABLED')
        visit(self._path(value))
        return self._path(value)

    def tool_catalog(self):
        return [{"name":name,"risk_class":"R"+str(risk),"inputSchema":spec,
                 "description":{"en_US":f"Local {name.replace('_',' ')}; no external order actions.",
                                "zh_CN":f"本地接口 {name}；不执行外部下单。",
                                "ja_JP":f"ローカル操作 {name}。外部注文は実行しません。"}[self.locale]}
                for name,(risk,spec) in TOOLS.items() if risk < 2 or self.enable_paper]

    def call(self, tool, arguments=None, *, agent_call_id=None, idempotency_key=None):
        arguments = {} if arguments is None else arguments
        call_id = agent_call_id or uuid.uuid4().hex
        try:
            if tool not in TOOLS: raise AgentError('KF_AGENT_DISABLED')
            risk,spec = TOOLS[tool]
            if risk == 2 and not self.enable_paper: raise AgentError('KF_AGENT_DISABLED')
            Draft202012Validator(spec).validate(arguments)
            _check_secrets(arguments,Path('agent-input'))
            if risk == 2 and (not agent_call_id or not idempotency_key): raise AgentError('KF_AGENT_IDEMPOTENCY')
            for item in (call_id,idempotency_key):
                if item is not None and (not isinstance(item,str) or not 1 <= len(item) <= 128): raise AgentError('KF_AGENT_REJECTED')
            input_hash = digest({"tool":tool,"arguments":arguments})
            # Single writer and durable STARTED receipts prevent blind replay after crashes.
            with self.lock:
                with self._db() as db:
                    prior = db.execute('SELECT input_hash,state,result FROM calls WHERE idem=?',(idempotency_key,)).fetchone() if idempotency_key else None
                    if prior:
                        if prior[0] != input_hash or prior[1] != 'SUCCEEDED': raise AgentError('KF_AGENT_IDEMPOTENCY')
                        return json.loads(prior[2])
                    db.execute('INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?)',(call_id,idempotency_key,input_hash,None,None,now(),tool,'STARTED',None))
                try:
                    result = plain(self._dispatch(tool,arguments))
                    _check_secrets(result,Path('agent-output'))
                    response = {"ok":True,"agent_call_id":call_id,"result":result}
                    with self._db() as db:
                        db.execute('UPDATE calls SET state=?,result_hash=?,run_id=?,result=? WHERE call_id=?',
                                   ('SUCCEEDED',digest(result),result.get('run_id'),json.dumps(response,allow_nan=False),call_id))
                    return response
                except Exception:
                    with self._db() as db: db.execute('UPDATE calls SET state=? WHERE call_id=?',('FAILED',call_id))
                    raise
        except Exception as exc:
            code = exc.code if isinstance(exc,AgentError) else 'KF_AGENT_REJECTED'
            # Never return exception text, filesystem paths, supplied values or tracebacks.
            response = {"ok":False,"agent_call_id":call_id,"error":{"code":code,"message":MESSAGES[self.locale].get(code,MESSAGES[self.locale]['KF_AGENT_REJECTED'])}}
            try:
                try: rejected_hash = digest({'tool':tool,'arguments':arguments})
                except Exception: rejected_hash = digest({'invalid_input':True})
                safe_call_id = call_id if isinstance(call_id,str) and 1 <= len(call_id) <= 128 else uuid.uuid4().hex
                with self.lock, self._db() as db:
                    db.execute('INSERT OR IGNORE INTO calls VALUES (?,?,?,?,?,?,?,?,?)',
                               (safe_call_id,None,rejected_hash,digest({'error_code':code}),None,now(),tool if tool in TOOLS else 'UNREGISTERED','REJECTED',json.dumps({'error_code':code})))
            except Exception: pass  # A receipt failure never turns a rejected action into execution.
            return response

    def _new_run(self):
        run_id = uuid.uuid4().hex
        folder = self._path('agent_runs/'+run_id)
        folder.mkdir(parents=True)
        return run_id,folder

    def _run(self, run_id):
        if not isinstance(run_id,str) or len(run_id)!=32 or any(c not in '0123456789abcdef' for c in run_id): raise AgentError('KF_AGENT_REJECTED')
        return self._path('agent_runs/'+run_id)

    def _dispatch(self, tool, a):
        if tool == 'get_capabilities':
            from .external import ReservedExternalActions
            return {"schema_version":"1.0","tools":self.tool_catalog(),"reserved_external_tools":ReservedExternalActions().catalog(),"locales":list(MESSAGES),"external_actions":False,"paper_enabled":self.enable_paper,"private_factors_in_local_install":not all(x.startswith('public.') for x in self.application.builtins.versions)}
        if tool == 'list_factors': return {"factors":plain(self.application.registry.catalog())}
        if tool == 'describe_factor':
            self.application.registry.require(a['implementation_id'],a['implementation_version'])
            return {"implementation_id":a['implementation_id'],"implementation_version":a['implementation_version'],"schema":json.loads((Path(__file__).parents[1]/'schemas/factor.schema.json').read_text())}
        if tool in {'list_strategies','describe_strategy'}:
            from ..strategy_registry import StrategyRegistry
            registry = getattr(self.application,'strategy_registry',None) or StrategyRegistry()
            catalog = plain(registry.catalog())
            if tool == 'list_strategies': return {"strategies":catalog}
            match = [x for x in catalog if x['implementation_id']==a['implementation_id'] and x['implementation_version']==a['implementation_version']]
            if not match: raise AgentError('KF_AGENT_REJECTED')
            return {"strategy":match[0],"schema":json.loads((Path(__file__).parents[1]/'schemas/strategy.schema.json').read_text())}
        if tool == 'inspect_broker_capabilities':
            return {"network_connected":False,"submit_enabled":False,"cancel_enabled":False,"modes":["backtest","paper","fake"]}
        if tool == 'validate_config':
            path = self._graph(a['path']); resolved = self.application.validate(path)
            return {"valid":True,"strategy_hash":resolved.strategy_hash,"data_hash":resolved.data_snapshot_hash,"config_hash":digest(dict(resolved.file_hashes))}
        if tool == 'validate_factor':
            config = load_config(self._path(a['path']))
            from ..factors import FactorSpec
            spec = FactorSpec.from_config(config)
            self.application.registry.require(spec.implementation_id,spec.implementation_version)
            self.application.validators[(spec.implementation_id,spec.implementation_version)](spec)
            return {"valid":True,"factor_id":spec.id}
        if tool == 'inspect_snapshot' or tool in {'check_point_in_time','check_lookahead'}:
            file = self._graph(a['path']); doc = self._json(file)
            from ..data_snapshot import snapshot_frames
            datasets = snapshot_frames(file,doc)
            if tool == 'inspect_snapshot': return {"snapshot_hash":hashlib.sha256(file.read_bytes()).hexdigest(),"datasets":{k:{"rows":len(v),"columns":list(v.columns)} for k,v in datasets.items()}}
            from ..research_diagnostics import check_visibility
            checked = check_visibility(datasets,a['decision_at'])
            from ..factors import FactorContext
            context = FactorContext(decision_at=a['decision_at'],datasets=datasets,data_snapshot_hash=digest(doc))
            checked['gated_rows'] = {k:len(context.read(k)) for k in datasets}
            checked['lookahead_check'] = 'AVAILABLE_AT_GATE_ONLY'
            return checked
        if tool == 'plan_strategy':
            from ..cli import plan_file
            path = self._graph(a['path']); execution = self._path(a['execution']); self._json(execution)
            result = plan_file(path,execution,a['decision_at'],a['now'])
            run_id,folder = self._new_run(); write_new(folder/'report.json',result)
            return {"run_id":run_id,"report":result,"external_submission":False}
        if tool == 'run_demo':
            from ..demo import create_demo
            from ..cli import plan_file
            run_id,folder = self._new_run(); demo = create_demo(folder/'demo')
            reports = [plan_file(demo/(mode+'.json'),demo/'execution.json','2024-05-01T09:00:00+09:00','2024-05-01T09:00:00+09:00') for mode in ('backtest','paper','fake')]
            intents = [x['plan']['intents'] for x in reports]
            if not intents[0] or not intents[0]==intents[1]==intents[2]: raise AgentError('KF_AGENT_REJECTED')
            write_new(folder/'report.json',reports[0])
            return {"run_id":run_id,"mode_intent_parity":True,"intent_count":len(intents[0]),"external_submission":False}
        if tool in {'start_backtest','run_backtest','start_paper_simulation'}:
            path = self._graph(a['path']); timeline = self._path(a['timeline']); self._json(timeline)
            resolved = self.application.validate(path)
            if tool == 'start_paper_simulation' and resolved.run['mode'] != 'paper': raise AgentError('KF_AGENT_REJECTED')
            if tool != 'start_paper_simulation' and resolved.run['mode'] != 'backtest': raise AgentError('KF_AGENT_REJECTED')
            return self._start_job(path,timeline, 'paper' if tool == 'start_paper_simulation' else 'backtest')
        if tool in {'get_job_status','get_job_result','cancel_job','stop_paper_simulation'}:
            job = self.jobs.get(a['job_id'])
            if job is None: raise AgentError('KF_AGENT_REJECTED')
            job = self._json(self._path('agent_jobs/'+job['job_id']+'.json'))
            self.jobs[job['job_id']] = job
            if tool == 'stop_paper_simulation' and job['job_type'] != 'paper': raise AgentError('KF_AGENT_REJECTED')
            if tool in {'cancel_job','stop_paper_simulation'}:
                if job['state'] in {'QUEUED','RUNNING'}:
                    event = self.cancellations.get(job['job_id'])
                    if event: event.set()
                    self._path('agent_jobs/'+job['job_id']+'.cancel').write_text(now(),encoding='utf-8')
                return {"job_id":job['job_id'],"run_id":job['run_id'],"cancel_requested":job['state'] in {'QUEUED','RUNNING'},"state":job['state']}
            if tool == 'get_job_result' and job['state']=='SUCCEEDED': return {"job":dict(job),"report":self._json(self._run(job['run_id'])/'report.json')}
            return dict(job)
        if tool in {'inspect_run','get_run_status','get_run_report','list_orders','list_fills','get_account_snapshot','reconcile_local_state'}:
            folder = self._run(a['run_id'])
            if tool == 'get_run_status':
                job = next((item for item in self.jobs.values() if item.get('run_id')==a['run_id']),None)
                if job:
                    job = self._json(self._path('agent_jobs/'+job['job_id']+'.json'))
                    return {"run_id":a['run_id'],"state":job['state'],"job_id":job['job_id']}
                return {"run_id":a['run_id'],"state":"SUCCEEDED" if (folder/'report.json').exists() else 'UNKNOWN'}
            report = self._json(folder/'report.json')
            if tool in {'list_orders','list_fills','get_account_snapshot','reconcile_local_state'}:
                journal = self._path(str((folder/'history/journal.sqlite').relative_to(self.root)))
                if not journal.exists():
                    return {"run_id":a['run_id'],"status":"PLANNED_ONLY","orders":report.get('plan',{}).get('intents',[]),"fills":[],"account":None}
                # Read-only SQLite; never instantiate Store here (its constructor mutates).
                with closing(sqlite3.connect(journal.as_uri()+'?mode=ro',uri=True)) as db:
                    if tool == 'reconcile_local_state':
                        integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
                        return {"run_id":a['run_id'],"integrity":integrity,"modified":False,"external_reconciliation":False}
                    table = {'list_orders':'orders','list_fills':'fills','get_account_snapshot':'accounts'}.get(tool)
                    cursor = db.execute('SELECT * FROM '+table+' LIMIT 1000')
                    names = [x[0] for x in cursor.description]
                    rows = [dict(zip(names,row)) for row in cursor.fetchall()]
                    return {"run_id":a['run_id'],"rows":rows,"limit":1000}
            output = {"run_id":a['run_id'],"report":report}
            if tool=='inspect_run':
                with self._db() as db:
                    cursor = db.execute('SELECT call_id,idem,input_hash,result_hash,run_id,timestamp,tool,state FROM calls WHERE run_id=?',(a['run_id'],))
                    output['audit'] = [asdict(AgentCallRecord(*row)) for row in cursor.fetchall()]
            return output
        if tool == 'analyze_factor':
            report = self._json(self._run(a['run_id'])/'report.json')
            import pandas as pd
            from ..research_diagnostics import analyze_frame
            reports = report.get('decisions',[report])
            frames = []
            for decision in reports:
                factor = decision['factors'][a['factor_id']]['minimal']
                frames.append(pd.DataFrame(factor['rows'],columns=factor['columns']))
            return analyze_frame(pd.concat(frames,ignore_index=True),quantiles=a.get('quantiles',5))
        if tool == 'compare_runs':
            left = self._json(self._run(a['left'])/'report.json'); right = self._json(self._run(a['right'])/'report.json')
            return {"left":a['left'],"right":a['right'],"same_strategy":left.get('strategy_hash')==right.get('strategy_hash'),"same_decision":left.get('decision_identity')==right.get('decision_identity'),"same_result":digest(left)==digest(right)}
        if tool == 'create_workspace':
            path = self._named('workspaces',a['name']); path.mkdir(parents=True,exist_ok=False)
            write_new(path/'workspace.json',{"schema_version":"1.0","created_at":now()})
            return {"workspace":str(path.relative_to(self.root)),"run_id":uuid.uuid4().hex}
        if tool == 'save_strategy_draft':
            from ..config import _load_config_snapshot
            path = self._named('drafts',a['name']+'.json')
            raw = json.dumps(a['config'],allow_nan=False).encode()
            _load_config_snapshot(path,(a['config'],hashlib.sha256(raw).hexdigest()))
            if a['config'].get('kind')!='strategy': raise AgentError('KF_AGENT_REJECTED')
            path.parent.mkdir(parents=True,exist_ok=True); write_new(path,a['config'])
            return {"draft":str(path.relative_to(self.root)),"run_id":uuid.uuid4().hex,"config_hash":digest(a['config'])}
        raise AgentError('KF_AGENT_DISABLED')

    def _named(self, folder, name):
        if not name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.' for c in name) or name in {'.','..'}: raise AgentError('KF_AGENT_PATH')
        return self._path(folder+'/'+name)

    def _persist_job(self, job):
        file = self._path('agent_jobs/'+job['job_id']+'.json')
        temp = file.with_suffix('.tmp'); temp.write_text(json.dumps(job),encoding='utf-8'); temp.replace(file)

    def _start_job(self, path, timeline, kind):
        run_id,folder = self._new_run(); job_id = uuid.uuid4().hex
        resolved = self.application.validate(path)
        # Capture exact input bytes before queuing; later user edits cannot change a job.
        captured = folder/'inputs'; captured.mkdir()
        for filename, expected in resolved.file_hashes.items():
            source = self._path(str(Path(filename).relative_to(self.root)))
            raw = source.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected: raise AgentError('KF_AGENT_REJECTED')
            destination = captured/source.relative_to(self.root)
            destination.parent.mkdir(parents=True,exist_ok=True); destination.write_bytes(raw)
        timeline_raw = timeline.read_bytes()
        captured_timeline = captured/timeline.relative_to(self.root)
        if captured_timeline.exists() and captured_timeline.read_bytes()!=timeline_raw: raise AgentError('KF_AGENT_REJECTED')
        captured_timeline.parent.mkdir(parents=True,exist_ok=True); captured_timeline.write_bytes(timeline_raw)
        captured_path = captured/path.relative_to(self.root)
        job = {"job_id":job_id,"job_type":kind,"state":"QUEUED","created_at":now(),"started_at":None,"finished_at":None,
               "result_ref":None,"error_code":None,"run_id":run_id,
               "input_hash":digest({"files":dict(resolved.file_hashes),"timeline":hashlib.sha256(timeline_raw).hexdigest()}),
               "worker":"in_process_thread","owner_pid":os.getpid(),"output_dir":str(folder.relative_to(self.root)),
               "command":["framework_v2.history.run_history",str(captured_path.relative_to(self.root)),str(captured_timeline.relative_to(self.root))],
               "recovery":"interrupted jobs fail closed; no automatic replay","cancel":"cancel_job"}
        self.jobs[job_id] = job; event = threading.Event(); self.cancellations[job_id] = event
        self._persist_job(job)
        def worker():
            try:
                from ..history import run_history
                with self.lock:
                    job.update(state='RUNNING',started_at=now()); self._persist_job(job)
                def canceled(): return event.is_set() or self._path('agent_jobs/'+job_id+'.cancel').exists()
                result = run_history(captured_path,captured_timeline,output_dir=folder/'history',cancel_check=canceled)
                if canceled(): raise InterruptedError()
                write_new(folder/'report.json',result)
                with self.lock: job.update(state='SUCCEEDED',result_ref='kabuforge://runs/'+run_id)
            except InterruptedError:
                with self.lock: job.update(state='CANCELED',error_code='KF_JOB_CANCELED')
            except Exception:
                with self.lock: job.update(state='FAILED',error_code='KF_JOB_FAILED')
            finally:
                with self.lock:
                    job['finished_at'] = now(); self._persist_job(job)
        threading.Thread(target=worker,name='kabuforge-'+job_id,daemon=True).start()
        return {"job_id":job_id,"run_id":run_id,"state":"QUEUED"}


class AgentResourceService:
    def __init__(self, command_service): self.commands = command_service

    def read(self, uri):
        simple = {'kabuforge://capabilities':'get_capabilities','kabuforge://factor-catalog':'list_factors','kabuforge://strategy-catalog':'list_strategies'}
        if uri in simple: return self.commands.call(simple[uri])
        if uri.startswith('kabuforge://runs/'):
            return self.commands.call('get_run_report',{'run_id':uri.removeprefix('kabuforge://runs/')})
        if uri.startswith('kabuforge://schemas/'):
            kind = uri.removeprefix('kabuforge://schemas/')
            if kind not in {'factor','strategy','run'}: raise AgentError('KF_AGENT_REJECTED')
            return json.loads((Path(__file__).parents[1]/'schemas'/f'{kind}.schema.json').read_text())
        if uri.startswith('kabuforge://docs/'):
            parts = uri.removeprefix('kabuforge://docs/').split('/')
            documents = {'README','ARCHITECTURE','DEVELOPMENT','AGENT_API','FACTOR_API','STRATEGY_API','EXECUTION','BROKER_API','RESEARCH_METHODOLOGY','SECURITY','CONTRIBUTING','RELEASE_PROCESS','ROADMAP','CHANGELOG'}
            if len(parts)!=2 or parts[0] not in MESSAGES or parts[1] not in documents: raise AgentError('KF_AGENT_REJECTED')
            path = Path(__file__).parents[2]/'docs'/parts[0]/(parts[1]+'.md')
            if not path.exists(): path = Path(__file__).parents[1]/'docs'/parts[0]/(parts[1]+'.md')
            return {"locale":parts[0],"document":parts[1],"content":path.read_text(encoding='utf-8')}
        raise AgentError('KF_AGENT_REJECTED')
