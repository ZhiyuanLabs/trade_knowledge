"""
Lightweight execution trace / event bus for the demo SSE endpoint.

During a streaming request a Trace object is placed in a ContextVar. Every
interesting step (LLM calls, tool calls, SQL queries, graph-node transitions,
answer-token deltas) pushes a JSON-serializable event into the trace queue.
The FastAPI /ask/stream endpoint drains that queue and forwards events to the
browser as Server-Sent Events, so the UI can show a live "execution trace".

In a normal (non-streaming) request there is no trace and emit() is a no-op —
all existing behaviour stays unchanged.
"""

from __future__ import annotations

import queue
import time
from contextvars import ContextVar
from typing import Any


class Trace:
    """Collects ordered execution events for one request."""

    def __init__(self) -> None:
        self.queue: "queue.Queue[dict | None]" = queue.Queue()
        self._seq = 0
        self._start = time.monotonic()

    def emit(self, kind: str, **payload: Any) -> None:
        self._seq += 1
        event = {
            "type": kind,
            "seq": self._seq,
            "elapsed": round(time.monotonic() - self._start, 3),
        }
        event.update(payload)
        self.queue.put(event)

    def close(self) -> None:
        self.queue.put(None)


_trace_var: ContextVar[Trace | None] = ContextVar("execution_trace", default=None)


def set_trace(trace: Trace):
    """Bind a trace for the current context/thread. Returns a reset token."""
    return _trace_var.set(trace)


def reset_trace(token) -> None:
    _trace_var.reset(token)


def get_trace() -> Trace | None:
    return _trace_var.get()


def emit(kind: str, **payload: Any) -> None:
    """Emit an event only when a trace is active."""
    trace = _trace_var.get()
    if trace is not None:
        trace.emit(kind, **payload)


def clip(text: str, limit: int = 1200) -> str:
    """Truncate long prompt/response text for the UI trace."""
    if text is None:
        return ""
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + " …"
