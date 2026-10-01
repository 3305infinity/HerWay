# HerWay — Existing Architecture Audit

**Phase 1 deliverable.** Audit date: 2026-10-01. Method: repository-wide
inspection, following actual imports and execution paths, plus live probes
against a running backend (`localhost:8000`) and frontend (`localhost:3000`).

> **This document records the state at the end of Phase 1 and is kept as
> written.** Phase 2 has since resolved several findings — notably the duplicate
> research implementations (§6.1), the missing trace ID and agent envelope (§8),
> and parts of the legacy endpoint exposure (§7). See
> [`PHASE2_IMPLEMENTATION_REPORT.md`](PHASE2_IMPLEMENTATION_REPORT.md) for what
> changed and [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) for current status. The
> unverified integrations listed here — MongoDB, Clerk, Atlas vector search and
> live Gemini — remain unverified.

Nothing below is marked working because a file or route exists. Every status is
backed by evidence recorded in this document, and anything that could not be
exercised in this environment is marked **UNVERIFIED** with the reason.

---

## 1. Repository shape

```
Haven-main/
├── backend/              FastAPI, 13,126 lines of Python (excl. tests/venv)
├── frontend/             Next.js 15.0.2 App Router, React 19, TypeScript
├── ai-avatar/            Separate sub-project (ai-avatar-backend, -frontend)
├── docs/                 ← created by this audit
├── README.md             Setup and API reference
├── ARCHITECTURE.md       Pre-existing design notes
├── VALIDATION_REPORT.md  Prior reliability pass
└── WOMEN_SAFETY_AUDIT.md Pre-existing safety review
```

**Not present:** no CI configuration (`.github/workflows`), no `Dockerfile`,
no `docker-compose`, no `vercel.json`/`render.yaml`/`Procfile`. Deployment is
entirely manual and undocumented beyond the README.

`ai-avatar/` is a self-contained sub-project and was **not** audited in depth;
it is not imported by `backend/` or `frontend/`.

---

## 2. Backend architecture

### 2.1 Composition

`backend/main.py` builds a single FastAPI app (`version 2.1.0`) and mounts six
routers. There are **35 HTTP operations** total, in two generations:

| Router | Mount | Operations | Generation |
|---|---|---|---|
| `routes/legacy.py` | `/` (root) | 14 | Original Haven |
| `routes/cases.py` | `/api/v2/cases` | 11 | v2 |
| `routes/research.py` | `/api/v2/research` | 3 | v2 |
| `routes/chat.py` | `/api/v2/chat` | 1 | v2 |
| `routes/discreet.py` | `/api/v2/discreet` | 3 | v2 |
| `routes/resources.py` | `/api/v2/resources` | 2 | v2 |
| (app) | `/health` | 1 | — |

Cross-cutting middleware:
- **CORS** with `allow_credentials=True` and an explicit origin list (no
  wildcard — correct, since the session cookie is sent).
- **`catch_unhandled_errors`** converts any uncaught exception into a plain
  JSON 500 rather than an HTML traceback, so case contents and file paths
  cannot leak through an error page.
- **`startup_auth_check()`** refuses to boot on an unsafe production auth
  configuration.

### 2.2 Agents

Six agents under `backend/agents/`. Responsibilities as actually implemented:

| Agent | File | Lines | Responsibility |
|---|---|---|---|
| `SituationAgent` | `situation_agent.py` | 93 | Natural language → structured `Situation` (category, urgency, goal, facts/claims/unknowns) |
| `ChatAgent` | `chat_agent.py` | 907 | **Tool-calling orchestrator.** 12 tools; the central routing brain |
| `ResearchAgent` | `research_agent.py` | 210 | Plans + concurrently executes SerpApi research |
| `SourceVerifier` | `source_verifier.py` | 302 | Search results → `EvidenceItem`s with authority tiers and contradictions |
| `ActionPlanner` | `action_planner.py` | 140 | Evidence → structured `ActionPlan` |
| `SafetyPlanAgent` | `safety_plan_agent.py` | 496 | Women-safety branch: `SafetyPlan` with phased actions and matched resources |

**`ChatAgent` is the single most important file for Phase 2.** It already
implements the "orchestrate, don't replace" pattern the project requires: the
original Haven capabilities are exposed to the LLM as callable tools rather
than being bypassed.

Its 12 tools:

