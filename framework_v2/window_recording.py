"""Opt-in recording of this live Qt window, never other desktop applications."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from PySide6.QtCore import QObject, QTimer, QBuffer, QIODevice
from PySide6.QtGui import QKeySequence, QShortcut


class WindowRecorder(QObject):
    def __init__(self, window, directory):
        super().__init__(window)
        self.window=window; self.root=Path(directory); self.root.mkdir(parents=True,exist_ok=False)
        self.frames=[]; self.previous=None
        self.timer=QTimer(self); self.timer.setInterval(750); self.timer.timeout.connect(self.capture)
        self.shortcut=QShortcut(QKeySequence('Ctrl+Shift+R'),window,activated=self.toggle)
        self.single=QShortcut(QKeySequence('Ctrl+Shift+P'),window,activated=lambda:self.capture(force=True))
        window.destroyed.connect(self.finish)

    def toggle(self):
        if self.timer.isActive():
            self.finish(); self.window.statusBar().showMessage('Recording saved / 录制已保存 / 録画を保存しました')
        else:
            self.window.statusBar().showMessage('Recording this application window / 正在录制本窗口 / このウィンドウを録画中')
            self.timer.start(); self.capture(force=True)

    def capture(self, force=False):
        if not self.window.isVisible() or self.window.isMinimized(): return
        pixmap=self.window.grab()
        buffer=QBuffer(); buffer.open(QIODevice.OpenModeFlag.WriteOnly); pixmap.save(buffer,'PNG')
        data=bytes(buffer.data()); digest=hashlib.sha256(data).hexdigest()
        if not force and digest==self.previous: return
        name=f'frame_{len(self.frames):04d}.png'
        with (self.root/name).open('xb') as stream: stream.write(data)
        self.frames.append({'path':name,'at':datetime.now(timezone.utc).isoformat(),'sha256':digest})
        self.previous=digest
        self.write_manifest()

    def write_manifest(self):
        (self.root/'recording.json').write_text(json.dumps({'capture':'live_Qt_widget_surface',
            'scope':'application client area; no desktop, cursor, or external dialogs',
            'frames':self.frames},ensure_ascii=False,indent=2),encoding='utf-8')

    def finish(self,*_):
        self.timer.stop(); self.write_manifest()
