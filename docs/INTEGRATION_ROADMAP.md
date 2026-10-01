# HerWay — Integration Roadmap (Phases 2–7)

Derived from the Phase 1 audit. Every file named here was verified to exist at
the time of writing. Issue IDs (`A-01`, `B-02`, …) refer to
[`KNOWN_ISSUES.md`](KNOWN_ISSUES.md).

**Standing constraints for all phases:** do not rebuild the application · do not
delete working features · preserve API compatibility unless a demonstrated
problem requires a change · no duplicate implementations · no new database or
agent framework without a concrete technical reason · keep LawBot, TherapyBot,
community, cases and discreet messaging as standalone experiences · government
and NGO resources stay *optional support*, never a hard dependency of a core
flow · no fake safety guarantees, ride-booking claims or emergency-delivery
claims.

---

## Phase 2 — Unified orchestration and women-safety domain integration

**Goal:** one research path, one agent envelope, one trace ID — and a legal
assistant whose retrieval actually works. No new capabilities.

### Reuse as-is
| File | Why |
|---|---|
| `backend/agents/chat_agent.py` | Already the orchestrator; 12 tools wrapping every legacy capability. **This is the integration point — extend it, do not replace it.** |
| `backend/agents/situation_agent.py` + `Situation` | Shared context object; already carries facts/claims/unknowns |
| `backend/agents/source_verifier.py`, `action_planner.py`, `safety_plan_agent.py` | Correct responsibilities, no overlap |
| `backend/services/serpapi_service.py` | Real integration verified working |
| `backend/india_resources.py` | Tier model and attribution |
| `backend/models/*.py` | 7 of 9 required contracts already exist |

### Modify
| File | Change |
|---|---|
| `backend/services/research_orchestrator.py` | Becomes the **single** research entry point |
| `backend/agents/research_agent.py` | **Do not delete.** Reduce to a thin delegating wrapper so `chat_agent.py:576` and `routes/cases.py:409` keep working (A-01) |
| `backend/routes/chat.py`, `cases.py`, `research.py` | Route through the orchestrator; accept and return a trace ID |
| `backend/services/embedding_service.py` | Return an explicit outcome instead of `[]` (B-02) |
| `backend/db.py` | `upload_embeddings_to_mongo` must store plain float arrays, not pickled `Binary` (B-01) |
| `backend/main.py` | Trace-ID middleware |

### New modules (genuinely required)
- `backend/models/agent_io.py` — `AgentRequest` / `AgentResponse` envelope with
  `trace_id`, `agent_name`, `degradations: list[ResearchDegradation]`,
  `error: AgentError | None` (A-03). Wrap existing agents; do not rewrite them.
- `backend/trace.py` — request-scoped trace ID via `contextvars`, surfaced in
  every log line and error body (A-02).
- `backend/models/errors.py` — one error envelope generalising the existing
  `SearchFailureReason` / `LLMUnavailableError` / `ResearchDegradation`.
- A re-ingestion script for `doc_embedding` (B-01) + documented Atlas index
  definition (C-02).

### Prerequisites
Atlas cluster with both vector indexes · Gemini key with real quota (C-03).

### Regression risks
- Collapsing two research paths changes chat behaviour — chat currently uses the
  *simpler* `ResearchAgent`, so budget enforcement will newly apply. Snapshot
  current chat responses first.
- Changing `upload_embeddings_to_mongo`'s storage format invalidates any
  existing `doc_embedding` documents. **Re-ingestion is mandatory, not
  optional.**
- `gemini-embedding-001` is pinned to 768 dims to match `culpritIndex2`.
  Changing dimensions requires rebuilding both indexes.

### Acceptance criteria
1. `ResearchOrchestrator` is the only component issuing SerpApi research;
   `ResearchAgent` delegates and its public signature is unchanged.
2. Identical input via `/api/v2/chat` and `/api/v2/research/{id}/run` produces
   the same search budget and caching behaviour.
3. Every response and log line carries the same `trace_id`.
4. `search_legal_docs` returns a distinguishable "unavailable" vs "no results",
   and **ChatAgent refuses to answer a legal question from model memory when
   retrieval is unavailable** — asserted by a test.
5. A real Atlas query returns ≥1 legal document for a known statute.
6. All 140 existing tests still pass; no endpoint removed; no frontend change
   required.

---

## Phase 3 — SerpApi-powered research and local intelligence

**Goal:** better local resource discovery and provenance. The integration
already works; this is depth.