| Tool | Wraps |
|---|---|
| `answer_user` | Terminal response with source IDs/URLs |
| `search_web` / `search_news` / `search_local` | `SerpApiService` verticals |
| `search_safety_resources` | Safety-specific resource discovery |
| `update_action_status` | Safety-plan action state |
| `adapt_safety_plan` | `SafetyPlanAgent` re-planning |
| `invoke_lawbot` | **Legal RAG** (`EmbeddingService.search_legal_docs`) |
| `search_community` | **Community posts** (`EmbeddingService.search_community_posts`) |
| `encode_message` | **Steganography** |
| `generate_formal_report` | `ReportService` |
| `generate_poem` | Legacy poem generation |

### 2.3 Services

| Service | File | Role |
|---|---|---|
| `LLMService` | `llm_service.py` | Gemini wrapper. `generate`, `structured_generate`, `chat`. Pushes the blocking SDK to `asyncio.to_thread`; classifies errors into `LLMUnavailableError(reason=...)` |
| `SerpApiService` | `serpapi_service.py` | SerpApi client, 4 verticals, in-process TTL cache, structured logging, explicit `SearchFailureReason` taxonomy |
| `ResearchOrchestrator` | `research_orchestrator.py` | Budgeted, iterative research with quality loops and contradiction resolution |
| `EmbeddingService` | `embedding_service.py` | Wrapper over the legacy RAG utilities |
| `MapsService` | `maps_service.py` | Local resource discovery via SerpApi Maps |
| `NewsService` | `news_service.py` | News vertical helper |
| `ReportService` | `report_service.py` | Formal report drafting (Gemini, optionally Groq second opinion) |
| `StegService` | `steganography_service.py` | Encode/decode wrapper |

### 2.4 Data contracts

Pydantic v2 models in `backend/models/`. **Most of the contracts a unified
orchestration layer needs already exist** — see §8.

- `research.py` — `Situation`, `Urgency`, `SituationCategory`, `SearchRequest`,
  `SearchResult`, `SearchOutcome`, `SearchFailureReason`, `ResearchPlan`,
  `ResearchTask`, `ResearchTraceEntry`, `ResearchExecutionResult`,
  `EvidenceItem`, `EvidenceStatus`, `EvidenceConfidence`, `Contradiction`,
  `SourceType`, `ResourceVerification`, `ResearchDegradation`.
  Locale defaults are India-first: `DEFAULT_COUNTRY = "in"`.
- `case.py` — `Case`, `CaseCreate`, `CaseUpdate`, `CaseStatus`, `CaseCategory`,
  `Location`, `ensure_case_indexes`.
- `action_plan.py` — `ActionPlan`, `ActionItem`, `ActionPriority`,
  `ActionStatus`, `ActionTimingPhase`, `ActionType`.
- `safety_plan.py` — `SafetyPlan`, `SafetyActionItem`, `SafetyAssessment`,
  `SafetyMatchedResource`, `SafetyPlanPhase`, `SafetyPlanUpdate`.

### 2.5 Persistence

`backend/db.py`. MongoDB via PyMongo, with a **full in-memory fallback**
(`_InMemoryDatabase`, `_InMemoryCollection`, `_InMemoryCursor`) implementing
`insert_one`, `find`, `find_one`, `update_one`, `delete_one`,
`count_documents`, `create_index`.

Two deliberate safety properties, both verified by reading the code:
- The fallback is **refused** when `HERWAY_ENV=production` — it raises rather
  than silently losing a saved safety plan.
- `database_mode()` exposes which store is live, surfaced on `/health`.

The in-memory collection does **not** implement `aggregate()` (verified:
`hasattr(db['doc_embedding'], 'aggregate') == False`), so Atlas
`$vectorSearch` cannot work in fallback mode. This is correct behaviour but
means RAG is untestable without a real Atlas cluster.

Collections in use: `SheBuilds.cases`, `.admin` (community posts),
`.complains2`, `.doc_embedding`.

### 2.6 Authentication and authorization

`backend/auth.py`:
- `Identity(subject, kind)` where `kind ∈ {"clerk", "anonymous"}`.
- Clerk session tokens verified RS256 against JWKS. **A presented-but-invalid
  token raises 401 rather than silently downgrading to anonymous** — the right
  choice.
- Anonymous visitors get a signed, httpOnly, `SameSite=lax` cookie
  (`herway_sid`, Max-Age 15552000) so their cases are isolated per browser.
- `assert_case_owner(case_doc, identity)` → 403 on mismatch.
- `require_authenticated` dependency for endpoints that need a real account.

**No endpoint accepts a caller-supplied `user_id`.** Verified by inspection of
`CaseCreate` (which documents the omission explicitly) and by the live
isolation test in §5.2.

---

## 3. Frontend architecture

Next.js 15.0.2 App Router, React 19, TypeScript, Tailwind, Radix UI, Clerk,
Three.js.

