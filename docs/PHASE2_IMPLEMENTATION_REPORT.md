# HerWay — Phase 2 Implementation Report

**Unified Orchestration and Women-Safety Domain Integration.** Completed
2026-10-01. Builds on [`EXISTING_ARCHITECTURE_AUDIT.md`](EXISTING_ARCHITECTURE_AUDIT.md);
that document is unchanged except where this phase resolved an issue it raised.

Nothing was rebuilt. `ChatAgent` was not replaced, no second orchestrator was
introduced, no feature was removed, and no file was deleted.

---

## 1. The role of `ChatAgent` after this phase

Unchanged in architecture, strengthened in reliability. It remains the central
integration layer: one tool-calling agent that exposes the original Haven
capabilities as twelve tools rather than reimplementing them.

| Tool | Wraps |
|---|---|
| `answer_user` | Terminal response with source URLs |
| `search_web` / `search_news` / `search_local` | `SerpApiService` verticals |
| `search_safety_resources` | Maps-backed resource discovery |
| `update_action_status` | Safety-plan action state |
| `adapt_safety_plan` | `SafetyPlanAgent` re-planning |
| `invoke_lawbot` | `EmbeddingService` legal RAG |
| `search_community` | `EmbeddingService` community matching |
| `encode_message` | Steganography flow |
| `generate_formal_report` | `ReportService` |
| `generate_poem` | Legacy poem generation |

**What changed:**

- Tool dispatch moved from inline in `converse` into `_execute_tool`. This is a
  pure move — no branch logic was altered — so that the call can be timed,
  logged and **isolated**. One tool raising no longer ends the turn with a 500;
  the user gets an honest degraded reply that points at 112/181.
- Structured logging on tool selection and completion: tool name, mode, status,
  duration, error reason. No user message, location or case content.
- `generate_poem` was unguarded and could raise; it now degrades.
- `invoke_lawbot`'s empty-result branch is documented as ambiguous (it means
  either "no match" or "retrieval is down" — issue B-02) and logs which
  happened. Its behaviour was already correct: it falls through to live official
  sources rather than answering from the model's memory.
- `ChatResponse` gained an optional `trace_id`.

The 907-line size was left alone deliberately. Shrinking it was not a goal, and
splitting the dispatch further would have fragmented the one place where the
tool contract is readable end to end.

---

## 2. The canonical research execution path

```
caller
  │
  ├── routes/research.py ──────────┐
  ├── agents/chat_agent.py ──┐     │
  └── routes/cases.py ───────┤     │
                             ▼     ▼
                    ResearchAgent  │     (thin delegate)
                             └─────┤
                                   ▼
                        ResearchOrchestrator      ← the only implementation
                                   │
                                   ▼
                            SerpApiService
```

`ResearchOrchestrator` is canonical. The audit's claim that it is a strict
superset was verified against the code before consolidating:

| Behaviour | old `ResearchAgent` | `ResearchOrchestrator` |
|---|---|---|
| Search budget | **none** | 4 normal / 6 complex, trimmed, configurable |
| PII scrubbing of queries | **none** | `sanitize_search_query` |
| Duplicate-query suppression | URL only | normalised query key + URL |
| Upstream failure signal | exception only | `SearchOutcome.success` + `error_message` |
| Credit metrics | none | `ResearchMetrics` |
| Maps location backfill | none | yes |
| Trace entry fields | 6 | 11 |
| Planner prompt | generic routing | India jurisdiction, named statutes, One Stop Centre / Mahila Thana / DLSA routing, freshness policy, *"return zero tasks if no search is needed"* |

**Nothing was discarded.** Every routing rule in the old planner prompt —
official sources for procedure, news for recent developments, maps for physical
help, no duplicate queries, never send raw user text as a query — is present in
`_ORCHESTRATOR_SYSTEM_PROMPT` in a stronger, India-specific form.

---

## 3. How `ResearchAgent` remains compatible

It was **not** removed. Both callers construct it positionally and use three
methods; all three signatures are unchanged:

```python
ResearchAgent(llm, serpapi)                    # agents/chat_agent.py:576
await agent.plan(case_id, situation, location) # routes/cases.py:409
await agent.execute(plan)
```

`ResearchExecutionResult` gained fields (`metrics`, richer trace entries) and
lost none.

### Intentional behaviour changes

Research reached through **chat** and the **safety-plan adapt** route now also:

1. **Respects a search budget.** Previously the LLM could return any number of
   tasks and every one ran.
2. **Has personal data stripped from queries** before they reach SerpApi. The
   old path sent planner output through unmodified, so a name, email or phone
   number in a task query left the server. This was a live PII leak.
