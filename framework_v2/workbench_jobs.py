"""Owned QProcess jobs: explicit manifests, isolated outputs, bounded cancellation."""
from __future__ import annotations
import codecs,hashlib,json,uuid
from datetime import datetime,timezone
from pathlib import Path
import os,platform,sys,sysconfig
from PySide6.QtCore import QObject,QProcess,QProcessEnvironment,QTimer,Signal

_WORKER_ENVIRONMENT_KEYS=frozenset({"SYSTEMROOT","WINDIR","PATH","TEMP","TMP","LOCALAPPDATA",
    "APPDATA","USERPROFILE","HOMEDRIVE","HOMEPATH"})

class JobController(QObject):
    started=Signal(dict); finished=Signal(dict); log=Signal(str)
    def __init__(self,workspace,parent=None):
        super().__init__(parent); self.workspace=Path(workspace).resolve(strict=True); self.process=None
        self.current=None; self.buffer=""; self.cancel_requested=False; self.jobs=[]
        jobs_root=self.workspace/"jobs"
        if jobs_root.exists() and not jobs_root.resolve().is_relative_to(self.workspace):
            raise ValueError("workbench jobs directory escapes its workspace")
        resolved_jobs=jobs_root.resolve()
        for path in sorted(jobs_root.glob("*/manifest.json")) if jobs_root.is_dir() else ():
            try:
                if path.is_symlink() or not path.parent.resolve().is_relative_to(resolved_jobs): continue
                job=json.loads(path.read_text(encoding="utf-8"))
                if job.get("status") in {"STARTING","RUNNING","CANCELING"}:
                    job["status"]="INTERRUPTED / 状态待核对"
                self.jobs.append(job)
            except (OSError,ValueError): pass

    @property
    def busy(self): return self.process is not None

    def _validate_current_directory(self):
        jobs_root=(self.workspace/"jobs").resolve(strict=True)
        job_dir=Path(self.current["manifest"]).parent.resolve(strict=True)
        if not jobs_root.is_relative_to(self.workspace) or not job_dir.is_relative_to(jobs_root):
            raise RuntimeError("owned workbench job directory escaped its workspace")
        return job_dir

    @staticmethod
    def _runtime_paths(request):
        if not (request.get("action")=="price_research" or
                (request.get("action")=="preflight" and request.get("target_action")=="price_research")):
            return []
        recipe=request.get("recipe") or {}
        if not isinstance(recipe,dict): raise ValueError("price-research recipe must be an object")
        provider="talib" if recipe.get("signal_template")=="sma_crossover" and recipe.get("signal_provider")=="talib" else "native"
        from .research_runtime import resolve_research_runtime
        operation="indicators" if provider=="talib" else "native"
        choices={"provider":"talib"} if provider=="talib" else None
        runtime=resolve_research_runtime(Path(__file__).resolve().parents[1],platform.python_version(),
            "win-amd64" if os.name=="nt" and sys.maxsize>2**32 else sysconfig.get_platform(),
            operation=operation,choices=choices)
        if not runtime.get("enabled"):
            raise RuntimeError("selected price-research dependencies are unavailable: "+str(runtime.get("reason") or "runtime unavailable"))
        return list(runtime.get("paths",[]))

    def start(self,request):
        if self.busy: raise RuntimeError("已有本工作台任务运行，请等待或取消")
        if not isinstance(request,dict) or request.get("action") not in {"preflight","journal","demo","plan","history","simulate","guided_demo","price_research"}:
            raise ValueError("unsupported workbench action")
        runtime_paths=self._runtime_paths(request)
        jobs_root=self.workspace/"jobs"
        jobs_root.mkdir(parents=True,exist_ok=True)
        jobs_root=jobs_root.resolve(strict=True)
        if not jobs_root.is_relative_to(self.workspace) or not jobs_root.is_dir():
            raise ValueError("workbench jobs directory escapes its workspace")
        job_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")+"-"+uuid.uuid4().hex[:8]
        directory=jobs_root/job_id; directory.mkdir(parents=True,exist_ok=False)
        directory=directory.resolve(strict=True)
        if not directory.is_relative_to(jobs_root):
            raise ValueError("owned job directory escapes its workspace")
        request={**request,"job_id":job_id,"workspace_path":str(self.workspace),"output_dir":str(directory/"output")}
        request_path=directory/"request.json"
        with request_path.open("x",encoding="utf-8",newline="\n") as stream:
            json.dump(request,stream,ensure_ascii=False,indent=2,allow_nan=False); stream.write("\n")
        self.current={"job_id":job_id,"action":request["action"],"status":"STARTING","started_at":datetime.now(timezone.utc).isoformat(),
            "request":str(request_path),"input_hash":hashlib.sha256(request_path.read_bytes()).hexdigest(),
            "output_dir":request["output_dir"],"log":str(directory/"worker.log"),"manifest":str(directory/"manifest.json"),
            "command":[sys.executable,"-B","-m","framework_v2.workbench_worker","--request",str(request_path)],"pid":None,
            "checkpoint":"request.json; partial outputs are retained; do not replay uncertain orders"}
        self.buffer=""; self.decoder=codecs.getincrementaldecoder("utf-8")("replace"); self.cancel_requested=False; self.jobs.append(self.current)
        process=QProcess(self); self.process=process
        process.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        inherited=QProcessEnvironment.systemEnvironment(); env=QProcessEnvironment()
        for name in inherited.keys():
            if name.upper() in _WORKER_ENVIRONMENT_KEYS: env.insert(name,inherited.value(name))
        package_root=str(Path(__file__).resolve().parents[1])
        env.insert("PYTHONPATH",os.pathsep.join([*map(str,runtime_paths),package_root]))
        env.insert("PYTHONDONTWRITEBYTECODE","1"); env.insert("PYTHONIOENCODING","utf-8")
        process.setProcessEnvironment(env); process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._read)
        process.started.connect(self._started); process.finished.connect(self._finished)
        process.errorOccurred.connect(self._error)
        self._persist(); process.start(sys.executable,self.current["command"][1:])
        return job_id

    def _persist(self):
        job_dir=self._validate_current_directory()
        path=job_dir/"manifest.json"
        if path.is_symlink(): raise RuntimeError("job manifest cannot be a symbolic link")
        path.write_text(json.dumps(self.current,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")

    def _started(self):
        self.current.update(pid=int(self.process.processId()),status="RUNNING")
        self._persist(); self.started.emit(dict(self.current))

    def _read(self):
        if self.process is None: return
        chunk=self.decoder.decode(bytes(self.process.readAllStandardOutput()))
        self.buffer+=chunk
        job_dir=self._validate_current_directory(); log_path=job_dir/"worker.log"
        if log_path.is_symlink(): raise RuntimeError("job log cannot be a symbolic link")
        with log_path.open("a",encoding="utf-8") as stream: stream.write(chunk)
        self.log.emit(chunk)

    def _error(self,error):
        if error==QProcess.ProcessError.FailedToStart and self.process is not None:
            self.buffer+="Worker process failed to start"
            self._finished(-1,QProcess.ExitStatus.CrashExit)

    def _finished(self,code,status):
        if self.process is None: return
        self._read(); result=None
        for line in self.buffer.splitlines():
            if line.startswith("WORKBENCH_RESULT="):
                try: result=json.loads(line.split("=",1)[1])
                except ValueError: pass
        valid=result is not None and result.get("job_id")==self.current["job_id"]
        success=code==0 and valid and result.get("ok") is True and not self.cancel_requested
        state="COMPLETED" if success else ("CANCELED" if self.cancel_requested else "FAILED")
        self.current.update(status=state,exit_code=int(code),finished_at=datetime.now(timezone.utc).isoformat(),
            result=result if valid else None,error=None if success else ((result or {}).get("errors") or "任务中止或未返回有效结果；见完整日志"))
        self._persist(); message=dict(self.current); old=self.process; self.process=None; old.deleteLater()
        self.finished.emit(message)

    def cancel(self):
        process=self.process
        if process is None or process.state()==QProcess.ProcessState.NotRunning: return False
        self.cancel_requested=True; self.current["status"]="CANCELING"; self._persist(); process.terminate()
        QTimer.singleShot(2000,lambda:self._kill_owned(process))
        return True

    def _kill_owned(self,process):
        if self.process is process and process.state()!=QProcess.ProcessState.NotRunning: process.kill()