### 3.1 Pages (11 user-facing)

| Route | Purpose | Backend it uses |
|---|---|---|
| `/` | Landing + situation intake | `/api/v2/cases`, `/api/v2/cases/analyze` |
| `/cases` | Case list | `/api/v2/cases?limit=100` |
| `/cases/[id]` | Case workspace: plan, research trail, safety plan, chat | `/api/v2/cases/{id}`, `.../actions/{id}`, `.../safety-plan/research-more`, `/api/v2/research/{id}/run`, `/api/v2/chat` |
| `/lawbot` | Standalone legal assistant | `/api/v2/chat` with `mode: 'legal'` |
| `/therapybot` | Niva emotional support + 3D avatar | `/api/v2/chat` with `mode: 'therapy'` |
| `/community` | Anonymous community posts | `/api/getPosts` → `/get-admin-posts` |
| `/post/[id]` | Community post detail | `/api/postbyid/[id]` → `/get-post/{id}` |
| `/create-post` | Community post composer | `/api/save`, `/api/generate-image` |
| `/dashboard` | Responder moderation queue | `/api/getPosts`, `/api/closeIssue` |
| `/discreet-message` | Steganography studio | `/api/v2/discreet/*` |
| `/privacy` | Honest limitations statement | — |

LawBot and TherapyBot **already route through the unified `/api/v2/chat`**
endpoint using a `mode` discriminator, rather than having separate pipelines.
This is a significant head start for Phase 2.

### 3.2 Two parallel proxy layers

This is the main frontend architectural wart:

1. **`/api/v2/[...path]/route.ts`** — a generic, correct proxy. Forwards all
   non-hop-by-hop headers, attaches the Clerk token server-side, preserves
   every `Set-Cookie` (so the anonymous session works), honours timeouts, and
   passes the upstream status through.
2. **Seven hand-written legacy routes** — `/api/chat`, `/api/getPosts`,
   `/api/save`, `/api/closeIssue`, `/api/decompose`, `/api/generate-text`,
   `/api/generate-image`, `/api/postbyid/[id]`. Each re-implements proxying
   with varying quality.

The inconsistency caused a real defect (§6.2): `/api/closeIssue` forwarded no
credentials at all.

### 3.3 Auth integration

`src/lib/clerk-config.ts` is the single source of truth for "is Clerk usable",
shared by `next.config.ts`, `middleware.ts` and `server-auth.ts`. When Clerk is
unconfigured or the keys are placeholders, the Clerk SDK is webpack-aliased to
local stand-ins (`clerk-mock.tsx`, `clerk-mock-server.ts`) that report **no
signed-in user**. `/dashboard` is gated on configured Clerk **and** an
`HERWAY_ADMIN_USER_IDS` allow-list — self-assigned `unsafeMetadata` is not
trusted.

---

## 4. Feature-to-code inventory

Status key — **WORKING**: exercised end-to-end in this environment.
**PARTIAL**: works but with a documented gap. **BROKEN**: cannot complete.
**UNVERIFIED**: could not be exercised here; reason given.

### 1. Situation analysis and urgency detection
- **Code:** `agents/situation_agent.py` → `SituationAgent`; `models/research.py` → `Situation`, `Urgency`, `SituationCategory`
- **Endpoint:** `POST /api/v2/cases/analyze`
- **Status:** **UNVERIFIED (live)** — Gemini free-tier quota exhausted; endpoint returned `429` with an honest message during probing. Logic covered by `test_situation_agent.py` (5 passed, mocked LLM).
- **Config:** `GEMINI_API_KEY`
- **Reuse:** **Directly.** `Situation` is the natural shared context object for Phase 2.

### 2. Chat orchestration and agent routing
- **Code:** `agents/chat_agent.py` → `ChatAgent` (12 tools); `routes/chat.py` → `ChatRequest`/`ChatResponse`
- **Endpoint:** `POST /api/v2/chat`
- **Status:** **UNVERIFIED (live)** — `429` from Gemini. Routing and response shape covered by mocked tests.
- **Note:** `ChatResponse` returns `tool_used`, `plan_adapted`, `safety_plan`, `community_posts`, `lawbot_docs`, `formal_report`, `degraded_notice` — the full orchestration surface.
- **Reuse:** **Directly — this is the Phase 2 integration point.**

### 3. Research planning
- **Code:** `agents/research_agent.py` → `ResearchAgent.plan`; `services/research_orchestrator.py` → `ResearchOrchestrator`
- **Status:** **PARTIAL — duplicated responsibility.** See §6.1.
- **Tests:** `test_research_orchestrator.py` (11 passed, heavily mocked)
- **Reuse:** **Refactor — consolidate onto `ResearchOrchestrator`.**