### Reuse
`services/serpapi_service.py` (cache, failure taxonomy, `_mentions_india`) ·
`services/maps_service.py` · `agents/source_verifier.py` ·
`india_resources.py` (`SourceTier`, `TIER_AUTHORITY`) ·
`models/research.py` (`SearchOutcome`, `ResourceVerification`)

### Modify
| File | Change |
|---|---|
| `services/serpapi_service.py` | Shared cache behind the existing `SerpApiCache` interface (A-05) |
| `services/maps_service.py` | Stop logging raw queries (S-04); richer `SafetyMatchedResource` population |
| `agents/source_verifier.py` | Promote state-government `.gov.in` subdomains; strengthen contradiction handling |

### New
- `backend/services/resource_resolver.py` — resolves a state/district to
  official One Stop Centre / Mahila Thana / DLSA listings, **always** returning
  a `ResourceVerification` level and a source URL.

### Prerequisites
Phase 2 trace IDs · SerpApi credits · a decision on the shared cache backend
(no new database without justification — reuse MongoDB with a TTL index unless
a real reason emerges).

### Regression risks
Query scoping changes can regress result quality; keep the live fixtures from
the audit (`"One Stop Centre Sakhi Nagpur"`, `"women helpline 181 India
official"`) as regression checks. A shared cache introduces a new failure mode —
it must degrade to the in-process cache, not error.

### Acceptance criteria
1. No raw user query appears in any log at INFO or above.
2. Every surfaced resource carries a verification level and a source URL; an
   unverified Maps listing is never labelled official.
3. Cache hit rate measurable and shared across workers.
4. A location with no coverage returns an honest "nothing verified found", never
   a fabricated listing.

---

## Phase 4 — Actionable workflows and persistent Safety Center

**Goal:** make plans durable and trackable. Models already exist.

### Reuse
`agents/safety_plan_agent.py` · `agents/action_planner.py` ·
`models/safety_plan.py` · `models/action_plan.py` ·
`routes/cases.py` safety-plan endpoints (already ownership-checked) ·
`frontend/src/app/cases/[id]/page.tsx` · `components/ResourceCard.tsx`,
`EvidenceCard.tsx`, `Timeline.tsx`

### Modify
| File | Change |
|---|---|
| `routes/cases.py` | Surface `GET .../safety-plan` and `PATCH .../safety-plan/actions/{id}` in the UI (currently unused — audit §5.5) |
| `frontend/src/app/cases/[id]/page.tsx` | Action status transitions against the server, not local state |
| `models/safety_plan.py` | Add `updated_at` per action for progress history |

### New
- `frontend/src/app/safety-center/page.tsx` — cross-case view of outstanding
  actions. **Additive**; `/cases` and `/cases/[id]` stay exactly as they are.

### Prerequisites
**Working MongoDB persistence (I-02) — a Safety Center on a volatile store is
worse than none.**

### Regression risks
`ActionPlanner` has a single test (I-05); add coverage *before* changing it.
Adding fields to `SafetyPlan` must stay backward-compatible with stored
documents — `ResourceVerification` already demonstrates the compatible-property
pattern.

### Acceptance criteria
1. Create a plan → restart the backend → the plan and every action status
   reload intact **from MongoDB**.
2. Action status changes survive a page reload.
3. `ActionPlanner` coverage raised to a meaningful level.
4. No existing case endpoint changes shape.

---

## Phase 5 — Incident workspace and private evidence management

**Goal:** let a user keep a private, structured record. Highest privacy
sensitivity in the project.

### Reuse
`backend/auth.py` (`assert_case_owner`) · `routes/cases.py` ownership pattern ·
`models/case.py` · `components/EvidenceCard.tsx`, `Timeline.tsx` ·
`services/report_service.py` · `utils/steganography.py`

### Modify
| File | Change |
|---|---|
| `models/case.py` | Evidence entries attached to a case |
| `routes/cases.py` | Evidence CRUD **on the existing `_load_owned_case` path** |
| `routes/legacy.py` | Moderation audit trail: actor + timestamp (S-06) |

### New
- `backend/models/evidence.py` — evidence item with timestamp, type, optional
  file reference, user-entered notes.
- `backend/services/evidence_store.py` — storage abstraction.

### Prerequisites
Phase 4 persistence · a documented decision on file storage (S3 already used for
community images) · **an explicit retention and deletion policy, written before
code.**

