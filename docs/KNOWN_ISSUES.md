# HerWay — Known Issues

Recorded during the Phase 1 audit (2026-10-01). Evidence and reasoning live in
[`EXISTING_ARCHITECTURE_AUDIT.md`](EXISTING_ARCHITECTURE_AUDIT.md); this file is
the actionable register.

**Priority:** P0 blocks production · P1 fix before launch · P2 fix when touched
· P3 cleanup.

> **Phase 2 update (2026-10-01).** A-01, A-02, A-03, S-03 and S-04 are resolved;
> S-01 now has a tested policy and S-02 a partial control. Statuses below are
> annotated inline. Evidence is in
> [`PHASE2_IMPLEMENTATION_REPORT.md`](PHASE2_IMPLEMENTATION_REPORT.md).
> The Phase 1 findings themselves are left as written.

---

## Confirmed bugs

| ID | Issue | Priority | Phase | Status |
|---|---|---|---|---|
| B-01 | **Legal RAG stores vectors as `Binary(pickle.dumps(...))`.** Atlas `$vectorSearch` cannot index a pickled blob, so LawBot retrieval can never return a document. Requires re-ingesting `doc_embedding` as plain float arrays plus a matching Atlas index. | **P0** | 2 | Open |
| B-02 | **`search_legal_docs` returns `[]` on every failure.** Caller cannot distinguish "no relevant law" from "retrieval down" — a legal assistant may then answer from model memory and invent section numbers. Needs an explicit outcome type (mirroring `SearchOutcome`/`SearchFailureReason`). | **P0** | 2 | Still open after Phase 2 — logged and documented, contract unchanged |
| B-03 | **Retired embedding model `text-embedding-004` (404).** Broke legal retrieval *and* community culprit matching. | P0 | 1 | **Fixed** — `gemini-embedding-001` @ 768 dims, verified with a real call |
| B-04 | **`find_top_matches` hardcoded `path="culprit_embedding"`** while legal docs store under `embedding`. | P1 | 1 | **Fixed** — now a parameter; community default unchanged |
| B-05 | **`/api/closeIssue` forwarded no credentials**, so moderation always 401'd and surfaced as an opaque 500. | P1 | 1 | **Fixed** — forwards cookie + Clerk token, preserves upstream status |
| B-06 | **`/health` reported `mongodb: true` for a set-but-unreachable URI**, while actually serving from the in-memory store. | P1 | 1 | **Fixed** — derived from real connection state |
| B-07 | **Clerk placeholder keys caused `host_invalid` on every request.** | P1 | 1 | **Fixed** — `clerk-config.ts` detects and falls back |
| B-08 | **`/dashboard` threw `ReferenceError: document is not defined`** during SSR on every request (lottie-web at module scope). | P2 | 1 | **Fixed** — `LiveIcon` loaded with `ssr: false` |

---

## Security and privacy issues

| ID | Issue | Priority | Phase |
|---|---|---|---|
| S-01 | **12 of 14 legacy endpoints are unauthenticated.** Verified: `GET /get-admin-posts` → 200 with no cookie. Includes five LLM-invoking endpoints (anyone can exhaust the Gemini quota) and `/save-extracted-data`, which writes to the database. Add `get_identity`/`require_authenticated` per endpoint, preserving the response contract. | **P0** | 7 | **POLICY SET (Phase 2)** — classified + rate limited + validated; 10 remain public by decision |
| S-02 | **No rate limiting anywhere.** With S-01, one visitor can exhaust the API budget for every real user. | **P0** | 7 | **PARTIAL (Phase 2)** — `backend/rate_limit.py`, in-process only |
| S-03 | **`POST /send-message` publishes to Twitter with no authentication.** Not reachable from the UI; still exposed. Either gate it or remove the route (keep `utils/twitter.py`). | **P0** | 7 | **RESOLVED (Phase 2)** — now requires authentication |
| S-04 | **Raw search queries are logged.** `maps_service.py:197` and the cache-hit line in `serpapi_service.py:152` include query text derived from user situation text — a log line can reveal that an identifiable session is seeking DV help. The structured `SerpApiLog` already does this correctly (`query_length` only); make the other two match. | P1 | 7 | **RESOLVED (Phase 2)** — plus a fourth leak fixed in `situation_agent.py` |
| S-05 | **`NEXT_PUBLIC_OPENCAGE_API_KEY` would ship a key to the browser** and send precise coordinates to a third party without passing through the server (`frontend/src/lib/utils.ts:12`). Currently dead code and the variable is unset. Delete the helper or route it through the backend, which already has a server-side `OPENCAGE_API_KEY`. | P1 | 6 |
| S-06 | **No audit trail on moderation.** `/close-issue` records no actor or timestamp, so there is no record of who actioned a report. | P2 | 5 |

---

## Incomplete integrations