### 4. SerpApi integration and search services
- **Code:** `services/serpapi_service.py` → `SerpApiService`, `SerpApiCache`
- **Verticals:** `google`, `google_news`, `google_maps`, scholar
- **Status:** **WORKING — REAL INTEGRATION VERIFIED.** Live calls made during this audit:
  - Maps: `"One Stop Centre Sakhi Nagpur"` → 1 result, top hit `'Sakhi one stop centre'`, `failure_reason=none`
  - Web: `"women helpline 181 India official"` → 10 results, top hit `"NCW Women's Helpline"`, `failure_reason=none`
- **Quality:** explicit `SearchFailureReason` taxonomy (9 values) so "no results" is distinguishable from "outage"; `_mentions_india()` appends jurisdiction to avoid foreign helplines; defensive `_as_text`/`_as_float`/`_as_int` coercion because Google Maps returns `type` as either string or list.
- **Caching:** in-process, 1h TTL, whitespace-normalised keys. **Per-process only** — see §7.
- **Config:** `SERPAPI_API_KEY`
- **Reuse:** **Directly.**

### 5. Source verification and research synthesis
- **Code:** `agents/source_verifier.py` → `SourceVerifier`; `india_resources.py` → `SourceTier`, `TIER_AUTHORITY`, `classify_source_tier`
- **Status:** **PARTIAL** — tier classification is pure logic and covered by `test_source_verifier.py` (4 passed); the LLM extraction step is UNVERIFIED live (quota).
- **Design:** 6 authority tiers, `GOVERNMENT_OF_INDIA` 0.95 → `GENERAL_WEB` 0.30; `.gov.in` and `.nic.in` both recognised.
- **Reuse:** **Directly.**

### 6. Action planning
- **Code:** `agents/action_planner.py` → `ActionPlanner`; `models/action_plan.py`
- **Status:** **UNVERIFIED (live)** — quota. `test_action_planner.py` (1 passed, mocked). Thinnest test coverage of any agent.
- **Reuse:** Directly; **add tests** (see roadmap Phase 4).

### 7. Safety planning and persistence
- **Code:** `agents/safety_plan_agent.py` → `SafetyPlanAgent`, `is_safety_case`; `models/safety_plan.py`
- **Endpoints:** `GET /api/v2/cases/{id}/safety-plan`, `PATCH .../safety-plan/actions/{id}`, `POST .../safety-plan/adapt`, `POST .../safety-plan/research-more`
- **Status:** **PARTIAL.** Ownership and 404/403 behaviour verified live (§5.2). Plan *generation* UNVERIFIED (quota). `test_safety_plan.py` (6 passed, mocked).
- **Design note:** `SafetyMatchedResource.verification` is a three-value
  `ResourceVerification` enum (`official_source` / `likely_official` /
  `unverified_listing`), not a boolean — so an unchecked Maps pin is never
  labelled "verified".
- **Reuse:** **Directly.**

### 8. Cases and incident management
- **Code:** `routes/cases.py`, `models/case.py`; `_load_owned_case()` on every path
- **Status:** **WORKING (in-memory).** Full CRUD verified live (§5.2).
- **Caveat:** **persistence to MongoDB is UNVERIFIED** — no reachable instance; `/health` reports `database: in-memory`.
- **Reuse:** **Directly.**

### 9. LawBot and legal RAG
- **Code:** `services/embedding_service.py` → `search_legal_docs`; `utils/embedding.py` → `generate_text_embedding`, `find_top_matches`; frontend `/lawbot`
- **Status:** **BROKEN.** Three independent, confirmed defects — see §6.3. The `/lawbot` *page* and its chat path work; the retrieval underneath returns nothing.
- **Reuse:** Keep the page and the `invoke_lawbot` tool. **Repair the retrieval layer (Phase 2).**

### 10. Niva / TherapyBot and emotional support
- **Code:** frontend `/therapybot`, `components/HavenAvatar.tsx` (Three.js); backend `/api/v2/chat` with `mode: 'therapy'`
- **Status:** **PARTIAL** — page renders (HTTP 200 verified); replies UNVERIFIED (quota). The fabricated "supportive fallback" that was visually identical to a real reply has been removed in prior work.
- **Reuse:** **Directly.**