3. **Reports a failed search as failed** rather than as a search that found
   nothing — which matters when telling a woman whether a shelter truly is not
   listed nearby or whether the lookup simply broke.
4. **Skips a repeated identical query** within one plan instead of paying twice.

All four are improvements. They are listed here because they are observable, not
because they are regressions.

---

## 4. Trace ID propagation

`backend/trace.py`. A `ContextVar` holding a short random token for one request.

```
X-Trace-Id (inbound, optional)
   │  validated against ^[A-Za-z0-9_-]{8,64}$ — anything else is discarded
   ▼
assign_trace_id middleware  (outermost, so the error handler sees it)
   │  set → ContextVar  ...  finally: reset, even on exception
   ├─► every log line        [19:36:52] INFO [9f1f6cb6]: Created case ...
   ├─► agents and services    via log_fields(...)
   ├─► asyncio.gather fan-out inherits automatically
   ├─► X-Trace-Id response header
   ├─► ChatResponse.trace_id
   └─► 500 error bodies
```

**Security.** A trace ID is a diagnostic label and nothing else. It is returned
to the browser, guessable by design, and consulted by no authorization code —
there is an explicit test (`test_trace_id_is_not_an_authorization_mechanism`)
asserting that presenting another session's trace ID still yields 403.

Inbound values are validated because they reach log files; an unvalidated header
is a log-injection vector. A malformed value is replaced silently rather than
rejected — a bad header should never fail a request for help.

**Logging configuration changed** so this works: the handler now sits on the
`backend` package logger rather than only `backend.main`, because every module
uses `logging.getLogger(__name__)` and was previously propagating to uvicorn's
root handler, which knows nothing about traces.

### Privacy fixes made while wiring this up

| Location | Was logging | Now |
|---|---|---|
| `situation_agent.py` | first 60 chars of `case_summary` — a paraphrase of the user's disclosure | category, urgency, counts |
| `maps_service.py` | the full resource query | resource type, flags, query length |
| `serpapi_service.py` | the cache key, which embeds the query | vertical, result count |

Verified live: two cases created with distinct disclosures, neither appears
anywhere in the server log.

---

## 5. Agent execution contracts

Seven of nine contracts already existed and were reused unchanged. Phase 2 added
only the two that were genuinely missing.

**`backend/models/agent_envelope.py`** — `AgentExecution`, `AgentStatus`,
`AgentError`.

The distinction that justifies it:

```
PROPOSED  → chosen, not yet run
ATTEMPTED → ran, did not succeed
COMPLETED → the requested effect actually took place
PARTIAL   → usable result, some sub-step degraded
UNAVAILABLE → dependency missing (no key, provider down)
SKIPPED   → deliberately not run
```

`ok` covers COMPLETED and PARTIAL. `did_complete` is COMPLETED only — check it
before telling a user something was done.

Deliberately lightweight: agents keep their signatures and return their existing
domain models. `AgentExecution.run` wraps a call; nothing inherits from
anything. `AgentError.reason` is a plain string so the existing
`SearchFailureReason` and `LLMUnavailableError.reason` vocabularies pass through
rather than being re-encoded.

---

## 6. Women-safety situation handling

`Situation` was extended, not replaced. **Every new field has a default**, so a
`Situation` stored before this phase still validates — asserted by
`test_situation_still_validates_without_the_new_fields`.

**New categories** (additive; all 21 pre-existing values keep their meaning):
`immediate_danger`, `street_harassment`, `unsafe_travel`, `campus_safety`,
`emotional_distress`, `safety_planning`, `local_discovery`.

**New fields:** `intent` (`SituationIntent`), `constraints`,
`recommended_workflow` (`SafetyWorkflow`), `immediate_danger_signals`.

### `backend/safety_triage.py` — deterministic, no LLM

This is the important design decision. Gemini's quota is currently exhausted; a
model can be rate-limited or retired at any time. A woman typing *"he is outside
my door right now"* must reach emergency guidance regardless. So triage is pure
regex and lookup tables: instant, offline, and unit-testable.

- **Conservative by construction.** Triage may only *raise* the urgency the
  model assigned, never lower it — asserted across all four urgency levels.
  Treating a safe situation as urgent costs a visible helpline she can ignore;
  the reverse cannot be undone.
- **Infers nothing.** Matching "he has a knife" marks danger and quotes the
  user's phrase; it does not add a fact or a constraint she did not state.
