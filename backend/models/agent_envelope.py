"""
A uniform envelope for one agent or tool execution.

The Phase 1 audit found that seven of the nine shared contracts already exist
(``Situation``, ``ResearchPlan``, ``SearchResult``, ``EvidenceItem``,
``ActionPlan``, ``SafetyPlan``, ``Case``). The two genuine gaps were a
request-scoped trace ID — now ``backend.trace`` — and this: a consistent way to
say *what an agent did, whether it actually worked, and how long it took*.

Design constraints taken from the existing code
-----------------------------------------------
- **Wrap, do not inherit.** Agents keep their current signatures and return
  their current domain models. ``AgentExecution.run`` wraps a call; nothing is
  forced into a base class.
- **Reuse the existing failure vocabulary.** ``SearchFailureReason`` and
  ``LLMUnavailableError.reason`` already classify failures well. ``AgentError``
  carries a ``reason`` string so those values pass through unchanged instead of
  being re-encoded into a new taxonomy.
- **Metadata is for debugging, not for data.** Only non-sensitive, low
  cardinality values belong in ``metadata`` — see :func:`backend.trace.log_fields`.

The distinction that matters most
---------------------------------
``AgentStatus`` separates **proposed → attempted → completed**. A safety product
must never tell a woman an action was taken when it only tried. ``completed`` is
reserved for work that actually took effect; ``attempted`` plus an error means
it did not.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Dict, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

from backend.trace import get_trace_id

T = TypeVar("T")


class AgentStatus(str, Enum):
    """What actually happened to an agent or tool invocation."""

    #: Chosen but not yet run — e.g. a tool the model selected this turn.
    PROPOSED = "proposed"
    #: Started and did not finish successfully.
    ATTEMPTED = "attempted"
    #: Finished, and the effect the caller asked for actually took place.
    COMPLETED = "completed"
    #: Finished, but the result is partial — some sub-step degraded.
    PARTIAL = "partial"
    #: Did not run because a dependency was unavailable (no key, provider down).
    UNAVAILABLE = "unavailable"
    #: Deliberately not run — e.g. the planner decided no search was needed.
    SKIPPED = "skipped"


class AgentError(BaseModel):
    """A failure, in terms the caller can act on.

    ``reason`` intentionally mirrors the existing vocabularies
    (``SearchFailureReason``, ``LLMUnavailableError.reason``) rather than
    introducing a competing one.
    """

    reason: str = Field(..., description="Machine-readable cause, e.g. 'rate_limited'")
    message: str = Field(..., description="Operator-facing detail. No user content.")
    user_message: Optional[str] = Field(
        None,
        description="Safe to show a user. Should say what to do next, and must "
        "never imply an action succeeded.",
    )
    retryable: bool = Field(
        False, description="Whether retrying the same call could reasonably succeed"
    )


class AgentExecution(BaseModel, Generic[T]):
    """One agent or tool execution, with its outcome and timing.

    Construct via :meth:`run` rather than by hand so the duration and trace ID
    are always populated consistently.
    """

    agent: str = Field(..., description="Agent or tool name, e.g. 'search_web'")
    status: AgentStatus = AgentStatus.PROPOSED
    trace_id: Optional[str] = Field(
        default=None,
        description="Request trace ID. Diagnostic only — never an authorization token.",
    )
    result: Optional[T] = Field(default=None, description="Structured result when successful")
    error: Optional[AgentError] = Field(default=None, description="Structured failure")
    duration_ms: float = Field(0.0, description="Wall-clock duration of the call")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Non-sensitive debugging context only: counts, flags, names.",
    )

    model_config = {"arbitrary_types_allowed": True}

    # -- convenience -------------------------------------------------------

    @property
    def ok(self) -> bool:
        """Whether the caller may use ``result``.

        ``PARTIAL`` counts: some evidence is better than none, and the
        degradation is reported separately.
        """
        return self.status in (AgentStatus.COMPLETED, AgentStatus.PARTIAL)

    @property
    def did_complete(self) -> bool:
        """Whether the requested effect actually took place.

        Stricter than :attr:`ok`. Use this before telling a user that something
        was done.
        """
        return self.status is AgentStatus.COMPLETED

    # -- construction ------------------------------------------------------

    @classmethod
    def started(cls, agent: str, **metadata: Any) -> "AgentExecution[T]":
        """An execution record for work about to begin."""
        return cls(
            agent=agent,
            status=AgentStatus.PROPOSED,
            trace_id=get_trace_id(),
            metadata=dict(metadata),
        )

    def succeed(self, result: T, *, partial: bool = False, **metadata: Any) -> "AgentExecution[T]":
        self.status = AgentStatus.PARTIAL if partial else AgentStatus.COMPLETED
        self.result = result
        self.metadata.update(metadata)
        return self

    def fail(
        self,
        reason: str,
        message: str,
        *,
        user_message: Optional[str] = None,
        retryable: bool = False,
        unavailable: bool = False,
        **metadata: Any,
    ) -> "AgentExecution[T]":
        self.status = AgentStatus.UNAVAILABLE if unavailable else AgentStatus.ATTEMPTED
        self.error = AgentError(
            reason=reason,
            message=message,
            user_message=user_message,
            retryable=retryable,
        )
        self.metadata.update(metadata)
        return self

    def skip(self, reason: str, **metadata: Any) -> "AgentExecution[T]":
        self.status = AgentStatus.SKIPPED
        self.metadata.update(metadata, skip_reason=reason)
        return self

    # -- the main entry point ---------------------------------------------

    @classmethod
    async def run(
        cls,
        agent: str,
        coro_factory,
        *,
        classify=None,
        **metadata: Any,
    ) -> "AgentExecution[T]":
        """Await ``coro_factory()``, recording status, duration and errors.

        ``coro_factory`` is a zero-argument callable returning an awaitable, so
        timing starts here rather than at the caller's construction site.

        ``classify`` optionally maps a caught exception to an
        :class:`AgentError`; when it returns ``None`` (or is absent) the
        exception is recorded as a generic, non-retryable failure. Exceptions
        are never re-raised — an isolated tool failure must not take down the
        rest of a chat turn.
        """
        execution: "AgentExecution[T]" = cls.started(agent, **metadata)
        start = time.perf_counter()
        try:
            result = await coro_factory()
        except Exception as exc:  # noqa: BLE001 - isolation is the point
            execution.duration_ms = round((time.perf_counter() - start) * 1000, 2)
            classified = classify(exc) if classify else None
            if classified is not None:
                execution.status = AgentStatus.ATTEMPTED
                execution.error = classified
            else:
                execution.fail(
                    reason=type(exc).__name__,
                    message=str(exc)[:500],
                )
            return execution

        execution.duration_ms = round((time.perf_counter() - start) * 1000, 2)
        return execution.succeed(result)