### 11. Anonymous community and moderation
- **Code:** `routes/legacy.py` → `/get-admin-posts`, `/get-post/{id}`, `/save-extracted-data`, `/close-issue/{id}`, `/find-match`; `_PRIVATE_POST_FIELDS`, `_public_post()`
- **Status:** **PARTIAL.**
  - Reading posts: **WORKING** — verified live, 2 posts returned.
  - **PII stripping: WORKING — verified live.** Response fields contained no contact/email/phone key; `_PRIVATE_POST_FIELDS` strips 9 field names including `user_id` and raw embeddings.
  - Moderation (close issue): **was BROKEN, proxy now fixed** (§6.2); still cannot complete end-to-end because Clerk is unconfigured.
- **Security concern:** `/get-admin-posts` is reachable with **no identity at all** (verified: HTTP 200 without cookie). See §7.

### 12. Discreet messaging and steganography
- **Code:** `utils/steganography.py`, `services/steganography_service.py`, `routes/discreet.py`, frontend `/discreet-message`
- **Status:** **WORKING — REAL ROUND TRIP VERIFIED.** Direct function-level test this audit, 200×200 PNG, capacity 4998 bytes:

  | Script | Result |
  |---|---|
  | English | OK (11→11) |
  | Hindi (Devanagari) | OK (14→14) |
  | Tamil | OK (11→11) |
  | Bengali | OK (20→20) |
  | Emoji (non-BMP) | OK (6→6) |

  UTF-8 byte-level encoding; the earlier `ord()`-based version silently
  destroyed any non-ASCII character.
- **Honesty:** `routes/discreet.py` exposes a `LIMITATIONS` list stating plainly
  that this is *not encryption* and that WhatsApp/Instagram compression destroys
  the payload. `GET /api/v2/discreet/limitations` verified 200.
- **Reuse:** **Directly.**

### 13. Authentication and authorization
- **Code:** `backend/auth.py`; frontend `lib/clerk-config.ts`, `lib/server-auth.ts`, `middleware.ts`
- **Status:** **WORKING for anonymous sessions — VERIFIED LIVE.** Clerk path **UNVERIFIED** (no credentials; see §6.4).
- **Evidence:** §5.2 — 7/7 cross-tenant requests returned 403; a second browser's case list was empty.

### 14. User data persistence
- **Code:** `backend/db.py`
- **Status:** **UNVERIFIED against MongoDB.** All testing ran on the in-memory fallback. No create→restart→reload cycle was possible.
- **This is the single largest unverified area of the system.**

### 15. Existing frontend pages and user workflows
- **Status:** **WORKING (render + navigation).** All 12 routes verified HTTP 200 against a fresh production build, server log clean.
- `npx tsc --noEmit` clean · `next lint` clean · `next build` succeeds.

### 16. India-specific resources and safety guidance
- **Code:** `backend/india_resources.py`; `routes/resources.py`; frontend `lib/india.ts`, `components/States.tsx`
- **Status:** **WORKING (backend) / NOT SURFACED (frontend).** Verified live:
  - `GET /api/v2/resources/national` → 7 helplines (112, 181, 1091, 1930, 1098, 14567, 14416), **every one carrying `official_source_url`**, plus `portals` and `note`.
  - `GET /api/v2/resources/regions` → 28 states + 8 union territories = 36.
- **Gap:** **neither endpoint is called by the frontend.** Helpline numbers are
  instead hardcoded across 8 frontend files, with no source attribution. See §7.

---

## 5. Validation results

### 5.1 Automated suites

| Suite | Result |
|---|---|
| Backend `pytest` | **140 passed**, 0 failed, 204 warnings, ~35s |
| Frontend `tsc --noEmit` | **clean** |
| Frontend `next lint` | **clean** |
| Frontend `next build` | **succeeds**, 23 pages |

Per-module backend results:

| Module | Tests | Mock refs |
|---|---|---|
| `test_authorization.py` | 19 passed | 0 |
| `test_e2e_cases.py` | 33 passed | 28 |
| `test_serpapi.py` | 28 passed | 33 |
| `test_llm_service.py` | 17 passed | 10 |
| `test_women_safety.py` | 16 passed | 6 |
| `test_research_orchestrator.py` | 11 passed | 39 |
| `test_safety_plan.py` | 6 passed | 15 |
| `test_situation_agent.py` | 5 passed | 2 |
| `test_source_verifier.py` | 4 passed | 5 |
| `test_action_planner.py` | 1 passed | 2 |

> **Every one of the 140 tests is offline.** There is not a single real
> integration test in the repository. The suite validates code paths,
> contracts and failure handling — it does **not** demonstrate that Gemini,
> SerpApi, MongoDB or Atlas vector search work. Treat a green suite accordingly.

### 5.2 Live authorization test (real, not mocked)

Two independent cookie jars simulating two browsers, against the running
backend. Browser A created a case; browser B attempted to reach it.