### Regression risks
**Highest-risk phase in the roadmap.** Evidence may be the only record of abuse
*and* dangerous if exposed. Deletion must be real, not a soft flag. File uploads
are a new attack surface (type, size, content validation). Do not weaken
`assert_case_owner` to accommodate sharing.

### Acceptance criteria
1. Cross-tenant evidence access returns 403 — tested exactly as the audit's
   7-endpoint matrix.
2. Deleting a case provably removes its evidence, including stored files.
3. No evidence content appears in any log.
4. `/privacy` is updated to state truthfully what this does and does not
   protect against.

---

## Phase 6 — Existing support features and everyday utility integration

**Goal:** connect what already exists. Mostly deletion of duplication.

### Reuse
`frontend/src/app/lawbot/`, `therapybot/`, `community/`, `discreet-message/`,
`create-post/`, `post/[id]/` · `components/HavenAvatar.tsx` ·
`src/app/api/v2/[...path]/route.ts` · `routes/resources.py`

### Modify
| File | Change |
|---|---|
| 8 frontend files hardcoding `112`/`181` | Consume `/api/v2/resources/national` so numbers carry attribution and one source of truth (I-01) |
| `frontend/src/lib/india.ts` | Source the states list from `/api/v2/resources/regions`, or make it an explicit cache of it |
| `src/app/api/{chat,getPosts,save,decompose,generate-text,generate-image,postbyid}` | Migrate onto the generic proxy pattern (A-04) |
| `frontend/src/lib/utils.ts` | Remove the browser-side OpenCage call (S-05) |

### New
Little should be needed. Possibly one `useResources()` hook.

### Prerequisites
None beyond Phase 2.

### Regression risks
Moving helplines from hardcoded to fetched introduces a **network dependency on
emergency numbers** — the UI must keep a static fallback so `112` and `181` are
visible even if the API is down. This is the one place where a hardcoded value
is correct; the goal is attribution, not removing the safety net.

### Acceptance criteria
1. Helpline numbers render with their source, and still render when the backend
   is unreachable.
2. Every legacy Next API route forwards credentials and preserves upstream
   status.
3. LawBot, TherapyBot, community, create-post and discreet messaging all remain
   reachable as standalone pages.
4. No `NEXT_PUBLIC_*` variable holds a credential.

---

## Phase 7 — End-to-end testing, privacy, reliability and production readiness

**Goal:** earn the phrase "production ready". **Nothing here may be claimed
without test evidence.**

### Reuse
All 10 existing test modules (140 tests) · `/health` · `db.py` production
guards · `auth.py` `startup_auth_check`

### Modify
| File | Change |
|---|---|
| `routes/legacy.py` | Authentication on the 12 unauthenticated endpoints (S-01); gate or remove `/send-message` (S-03) |
| `main.py` | Rate limiting (S-02); `/health` probes real liveness (A-08) |
| `requirements.txt` | Migrate `google-generativeai` → `google-genai` (A-06) |
| `services/serpapi_service.py`, `maps_service.py` | Final log audit (S-04) |

### New
- `.github/workflows/ci.yml` — pytest + tsc + lint + build on every push (C-05).
- `backend/tests/test_integration_live.py` — **real** integration tests, opt-in
  behind an env flag, clearly separated from the 140 mocked tests (I-04).
- `backend/middleware/rate_limit.py`.
- `Dockerfile` / compose (C-06) · `LICENSE` (C-07).

### Prerequisites
Real MongoDB · Atlas indexes · funded Gemini key · Clerk project.

### Regression risks
Adding authentication to legacy endpoints **will break any unauthenticated
client**, including the community page — stage it and verify each flow. Rate
limiting must never block a genuine emergency: emergency-resource reads should
be exempt or generously limited.

### Acceptance criteria
1. CI green on every push; mocked and live suites reported separately.
2. Zero unauthenticated endpoints that invoke an LLM or write to the database.
3. A create→restart→reload cycle verified **against real MongoDB**.
4. Flows A–G re-run against real integrations, with results recorded and
   failures stated plainly.
5. `/health` reflects actual liveness.
6. No user content in logs at INFO or above.
7. A documented, tested deployment path.

---

## Cross-phase: what must not regress

Carry the "product-safety items to preserve" table from
[`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) into every phase's review. In particular,
no phase may introduce:

- a fabricated answer when a model or search is unavailable,
- a resource presented as verified without a source,
- a safety guarantee the software cannot keep,
- an invented law, section number or court procedure,
- a claim that Quick Exit guarantees digital safety,
- any suggestion that the user confront an abuser.