- **Raw text beats the summary.** `apply_triage_to_text` scans the original
  message, because a model's paraphrase is exactly where an urgent detail gets
  smoothed away ("he's outside with a knife" → "the user reports feeling
  unsafe").

Routing: critical urgency overrides every category and goes to the emergency
surface. 16 false-positive cases are tested to keep that surface meaningful.

**Emergency guidance does not require the chatbot.** `GET /api/v2/resources/national`
is public, unauthenticated and explicitly exempt from rate limiting — verified
live with 40 consecutive requests, all 200.

---

## 7. Legacy endpoint security decisions

Each of the 14 endpoints was classified rather than blanket-protected. The full
table is at the top of `backend/routes/legacy.py`.

| Class | Endpoints | Control | Auth added |
|---|---|---|---|
| LLM / paid | `/text-generation`, `/img-generation`, `/text-decomposition`, `/poem-generation`, `/generate-image`, `/find-match` | LLM budget (20 / 5 min) + input validation | no |
| Public submission | `/save-extracted-data` | Submission budget (10 / 5 min) | no |
| Public utility | `/encode`, `/decode` | Utility budget (30 / 5 min) | no |
| Public read | `/get-admin-posts`, `/get-post/{id}` | Read budget (120 / min) | no |
| External publish | `/send-message` | Submission budget | **yes** |
| Administrative | `/close-issue/{id}`, `/upload_embeddings/` | Submission / LLM budget | already had it |

**Why authentication was not added to the public ten.** Two reasons, and the
first is the product one: the community feed exists so a woman can read other
women's experiences and post her own *without creating an account that ties her
identity to a disclosure*. Anonymity is the feature. Second, five of the Next.js
proxies in front of these routes (`/api/decompose`, `/api/generate-text`,
`/api/generate-image`, `/api/getPosts`, `/api/save`) do not forward credentials,
so requiring auth would have broken the community and create-post flows outright.

The risk those routes actually carry is **cost and volume**, which a per-caller
budget addresses without a login wall.

**`/send-message` is the exception.** It publishes to a public Twitter account,
is unreachable from the current UI, and an open endpoint that posts externally
on a domestic-violence product is not defensible. It now requires an
authenticated identity. Verified live: `401`.

### Limits of the rate limiter — stated plainly

`backend/rate_limit.py` is in-process and in-memory:

- **Per worker.** With N uvicorn workers a caller effectively gets N× the budget.
- **Resets on restart.**
- **No defence against a distributed attacker.** It stops casual abuse and
  runaway clients; a real edge/WAF limit is still required in production.
- `X-Forwarded-For` is deliberately **not** trusted, since it is
  attacker-controlled without a known proxy in front.

Nothing carrying emergency information is limited: `/health` and
`/api/v2/resources/*` are exempt.

---

## 8. Tests performed

### Automated — all offline unless stated

| Suite | Result |
|---|---|
| **Backend total** | **315 passed**, 0 failed, 0 skipped (~47s) |
| ├─ pre-existing | 140 passed — unchanged, no modifications |
| ├─ `test_trace.py` | **39** new |
| ├─ `test_research_consolidation.py` | **15** new |
| ├─ `test_safety_triage.py` | **69** new |
| ├─ `test_legacy_security.py` | **20** new |
| ├─ `test_agent_envelope.py` | **16** new |
| └─ `test_chat_agent_phase2.py` | **16** new |
| Frontend `tsc --noEmit` | clean |
| Frontend `next lint` | clean |
| Frontend `next build` | succeeds, 23 pages |

**Regression method for Task 2:** the consolidation tests were written *before*
the refactor. Against the old `ResearchAgent` they ran **8 passed / 7 failed** —
the 8 being the compatibility surface both callers depend on, the 7 being the
defects consolidation fixes. After the refactor: **15 passed**. The 8 never
broke.

### Live, real-integration checks

These made real network calls and are labelled as such:

| Check | Result |
|---|---|
| **SerpApi through the consolidated path** | **REAL** — 1 billable search; 10 results, top hit `missionshakti.wcd.gov.in` (Government of India); `success=True`; trace `live-smoke-0001` propagated; budget 4 applied; `metrics.search_count=1` |
| Trace header round trip | valid ID echoed; `"evil injected value"` replaced with a fresh ID |
| Trace isolation in logs | 2 concurrent cases → 2 distinct prefixes |
| No user content in logs | two disclosures created; neither appears in the log |
| `/health` MongoDB truthfulness | now `integrations.mongodb = False` while `database = in-memory` |
| Rate limiting | `/poem-generation` → 429 with `Retry-After` after the budget |
| Emergency exemption | 40 consecutive `/api/v2/resources/national` → all 200 |
| `/send-message` auth | 401 unauthenticated |
| Input validation | `/text-decomposition` empty body → 422 |
| Case ownership | 4/4 cross-tenant requests → 403 |

### Not validated — stated honestly

- **Gemini**: quota exhausted. Every LLM-dependent path is mock-tested only.
  No live situation analysis, chat reply, safety plan or action plan was
  produced in this phase.
- **MongoDB**: unreachable. All persistence ran on the in-memory fallback.
- **Atlas vector search**: no cluster. Legal RAG remains unverifiable.
- **Clerk**: not configured. The authenticated branch of `/send-message`,
  `/close-issue` and `/dashboard` is tested only for its 401 path. **The
  success path of any authenticated flow is unverified.**

---

## 9. Files changed

**New (8)**

```
backend/trace.py                              request-scoped trace IDs
backend/safety_triage.py                      deterministic urgency + routing
backend/rate_limit.py                         abuse controls
backend/models/agent_envelope.py              agent execution envelope
backend/tests/test_trace.py                   39 tests
backend/tests/test_research_consolidation.py  15 tests
backend/tests/test_safety_triage.py           69 tests
backend/tests/test_legacy_security.py         20 tests
backend/tests/test_agent_envelope.py          16 tests
backend/tests/test_chat_agent_phase2.py       16 tests
docs/PHASE2_IMPLEMENTATION_REPORT.md          this document
```

**Modified (10)**

```
backend/main.py                   trace middleware; package-level log handler
backend/logger.py                 trace ID in every line, read defensively
backend/agents/research_agent.py  rewritten as a delegate (interface preserved)
backend/agents/chat_agent.py      tool dispatch extracted + isolated; logging
backend/agents/situation_agent.py triage applied; prompt extended; log privacy
backend/models/research.py        7 categories, 4 fields, 2 enums — all additive
backend/routes/chat.py            trace_id on ChatResponse
backend/routes/legacy.py          security policy: limits, validation, 1 auth
backend/services/maps_service.py  stopped logging raw queries
backend/services/serpapi_service.py stopped logging the cache key
frontend/src/lib/types.ts         optional trace_id on ChatReply
```

**Deleted: 0. Features removed: 0. Endpoints removed: 0.**

---

## 10. Issues from Phase 1 resolved here

| ID | Issue | Status |
|---|---|---|
| A-01 | Duplicate research implementations | **Resolved** — one canonical path |
| A-02 | No trace/correlation ID | **Resolved** |
| A-03 | No uniform agent envelope | **Resolved** |
| S-02 | No rate limiting | **Partly** — in-process; needs a shared backend |
| S-03 | Unauthenticated Twitter publish | **Resolved** |
| S-04 | Raw queries in logs | **Resolved**, plus a fourth leak found in `situation_agent.py` |
| S-01 | 12 unauthenticated legacy endpoints | **Policy set and tested**; 10 remain public by decision |
| B-02 | Legal RAG `[]` ambiguity | **Documented and logged**, not fixed — needs the contract change in §11 |

---

## 11. Remaining blockers

1. **No Atlas cluster** (C-02). Legal RAG stays broken: vectors are stored as
   pickled `Binary`, which `$vectorSearch` cannot index, and the legal
   collection has no index. Unchanged from Phase 1 — repairing it by inventing a
   substitute was explicitly out of scope.
2. **Gemini quota** (C-03). No LLM-dependent behaviour has been verified live in
   either phase.
3. **No MongoDB** (C-01). Persistence remains unproven.
4. **No Clerk project** (C-04). No authenticated flow has a verified success path.
5. **Rate limiting is per-process** (A-05). Shares a root cause with the SerpApi
   cache; both want the same shared backend.
6. **No CI** (C-05). 315 tests, nothing runs them automatically.

---

## 12. Recommended starting point for Phase 3

Phase 3 is *SerpApi-powered research and local intelligence*. The foundation it
needs now exists: one research path, a trace ID through it, and a live-verified
SerpApi integration.

**Start with the shared cache** (`A-05`) in `backend/services/serpapi_service.py`,
behind the existing `SerpApiCache` interface. Reasons it comes first:

- It is the only Phase 3 prerequisite that is purely infrastructural — no
  product decision is blocked on it.
- `backend/rate_limit.py` has the same per-process limitation and the same fix,
  so one backend serves both.
- Every subsequent Phase 3 task increases search volume. Doing it after means
  paying for the duplicates twice over.

Keep the live fixtures from this phase as regression checks for result quality:
`"One Stop Centre Sakhi Nagpur official"` should keep returning a
`missionshakti.wcd.gov.in` result at the top.

Then `backend/services/resource_resolver.py` as planned in
[`INTEGRATION_ROADMAP.md`](INTEGRATION_ROADMAP.md) — now able to use
`SafetyWorkflow.LOCAL_RESOURCES` as its routing trigger.