| ID | Issue | Priority | Phase |
|---|---|---|---|
| I-01 | **India resource registry is never surfaced.** `/api/v2/resources/national` (7 attributed helplines, each with `official_source_url`) and `/regions` (36) are not called by any page. Meanwhile 8 frontend files hardcode `112`/`181` with no attribution, and `lib/india.ts` duplicates the states list. Two sources of truth that will drift. | P1 | 6 |
| I-02 | **MongoDB persistence never verified.** All testing ran in-memory. No create→restart→reload cycle has been performed. | **P0** | 7 |
| I-03 | **Clerk sign-in never verified.** No project configured, so the authenticated path (including `/dashboard` and the now-fixed close-issue flow) is untested end-to-end. | P1 | 7 |
| I-04 | **No real integration test exists.** All 140 backend tests are offline/mocked. A green suite does not demonstrate that Gemini, SerpApi, MongoDB or Atlas work. | P1 | 7 |
| I-05 | **`ActionPlanner` has one test.** Thinnest coverage of any agent, for a component that produces user-facing instructions. | P1 | 4 |
| I-06 | **Community `find-match` depends on the same broken vector search as B-01.** It has a recency fallback, so it degrades rather than failing — but it is not doing similarity matching. | P2 | 6 |

---

## Architectural risks

| ID | Issue | Priority | Phase |
|---|---|---|---|
| A-01 | **Duplicate research implementations.** `ResearchAgent` (chat + cases routes) and `ResearchOrchestrator` (research route) both plan and execute search with different budgeting, caching and quality behaviour. The same case researched two ways behaves differently. Consolidate onto `ResearchOrchestrator`. | **P0** | 2 | **RESOLVED (Phase 2)** — `ResearchOrchestrator` canonical; `ResearchAgent` is a delegate |
| A-02 | **No trace/correlation ID anywhere.** Verified by grep: no `trace_id`, `request_id` or `correlation_id` in the codebase. A multi-agent pipeline cannot be debugged without one, and it is a prerequisite for the error contract. | **P0** | 2 | **RESOLVED (Phase 2)** — `backend/trace.py` |
| A-03 | **No uniform agent invocation envelope.** Each agent has an ad-hoc signature; `ToolCallChoice` covers tool dispatch only. | P1 | 2 | **RESOLVED (Phase 2)** — `backend/models/agent_envelope.py` |
| A-04 | **Two parallel frontend proxy layers.** The generic `/api/v2/[...path]` proxy is correct; seven hand-written legacy routes each re-implement proxying with varying quality. B-05 was caused by exactly this. | P1 | 6 |
| A-05 | **SerpApi cache is per-process.** In-memory dict: multi-worker deployments bill once per worker, and a restart clears it. Needs a shared cache before horizontal scaling. | P1 | 7 |
| A-06 | **`google-generativeai` is formally deprecated** and prints an end-of-support notice on import. Two model retirements have already broken this app. Migrate to `google-genai`. | P1 | 7 |
| A-07 | **In-memory DB fallback diverges from MongoDB.** `_InMemoryCollection` implements no `aggregate()`, so any aggregation path is untestable locally and will only fail in a real deployment. | P2 | 7 |
| A-08 | **`/health` does not probe liveness.** It reports whether integrations are *configured* (now correct for MongoDB), not whether Gemini/SerpApi actually answer. | P2 | 7 |

---

## Missing configuration and infrastructure

| ID | Item | Priority | Phase |
|---|---|---|---|
| C-01 | No reachable MongoDB instance | **P0** | 7 |
| C-02 | No Atlas vector indexes — `culpritIndex2` (community) and a legal-document index (B-01) | **P0** | 2 |
| C-03 | Gemini free-tier quota exhausted (~20 req/day; one full case uses 5–8), blocking all live LLM verification | **P0** | 7 |
| C-04 | No Clerk project | P1 | 7 |
| C-05 | **No CI.** Nothing runs the 140 tests automatically. | P1 | 7 |
| C-06 | No deployment config — no Dockerfile, compose, or platform manifest | P1 | 7 |
| C-07 | No `LICENSE` file, though README and badge claim MIT | P2 | 7 |
| C-08 | 13 env vars were undocumented | P2 | 1 | **Fixed** — added to `.env.example` |

---

## Product-safety items to preserve

These are **working as intended** and must not regress. Listed because they are
easy to undo accidentally.

| Behaviour | Where |
|---|---|
| LLM outage returns 429/503 with a helpline, never a fabricated answer | `llm_service.py` `_classify_api_error` |
| Steganography is described as *not encryption*, with compression warning | `routes/discreet.py` `LIMITATIONS` |
| Resources carry three-state provenance, never a blanket "verified" badge | `models/safety_plan.py` `ResourceVerification` |
| Community posts are PII-stripped server-side | `routes/legacy.py` `_PRIVATE_POST_FIELDS` |
| Search queries are PII-scrubbed before leaving the server | `research_orchestrator.py` `sanitize_search_query` |
| Production refuses the volatile in-memory store | `db.py` `_is_production` |
| An invalid Clerk token 401s instead of downgrading to anonymous | `auth.py` |
| `/dashboard` requires an allow-list, not self-assigned metadata | `app/dashboard/page.tsx` |
| Helpline numbers are never invented; unverified resources are labelled | `india_resources.py` |

---

## Suggested order of work

**Before anything else (P0):**
1. A-01 consolidate research · A-02 trace IDs — these shape every later phase
2. B-01 + B-02 + C-02 repair legal RAG — currently shipping a legal assistant with no retrieval
3. S-01 + S-02 + S-03 close the unauthenticated surface
4. I-02 + C-01 + C-03 prove persistence and obtain real quota

**Then (P1):** A-03 · I-01 · I-04 · I-05 · S-04 · S-05 · A-04 · A-05 · A-06 ·
C-04 · C-05 · C-06