```
A: POST   /api/v2/cases                         -> 200  (id 6abe5744...)
A: GET    /api/v2/cases/{id}                    -> 200
A: GET    /api/v2/cases                         -> 200
A: PATCH  /api/v2/cases/{id}                    -> 200
A: GET    /api/v2/cases/{id}/safety-plan        -> 404  (no plan yet — correct)

B: GET    /api/v2/cases/{id}                    -> 403
B: PATCH  /api/v2/cases/{id}                    -> 403
B: DELETE /api/v2/cases/{id}                    -> 403
B: GET    /api/v2/cases/{id}/safety-plan        -> 403
B: GET    /api/v2/research/{id}/plan            -> 403
B: GET    /api/v2/research/{id}/report          -> 403
B: POST   /api/v2/research/{id}/run             -> 403
B: GET    /api/v2/cases                         -> 0 cases
```

**7/7 cross-tenant attempts blocked.** Anonymous session isolation works.

### 5.3 Live integration probes (real)

| Integration | Result |
|---|---|
| SerpApi `google_maps` | **REAL CALL OK** — 1 result |
| SerpApi `google` | **REAL CALL OK** — 10 results |
| Gemini `generate` | **rate_limited** — free tier exhausted |
| Gemini embeddings | **REAL CALL OK after fix** — 768 dims (was 404) |
| Steganography | **REAL round trip OK** — 5 scripts |
| MongoDB | **in-memory** — URI set but unreachable |
| OpenCage / Groq / AWS Bedrock | not exercised |

### 5.4 Degradation behaviour (real)

With Gemini exhausted, the LLM-dependent endpoints degrade honestly rather than
fabricating:

```
POST /api/v2/cases/analyze -> 429
  "HerWay has reached its limit for AI requests just now. Please try again in a
   few minutes. If you need help immediately, call 112, or 181 for the women
   helpline. Your text has not been lost."

POST /api/v2/chat          -> 429  (same, with helpline)
```

This is correct and important: a safety product must never invent an answer
when its model is unavailable.

### 5.5 API contract alignment

Diffed the 10 distinct `/api/v2/*` paths the frontend calls against the live
OpenAPI schema:

```
Frontend calls not served by backend:  0   ← no contract mismatches
Backend v2 endpoints never called:     7
```

The 7 unused: `.../safety-plan`, `.../safety-plan/actions/{id}`,
`.../safety-plan/adapt`, `/research/{id}/plan`, `/research/{id}/report`,
`/resources/national`, `/resources/regions`.

The safety-plan reads are explained — the UI gets the plan embedded in the case
response (`caseData.safety_plan`). The two `resources` endpoints are a genuine
unsurfaced feature (§7).

---

## 6. Defects found

### 6.1 Duplicate research responsibility — ARCHITECTURAL, not fixed

`ResearchAgent` (210 lines) and `ResearchOrchestrator` (632 lines) both plan and
execute SerpApi research, and are reached by **different entry points**:

| Component | Called from |
|---|---|
| `ResearchAgent` | `agents/chat_agent.py:576`, `routes/cases.py:409` |
| `ResearchOrchestrator` | `routes/research.py:99` |

So a case researched through chat gets different budgeting, caching and quality
behaviour than the same case researched through `POST /api/v2/research/{id}/run`.
`ResearchOrchestrator` is the more capable implementation (budget enforcement,
iteration limits, contradiction resolution).

**Not fixed here** — consolidation changes behaviour and belongs in Phase 2.

### 6.2 `/api/closeIssue` dropped all credentials — FIXED

The Next proxy forwarded neither the session cookie nor the Clerk token, while
the backend requires `require_authenticated`. Every moderation attempt 401'd,
and the `catch` turned it into an opaque `500 {"error":"Failed to close issue"}`.

Verified before:
```
backend direct, no auth  -> 401
through the Next proxy   -> 500  {"error":"Failed to close issue"}
```
After the fix:
```
through the Next proxy   -> 401  {"detail":"Please sign in to continue."}
```

Now forwards cookie + Clerk token and preserves the upstream status. **The flow
still cannot complete end-to-end** because Clerk is unconfigured — that part
remains UNVERIFIED.

### 6.3 Legal RAG broken three ways — ONE FIXED, TWO DOCUMENTED

1. **Retired embedding model — FIXED.** `models/text-embedding-004` returns
   `404 ... is not found for API version v1beta`. Every embedding call failed,
   breaking both legal retrieval and community culprit matching. Replaced with
   `models/gemini-embedding-001`, output reduced to **768 dimensions** to stay
   compatible with the existing `culpritIndex2` declaration. Verified with a
   real API call: `len == 768`.
