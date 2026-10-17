"""Deterministic destruction of already-closed, test-owned Qt windows."""
from PySide6.QtCore import QCoreApplication, QEvent, QProcess, QThread
from shiboken6 import Shiboken


def dispose_closed_widget(widget):
    """Dispose one owned window after its existing close/worker checks finish.

    Does not close windows, stop workers, or change the shared QApplication.
    """
    if not Shiboken.isValid(widget):
        return
    if widget.isVisible():
        raise RuntimeError("Refusing to dispose a window whose close was rejected")
    for thread in widget.findChildren(QThread):
        if thread.isRunning():
            raise RuntimeError("Refusing to dispose a window with a running owned QThread")
    for process in widget.findChildren(QProcess):
        if process.state() != QProcess.ProcessState.NotRunning:
            raise RuntimeError("Refusing to dispose a window with a running owned QProcess")
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(widget, QEvent.Type.DeferredDelete)
