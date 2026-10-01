"""Owned QProcess jobs: explicit manifests, isolated outputs, bounded cancellation."""
from __future__ import annotations
import codecs,hashlib,json,uuid
from datetime import datetime,timezone
from pathlib import Path
import sys
from PySide6.QtCore import QObject,QProcess,QProcessEnvironment,QTimer,Signal

class JobController(QObject):
    started=Signal(dict); finished=Signal(dict); log=Signal(str)
    def __init__(self,workspace,parent=None):
        super().__init__(parent); self.workspace=Path(workspace).resolve(); self.process=None
        self.current=None; self.buffer=""; self.cancel_requested=False; self.jobs=[]
        for path in sorted((self.workspace/"jobs").glob("*/manifest.json")):
            try:
                job=json.loads(path.read_text(encoding="utf-8"))
                if job.get("status") in {"STARTING","RUNNING","CANCELING"}:
                    job["status"]="INTERRUPTED / 状态待核对"
                self.jobs.append(job)
            except (OSError,ValueError): pass

    @property
    def busy(self): return self.process is not None

    def start(self,request):
        if self.busy: raise RuntimeError("已有本工作台任务运行，请等待或取消")
        job_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")+"-"+uuid.uuid4().hex[:8]
        directory=self.workspace/"jobs"/job_id; directory.mkdir(parents=True,exist_ok=False)
        request={**request,"job_id":job_id,"output_dir":str(directory/"output")}
        request_path=directory/"request.json"; request_path.write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding="utf-8")
        self.current={"job_id":job_id,"action":request["action"],"status":"STARTING","started_at":datetime.now(timezone.utc).isoformat(),
            "request":str(request_path),"input_hash":hashlib.sha256(request_path.read_bytes()).hexdigest(),
            "output_dir":request["output_dir"],"log":str(directory/"worker.log"),"manifest":str(directory/"manifest.json"),
            "command":[sys.executable,"-B","-m","framework_v2.workbench_worker","--request",str(request_path)],"pid":None,
            "checkpoint":"request.json; partial outputs are retained; do not replay uncertain orders"}
        self.buffer=""; self.decoder=codecs.getincrementaldecoder("utf-8")("replace"); self.cancel_requested=False; self.jobs.append(self.current)
        process=QProcess(self); self.process=process
        process.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        env=QProcessEnvironment.systemEnvironment(); env.insert("PYTHONDONTWRITEBYTECODE","1"); env.insert("PYTHONIOENCODING","utf-8")
        process.setProcessEnvironment(env); process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._read)
        process.started.connect(self._started); process.finished.connect(self._finished)
        process.errorOccurred.connect(self._error)
        self._persist(); process.start(sys.executable,self.current["command"][1:])
        return job_id

    def _persist(self):
        Path(self.current["manifest"]).write_text(json.dumps(self.current,ensure_ascii=False,indent=2),encoding="utf-8")

    def _started(self):
        self.current.update(pid=int(self.process.processId()),status="RUNNING")
        self._persist(); self.started.emit(dict(self.current))

    def _read(self):
        if self.process is None: return
        chunk=self.decoder.decode(bytes(self.process.readAllStandardOutput()))
        self.buffer+=chunk
        with Path(self.current["log"]).open("a",encoding="utf-8") as stream: stream.write(chunk)
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