2. **Wrong field path — FIXED (code), still blocked.** `find_top_matches`
   hardcoded `path="culprit_embedding"`, but `search_legal_docs` queries the
   `doc_embedding` collection, whose vector field is `embedding`. Even with a
   working index, legal retrieval searched a field that does not exist there.
   `path`/`index` are now parameters (defaults unchanged for the community
   caller).
3. **Stored format incompatible — NOT FIXED, architectural.**
   `upload_embeddings_to_mongo` stores vectors as
   `Binary(pickle.dumps(embedding))`. Atlas `$vectorSearch` requires a plain
   array of numbers and cannot index a pickled blob. **Legal RAG cannot work
   until documents are re-ingested as plain arrays with a matching index.**

Additionally, `search_legal_docs` swallows every exception and returns `[]`, so
the caller cannot distinguish "no relevant law" from "retrieval is down". For a
legal assistant this is dangerous — an empty result must not be answered from
the model's own memory. The log message now says so explicitly; the return
contract was left unchanged (a Phase 2 item).

### 6.4 Clerk keys were placeholders — FIXED (prior step, confirmed here)

`frontend/.env.local` held a fabricated publishable key decoding to
`haven-dev.clerk.accounts.dev` and a secret containing the literal string
`mocksecret`. Clerk rejected every request with
`{"errors":[{"message":"Invalid host","code":"host_invalid"}]}`.
`lib/clerk-config.ts` now detects placeholder/unregistered keys and falls back
to anonymous sessions with a printed reason. Verified: 12/12 routes 200, zero
Clerk references in served HTML or any of the 6 JS chunks.

### 6.5 `/health` misreported MongoDB — FIXED

`_integration_status()` reported `"mongodb": true` whenever the env var was
*set*, while `database_mode()` reported `in-memory`. An operator reading
`/health` would believe cases were being persisted when they were not. Now
derived from the actual connection state.

### 6.6 SSR crash on `/dashboard` — FIXED (prior step)

`LiveTitle` statically imported `@lordicon/react` → `lottie-web`, which touches
`document` at module scope, throwing on every server render. Next recovered via
client rendering so the page still returned 200 and it appeared only in the log.
Split into `LiveIcon.tsx` loaded with `ssr: false`.

---

## 7. Security, privacy and reliability concerns

Ordered by severity. Detail and priority in `KNOWN_ISSUES.md`.

| # | Concern | Evidence |
|---|---|---|
| 1 | **12 of 14 legacy endpoints have no authentication.** Only `/close-issue/{id}` and `/upload_embeddings/` require identity. Verified live: `GET /get-admin-posts` → 200 with no cookie; `GET /poem-generation` → 422 (reached handler, no auth challenge). Includes LLM-invoking endpoints (`/text-generation`, `/text-decomposition`, `/img-generation`, `/poem-generation`, `/generate-image`) — anyone can burn the Gemini quota — and `/save-extracted-data`, which writes to the database. | live probe |
| 2 | **No rate limiting anywhere.** Combined with #1, a single visitor can exhaust the API budget for every real user. | inspection |
| 3 | **Legal RAG silently returns `[]` on failure.** A legal assistant that cannot distinguish "no law found" from "retrieval down" risks answering from parametric memory and inventing section numbers. | §6.3 |
| 4 | **`POST /send-message` publishes to Twitter, unauthenticated.** Not reachable from the current UI, but exposed on the API. In a DV product, an open endpoint that publishes externally is serious. | `routes/legacy.py:241` |
| 5 | **Raw search queries are logged.** `maps_service.py:197` logs `query='%s'` and `serpapi_service.py:152` logs the cache key (which contains the query). Queries derive from user situation text, so a log line can reveal that an identifiable session is seeking DV help. Note the structured `SerpApiLog` is careful — it records `query_length`, not the query — so the codebase is inconsistent rather than uniformly unsafe. | inspection |
| 6 | **Browser-side geocoding would leak a key.** `frontend/src/lib/utils.ts:12` calls OpenCage with `NEXT_PUBLIC_OPENCAGE_API_KEY`, which ships in client JS, and sends precise coordinates to a third party without passing through the server. **Currently dead code** — the helper is never called, and the variable is unset. | inspection |
| 7 | **All data is volatile.** `/health` reports `database: in-memory`. Every case and safety plan created in this environment is lost on restart. Production refuses this mode, but nothing has been verified against a real MongoDB. | live `/health` |
| 8 | **SerpApi cache is per-process.** `SerpApiCache` is an in-memory dict. With more than one worker, identical searches bill once per worker; a restart clears it. | inspection |
| 9 | **India resources exist but are invisible.** The attributed registry (every helpline with `official_source_url`) is never called by the UI; 8 frontend files hardcode `112`/`181` with no attribution. Two sources of truth that will drift. The states list is likewise duplicated between `lib/india.ts` and `/api/v2/resources/regions`. | §5.5 |
| 10 | **No CI.** Nothing runs the 140 tests automatically. | inspection |
| 11 | **`google-generativeai` is formally deprecated** and prints an end-of-support notice on import. Two model retirements have already broken this app (`gemini-1.5-flash`, `text-embedding-004`). | observed |
| 12 | **Dead code with prints.** `backend/utils/ai_assitant.py` is an interactive CLI with `print()` calls, never imported anywhere. | inspection |

