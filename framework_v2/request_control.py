"""Trusted transport cancellation, without changing request/financial identities."""
from contextlib import contextmanager
from contextvars import ContextVar
import subprocess
import time

_event = ContextVar('research_request_cancellation', default=None)


class RequestCancelled(InterruptedError):
    pass


@contextmanager
def cancellation_scope(event):
    token = _event.set(event)
    try:
        yield
    finally:
        _event.reset(token)


def check_cancelled():
    event = _event.get()
    if event is not None and event.is_set():
        raise RequestCancelled('local research request canceled; partial outputs retained')


def stop_owned(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def wait_owned(process, timeout=None):
    if _event.get() is None:
        return process.wait() if timeout is None else process.wait(timeout=timeout)
    started = time.monotonic()
    while True:
        try:
            check_cancelled()
        except RequestCancelled:
            stop_owned(process)
            raise
        remaining = None if timeout is None else timeout - (time.monotonic() - started)
        if remaining is not None and remaining <= 0:
            raise subprocess.TimeoutExpired(getattr(process, 'args', 'owned worker'), timeout)
        try:
            return process.wait(timeout=.1 if remaining is None else min(.1, remaining))
        except subprocess.TimeoutExpired:
            pass
