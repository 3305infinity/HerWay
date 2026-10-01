"""
Request-scoped trace identifiers.

Why this exists
---------------
HerWay answers a single user message by fanning out across several agents and
services (situation analysis → research planning → SerpApi → source
verification → action/safety planning). When one of those fails, the log lines
from the others are interleaved with every other concurrent request, and there
is no way to reassemble what happened for one person.

A trace ID is a short, random, meaningless token carried in a ``ContextVar`` for
the lifetime of one request. ``contextvars`` are the right tool because asyncio
copies the context per task: two concurrent requests, and any ``asyncio.gather``
fan-out inside them, each see their own value without it being threaded through
every function signature.

Security properties
-------------------
- **A trace ID is a diagnostic label, never an authorization token.** It is
  returned to the browser and is guessable by design. Nothing may grant access
  based on it. Ownership is decided solely by ``backend.auth``.
- **Client-supplied IDs are validated, never trusted verbatim.** An unvalidated
  value flows into log files, so it is a log-injection and unbounded-growth
  vector. Anything that is not a short, plain token is discarded and replaced
  with a fresh server-generated ID.
- **Nothing sensitive belongs in a trace ID or in the log fields built here.**
  No user message, location, case content, token or evidence.

This module deliberately has no dependency on FastAPI, any LLM provider, or any
other part of the backend, so agents and services can import it freely.
"""

from __future__ import annotations

import logging
import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Dict, Iterator, Optional

#: Header used to accept an inbound trace ID and to return the active one.
TRACE_HEADER = "X-Trace-Id"

#: Accepted shape for a client-supplied trace ID: a short, plain token.
#: Deliberately strict — this value reaches log files, so newlines, control
#: characters, ANSI escapes and unbounded length are all refused.
_TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

_TRACE_ID: ContextVar[Optional[str]] = ContextVar("herway_trace_id", default=None)


def new_trace_id() -> str:
    """A fresh, random trace ID. 32 hex chars — collision-free in practice."""
    return uuid.uuid4().hex


def is_valid_trace_id(value: Any) -> bool:
    """Whether ``value`` is acceptable as a trace ID.

    Rejects non-strings, anything shorter than 8 or longer than 64 characters,
    and anything outside ``[A-Za-z0-9_-]``.
    """
    return isinstance(value, str) and bool(_TRACE_ID_PATTERN.match(value))


def coerce_trace_id(value: Any) -> str:
    """Return ``value`` if it is a valid trace ID, otherwise a fresh one.

    Used at the edge: a caller may propagate its own ID for cross-service
    correlation, but a malformed or hostile value is silently replaced rather
    than rejected — a bad header should not fail a woman's request for help.
    """
    return value if is_valid_trace_id(value) else new_trace_id()


def get_trace_id() -> Optional[str]:
    """The trace ID for the current context, or ``None`` outside a request."""
    return _TRACE_ID.get()


def set_trace_id(trace_id: str) -> Token:
    """Bind ``trace_id`` to the current context.

    Returns the token needed to restore the previous value; prefer
    :func:`trace_context`, which cannot be left unbalanced.
    """
    return _TRACE_ID.set(trace_id)


def reset_trace_id(token: Token) -> None:
    """Restore the value replaced by :func:`set_trace_id`."""
    _TRACE_ID.reset(token)


@contextmanager
def trace_context(trace_id: Optional[str] = None) -> Iterator[str]:
    """Bind a trace ID for the duration of the block, then restore it.

    The reset happens in ``finally``, so an exception inside the block cannot
    leave a stale ID bound to the context — which, on a reused worker task,
    would mislabel the next request's logs.

    >>> with trace_context() as tid:
    ...     assert get_trace_id() == tid
    """
    token = _TRACE_ID.set(coerce_trace_id(trace_id))
    try:
        yield _TRACE_ID.get()  # type: ignore[misc]
    finally:
        _TRACE_ID.reset(token)


class TraceIdFilter(logging.Filter):
    """Attaches ``trace_id`` to every record so formatters can print it.

    Records emitted outside a request get ``"-"`` rather than failing to format.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id() or "-"
        return True


def install_log_filter(*loggers: logging.Logger) -> None:
    """Attach :class:`TraceIdFilter` to the given loggers and their handlers.

    The filter goes on handlers as well as loggers because a ``Filter`` on a
    logger does not apply to records propagated from its children, while one on
    the handler sees everything that handler writes.
    """
    trace_filter = TraceIdFilter()
    for lg in loggers:
        lg.addFilter(trace_filter)
        for handler in lg.handlers:
            handler.addFilter(trace_filter)


def log_fields(**fields: Any) -> Dict[str, Any]:
    """Build a structured log payload carrying the current trace ID.

    Pass only non-sensitive, low-cardinality values: counts, durations, tool
    names, status strings, boolean flags. **Never** a user message, a location,
    case content, a URL from a user, or a credential — these payloads land in
    log files that are not protected like the database is.

    >>> log_fields(tool="search_web", outcome="ok", duration_ms=12)
    {'trace_id': ..., 'tool': 'search_web', 'outcome': 'ok', 'duration_ms': 12}
    """
    payload: Dict[str, Any] = {"trace_id": get_trace_id() or "-"}
    payload.update(fields)
    return payload