---

## 8. Which integration contracts already exist

Against the nine contracts Phase 2 was asked to define — **seven already exist**
and should be reused rather than re-specified:

| Contract | Existing type | Status |
|---|---|---|
| Situation context | `Situation` — `category`, `urgency`, `user_goal`, `known_facts`, `user_claims`, `unknowns`, `missing_information`, `entities`, `organizations_involved`, `location` | **Exists, essentially complete** |
| Agent invocation / response | `ToolCallChoice` + per-tool models in `chat_agent.py` | **Partial** — tool-call shape exists, no uniform agent envelope |
| Research task planning | `ResearchPlan`, `ResearchTask`, `FreshnessPolicy`, `ResearchMetrics` | **Exists** |
| Normalized search results | `SearchResult`, `SearchOutcome`, `SearchRequest`, `SourceType` | **Exists** |
| Source verification | `EvidenceItem`, `EvidenceStatus`, `EvidenceConfidence`, `Contradiction`, `ResourceVerification`, `SourceTier` | **Exists** |
| Structured action plans | `ActionPlan`, `ActionItem` + 4 enums | **Exists** |
| Persistent safety plans | `SafetyPlan`, `SafetyActionItem`, `SafetyAssessment`, `SafetyMatchedResource` | **Exists** |
| Case references / shared context | `Case`, `CaseCreate`, `CaseUpdate` | **Exists**; no explicit user-approved context-sharing model |
| Consistent errors + trace IDs | `SearchFailureReason`, `ResearchDegradation`, `LLMUnavailableError`, `ResearchTraceEntry` | **Partial** — rich per-subsystem taxonomies, but **no `trace_id`/`request_id`/`correlation_id` exists anywhere in the codebase** (verified by grep) |

**The two real gaps are: a uniform agent invocation envelope, and a
request-scoped trace identifier.** Everything else is a matter of reuse.

---

## 9. Required configuration

| Variable | Needed for | Without it |
|---|---|---|
| `GEMINI_API_KEY` | all agents, embeddings | 503/429 with honest message |
| `SERPAPI_API_KEY` | all research | searches report `not_configured` |
| `MONGODB_URI` | persistence | in-memory, data lost on restart; refused in production |
| `HERWAY_SESSION_SECRET` | anonymous sessions | random per-process; sessions die on restart |
| `CLERK_ISSUER` (backend) + `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` / `CLERK_SECRET_KEY` (frontend) | accounts | anonymous-only mode |
| `HERWAY_ADMIN_USER_IDS` | `/dashboard` | nobody can access moderation |
| `OPENCAGE_API_KEY` | reverse geocoding | user types location; never guessed |
| `GROQ_API_TOKEN` | report second opinion | Gemini draft used alone |
| `AWS_*`, `S3_BUCKET_NAME` | community post images | reports unavailable |

**Missing infrastructure:** a reachable MongoDB; an Atlas cluster with
`culpritIndex2` (community) and a legal-document vector index; a Gemini key with
real quota; a Clerk project. `.env.example` was updated during this audit to
document 13 previously-undocumented variables.

---

## 10. Summary

| Category | Count | Items |
|---|---|---|
| **WORKING (verified)** | 6 | SerpApi integration · steganography · anonymous auth + ownership · case CRUD (in-memory) · India resources API · frontend render/build |
| **PARTIAL** | 6 | Research planning (duplicated) · source verification · safety planning · TherapyBot · community · situation analysis |
| **BROKEN** | 1 | Legal RAG retrieval |
| **UNVERIFIED** | 3 | MongoDB persistence · Clerk sign-in · all LLM-dependent generation (quota) |

**Defects fixed this phase:** 3 (embedding model + RAG field path, closeIssue
credential forwarding, `/health` MongoDB reporting).
**Defects documented for later:** see `KNOWN_ISSUES.md`.
**Files deleted:** 0. **Features removed:** 0.
