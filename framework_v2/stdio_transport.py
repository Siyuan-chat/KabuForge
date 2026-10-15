"""Sequential MCP responses with an independent control reader and framed input."""
import json
import queue
import threading

from .config import _unique_pairs, _reject_constant
from .request_control import cancellation_scope
from .agent.core import TOOLS

_CANCELLABLE = frozenset({'research_price', 'research_price_research',
    'research_factor_diagnostics', 'research_factor_strategy', 'research_model_training',
    'research_engine_comparison', 'research_indicator', 'research_price_sensitivity'})


def serve(adapter, stdin, stdout):
    # Keep control reads independent of queued business requests: queue
    # backpressure must not prevent reaching a cancellation notification/EOF.
    # The existing readline character limit remains authoritative.
    frames = queue.SimpleQueue()
    events = {}
    lock = threading.Lock()
    stopped = threading.Event()

    def enqueue(frame):
        if not stopped.is_set():
            frames.put(frame)

    def reader():
        try:
            while not stopped.is_set():
                line = stdin.readline(1024 * 1024 + 1)
                if not line:
                    break
                if len(line) > 1024 * 1024:
                    while line and not line.endswith('\n'):
                        line = stdin.readline(1024 * 1024 + 1)
                    enqueue((None, None, -32600, 'Request too large'))
                    continue
                try:
                    value = json.loads(line, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
                except (ValueError, TypeError):
                    enqueue((None, None, -32700, 'Parse error'))
                    continue
                if not isinstance(value, dict):
                    enqueue((None, None, -32600, 'Invalid request'))
                    continue
                request_id = value.get('id')
                params = value.get('params', {})
                if (value.get('jsonrpc') == '2.0' and 'id' not in value
                        and value.get('method') == 'notifications/cancelled' and isinstance(params, dict)):
                    key = params.get('requestId')
                    if type(key) in (str, int):
                        with lock:
                            event = events.get(key)
                            if event is not None: event.set()
                    continue
                event = None
                if (type(request_id) in (str, int) and value.get('method') == 'tools/call'
                        and isinstance(params, dict) and isinstance(params.get('name'), str)
                        and params['name'] in _CANCELLABLE
                        and TOOLS.get(params['name'],(-1,None))[0] == 1):
                    event = threading.Event()
                    with lock:
                        events[request_id] = event
                enqueue((value, event, None, None))
        finally:
            with lock:
                for event in events.values(): event.set()
            enqueue(None)

    thread = threading.Thread(target=reader, name='kabuforge-mcp-control-reader', daemon=True)
    thread.start()
    try:
        while True:
            frame = frames.get()
            if frame is None: break
            value, event, code, message = frame
            try:
                if code is not None:
                    response = {'jsonrpc':'2.0','id':None,'error':{'code':code,'message':message}}
                else:
                    # Only pure research tools receive a token. Paper mutations
                    # retain their existing durable, non-interruptible boundary.
                    with cancellation_scope(event):
                        response = adapter.request(value)
                if response is not None:
                    stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + '\n')
                    stdout.flush()
            finally:
                if value is not None and event is not None:
                    with lock:
                        if events.get(value.get('id')) is event:
                            del events[value['id']]
    finally:
        stopped.set()
        with lock:
            for event in events.values(): event.set()
        adapter.service.shutdown()
