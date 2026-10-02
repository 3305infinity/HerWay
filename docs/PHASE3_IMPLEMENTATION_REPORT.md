# HerWay — Phase 3 Implementation Report

**SerpApi-Powered Research and Local Intelligence.** Completed 2026-10-01.
Builds on [`PHASE2_IMPLEMENTATION_REPORT.md`](PHASE2_IMPLEMENTATION_REPORT.md).

No second orchestrator was created, `ChatAgent` was not rewritten, and nothing
was deleted.

---

## 1. The line this phase does not cross

HerWay now helps a user find and compare places. It does **not** tell anyone a
place or route is safe, because search results cannot establish that. A venue
with 4.8 stars and 2,000 reviews can be dangerous for a woman alone at night;
one with no reviews can be fine.

That constraint is enforced structurally, not by prompt wording:

- No model in this phase has a `safety_score`, `is_safe` or `safest` field —
  asserted by tests that grep the serialised payloads.
- `compare_options` has **no overall ranking** and preserves input order, so a
  higher rating cannot silently become "first choice".
- Review themes are grouped deterministically; the keyword group that mentions
  security is named `security_mentions` and ships with a limitation stating it
  records what a reviewer wrote, not whether the place is safe.
- `AreaReportSummary` carries `cannot_infer_crime_rate` and
  `absence_of_results_is_not_safety` as explicit fields.
- Every listing carries `open_now_known: false` — the provider does not tell us,
  so we say so rather than implying it.

---

## 2. Cache architecture and infrastructure requirements

### What was there

`SerpApiCache` was a dict on the service instance. Every worker held its own,
and a restart discarded it. SerpApi bills per search.

### What was chosen, and why

The repository has **no Redis, Memcached or any shared store configured**
(verified), and no MongoDB was reachable. Rather than introduce a service the
project would then depend on, `backend/services/search_cache.py` ships three
interchangeable backends and defaults to the one that changes nothing:

| Backend | Sharing | Requirements | Verified |
|---|---|---|---|
| `memory` *(default)* | none — per process | nothing | n/a |
| `sqlite` | across processes, **one host** | a writable file path | **yes — see §3** |
| `mongodb` | across hosts | the MongoDB the app already needs + TTL index | **no** |

Selected with `HERWAY_CACHE_BACKEND`. An unavailable backend degrades to
in-process with a warning; a cache outage never becomes a user-visible outage.

SQLite was chosen as the verifiable shared option because it is in the standard
library — zero new dependency — and WAL mode gives concurrent cross-process
access, which is exactly the shape of a multi-worker uvicorn deployment on one
machine.

### TTL policy

| Vertical | TTL | Reasoning |
|---|---|---|
| `news` | 15 min | Freshness is the entire point of a news search |
| `maps` / `local` | 3 h | Name and address are stable; hours and closures drift |
| `web` | 1 h | Procedures and statutes change slowly |

### Key construction

Keys are `sha256` of normalised `(vertical, query, location, country, language,
page, extra)`. Whitespace and case collapse, so `"women  helpline"` and
`"Women Helpline"` share an entry. Location, country, language and page are all
part of the key — a Pune result is not a Nagpur result.

**The query is hashed, not stored.** Keys land in a shared store and in metrics;
a raw key would disclose that someone searched for a women's shelter in a named
district. API keys never enter the key material.

### Safety properties

- **JSON, never pickle.** A shared store is untrusted input; unpickling it would
  be arbitrary code execution.
- **Empty results are never cached** — indistinguishable from a failure.
- **Corrupt or wrong-schema entries are evicted and treated as a miss**, never
  raised into the request path.
- **Single-flight locking** collapses concurrent identical queries in one
  process. Cross-*worker* deduplication would need a distributed lock and is
  deliberately out of scope.

---

## 3. Cross-process verification — the claim and its evidence

The brief required not claiming cross-process sharing without proving it.

```
WRITER pid=33844 backend=sqlite shared=True writes=1
READER pid=27304 hit=True results=1
  recovered: 'Sakhi One Stop Centre' <- written by a DIFFERENT process
  unknown key is a miss: True

control (memory backend): cross-process hit = False
```

Two independent OS processes; one wrote, the other read it back. The control
shows the in-process backend fails the same test, which is what makes the result
meaningful. This runs in CI as
`test_sqlite_cache_is_shared_across_processes`, which spawns a real second
interpreter via `subprocess`.

**The `mongodb` backend is contract-tested against a fake collection only.**
Cross-host sharing is unverified.

---

## 4. Local resource resolution

`backend/services/resource_resolver.py`. Triggered by
`SafetyWorkflow.LOCAL_RESOURCES`.

**Flow:** user text → `wants_local_discovery()` → `infer_category()` →
`ResourceResolver.resolve()` → `SerpApiService.search_detailed()` *(cached)* →
normalise → `ResolutionOutcome`.

15 categories, each with a query template tuned for Indian listings (One Stop
Centre, Mahila Thana, DLSA, Swadhar Greh). The category set is closed, so no
unvalidated user text becomes a provider query.

**Trigger discipline.** `wants_local_discovery` returns `False` for writing
requests, explanations, translations and emotional messages. Each false positive
is a wasted paid call and a worse answer; 9 negative cases are tested.

**Location.** A place name is enough. Precise GPS is never requested for
ordinary discovery — "find a chemist in Baner" does not need it, and asking
would collect a sensitive signal for no benefit. A missing location returns
`location_required` rather than a guess.

**Failure vs emptiness.** `ResolutionOutcome.success=False` means the lookup
broke; `found_nothing=True` means it worked and matched nothing. Collapsing
these would tell a woman an area has no hospitals when the search simply failed.

---

## 5. Normalised schemas

```
ResolvedResource     name, category, address?, phone?, url?, source_domain?,
                     rating?, review_count?, verification, verification_note,
                     hours_text?, retrieved_at, open_now_known=false

ResolutionOutcome    resources[], success, failure_reason, category,
                     location_used?, query_used?, from_cache, trace_id,
                     retrieved_at, found_nothing, disclaimer

PlaceProfile         name, listing?, reviews?, success, failure_reason,
                     sources[], trace_id, retrieved_at

ReviewSummary        themes[], total_reviews_seen, provider_review_count?,
                     average_rating?, limitations[], possible_duplicate_content,
                     is_not_a_safety_assessment=true

AreaReportSummary    articles[], success, failure_reason, limitations[],
                     cannot_infer_crime_rate=true,
                     absence_of_results_is_not_safety=true

ComparisonResult     option_names[], fields_compared[], table{}, user_priorities[],
                     notes[], retrieved_at, has_overall_ranking=false, basis
```

Every optional field is `None` when the provider did not supply it. Nothing is
filled in from a similar listing or from model memory.

---

## 6. Source and uncertainty handling

**Reviews.** Deterministic keyword grouping into nine themes, each carrying the
verbatim fragments that produced it. Positive and negative evidence both
survive. Near-duplicate text is detected and flagged, because repeated copies of
one description are a single source, not several people agreeing.

**News.** `classify_claim()` labels each item `allegation`,
`reported_incident`, `official_statement` or `unclear`. Allegation wins over
incident wording, because presenting an allegation as established fact is the
costlier error. Only a real `published_at` is used; a relative string is kept
verbatim rather than converted into a date we would be guessing at. Undated
articles are counted and flagged.

**Comparison.** Only fields at least one option actually has become rows. Gaps
are labelled "Not published by the source" — not blank, and not zero. An option
with nothing published still appears, because knowing a listing has no phone
number is itself useful. User priorities reorder the table and are echoed back;
they never collapse into a score.

---

## 7. Integration with chat

Two tools added **alongside** the existing twelve; no existing tool name or
behaviour changed.

| Tool | When |
|---|---|
| `research_place` | The user names one specific place |
| `compare_places` | The user is weighing options of one category in one area |

The system prompt steers `search_safety_resources` for support services during a
safety situation and `compare_places` for everyday choices, and forbids either
for writing requests, emotional support or legal questions. A missing location
asks rather than guesses.

Three optional fields added to `ChatResponse` — `local_resources`,
`place_profile`, `comparison`. All additive; a client ignoring them behaves
exactly as before.

**The deterministic safety triage path is untouched** and remains independent of
live search, as Phase 2 left it.

---

## 8. Cost, latency and reliability

| Control | Where | State |
|---|---|---|
| Per-workflow search budget | `ResearchOrchestrator` (4 normal / 6 complex) | from Phase 2 |
| Shared caching | `search_cache.py` | **new** |
| Query deduplication | normalised key + orchestrator dedup | from Phase 2 + new |
| Single-flight | `SerpApiCache.lock_for` | **new**, in-process only |
| Bounded parallelism | `asyncio.gather` over a budget-capped task list | from Phase 2 |
| Provider timeout | `SERPAPI_TIMEOUT_SECONDS`, default 30s | existing |
| Retries | existing backoff; non-recoverable errors are not retried | existing |
| Rate limiting | `rate_limit.py`, LLM tier on all discovery routes | from Phase 2 |
| Usage metrics | `SerpApiCache.stats()` | **new** |
| Graceful degradation | failure taxonomy preserved end to end | from Phase 2 |

### Rate limiter: the limitation, stated plainly

`backend/rate_limit.py` is **in-process**. With N workers a caller effectively
gets N× the budget, and a restart clears it. It stops casual abuse and runaway
clients; it is **not** globally enforced and is not a defence against a
distributed attacker.

Making it distributed needs a shared counter with atomic increment — which is a
*different* dependency from the cache. SQLite is adequate for a read-mostly
cache on one host but a poor fit for a high-contention counter, and the mongodb
cache backend is unverified. **Distributed rate limiting is therefore separated
from this phase and depends on choosing a real shared store (Redis being the
natural fit).** It is not claimed as done.

---

## 9. Tests and validation

### Automated

| Suite | Result |
|---|---|
| **Backend total** | **451 passed**, 0 failed, 0 skipped (~59s) |
| ├─ pre-Phase-3 | 315 passed, unmodified |
| ├─ `test_search_cache.py` | **39** new (incl. a real cross-process test) |
| ├─ `test_local_intelligence.py` | **69** new |
| ├─ `test_discover_routes.py` | **19** new |
| └─ `test_chat_agent_phase2.py` | +9 for the new tools |
| Frontend `tsc --noEmit` | clean |
| Frontend `next lint` | clean |
| Frontend `next build` | succeeds; `/discover` at 3.98 kB |

**Which used mocks:** everything except the two items below. The SerpApi
provider is a `MagicMock` throughout `test_local_intelligence.py` and
`test_discover_routes.py`.

**Which used real services:**

1. `test_sqlite_cache_is_shared_across_processes` — a **real** second Python
   process and a real SQLite file. No network.
2. The live smoke test below — a **real, billable** SerpApi call.

### Live SerpApi smoke test (real)

One billable call, then an identical repeat to exercise the cache:

```
LIVE call   : success=True resources=1 reason=none
  latency   : 8729 ms   trace=phase3-live-0001
  - 'Sakhi one stop centre'
      addr='5, Katol Rd, Dalal Compound, Rajnagar, Nagpur,'
      phone=None  verification=likely_official

CACHED call : resources=1 latency=1 ms
  cache stats: {'backend': 'sqlite', 'shared_across_processes': True,
                'hit_rate': 0.5, 'hits': 1, 'misses': 1, 'errors': 0, 'writes': 1}
```

**8729 ms → 1 ms**, one SerpApi credit instead of two. Note `phone=None`: the
listing published no number, and the resolver reports that rather than
inventing one.

### Not validated

- **Gemini** — quota still exhausted. No LLM-backed path verified live in any
  phase.
- **MongoDB / Atlas** — unreachable. The `mongodb` cache backend and all
  persistence remain unverified.
- **Clerk** — not configured.
- **Cross-host cache sharing** — requires the mongodb backend, hence unverified.

---

## 10. Files changed

**New (7)**

```
backend/services/search_cache.py          pluggable shared cache
backend/services/resource_resolver.py     local resource resolution
backend/services/place_research.py        place/review/news + comparison
backend/routes/discover.py                5 discovery endpoints
backend/tests/test_search_cache.py        39 tests
backend/tests/test_local_intelligence.py  69 tests
backend/tests/test_discover_routes.py     19 tests
frontend/src/app/discover/page.tsx        discovery UI
docs/PHASE3_IMPLEMENTATION_REPORT.md      this document
```

**Modified (7)**

```
backend/services/serpapi_service.py   SerpApiCache re-exported from search_cache
backend/agents/chat_agent.py          +2 tools, prompt guidance (no rewrite)
backend/routes/chat.py                +3 optional response fields
backend/main.py                       mounted the discover router
backend/tests/test_chat_agent_phase2.py  +9 tests
frontend/src/components/Navbar.tsx    "Find places" link
.env.example                          cache backend + TTL documentation
```

**Deleted: 0. Endpoints removed: 0. Features removed: 0.**

---

## 11. Known provider limitations

- **SerpApi Maps returns no opening-hours flag** in the shape consumed here, so
  `open_now_known` is always `false`. Claiming "open now" would be invention.
- **Review text is snippet-only.** A handful of fragments out of a rating based
  on thousands — stated in every `ReviewSummary.limitations`.
- **`type` arrives as either a string or a list** depending on the listing;
  handled by the Phase 1 coercion helpers.
- **News dates are often relative** ("2 days ago") or absent.
- **No independent corroboration is available.** Syndicated copies look like
  separate sources, hence the duplicate-content flag.

---

## 12. Remaining limitations

1. **Distributed rate limiting is not implemented** (§8). Needs a shared atomic
   counter; separate dependency from the cache.
2. **Cross-worker single-flight is not implemented.** Two workers can still race
   on one key.
3. **`mongodb` cache backend unverified.**
4. **Gemini, MongoDB, Atlas and Clerk remain unverified** across all three
   phases.
5. **Legal RAG still broken** (Phase 1 B-01) — pickled vectors, no Atlas index.
6. **No CI.** 451 tests, nothing runs them automatically.

---

## 13. Recommended starting point for Phase 4

Phase 4 is *Actionable Workflows and Persistent Safety Center*, and it is the
first phase whose value depends on **data surviving a restart**. Everything
built so far is stateless or cached.

**Start by proving persistence**, before building any Safety Center UI:

1. Stand up a real MongoDB (local `mongod` or Atlas) and set `MONGODB_URI`.
2. Run one create → restart → reload cycle against it for an existing `Case`.
3. Only then build safety-plan, trusted-contact and check-in storage.

The reason for that order: `backend/db.py` falls back to an in-memory store that
loses everything on restart, and `/health` now reports this truthfully. A Safety
Center built and "verified" on that fallback would pass its tests and lose a
woman's safety plan the first time the process restarted. That is the single
most consequential unverified assumption in the codebase.

Reuse `SafetyPlan`, `SafetyActionItem`, `SafetyMatchedResource` and
`safety_plan_agent` as they stand; they already model most of what Phase 4
needs. `ResolvedResource.to_dict()` is directly saveable into
`SafetyPlan.matched_resources`, which is the natural seam between this phase
and the next.
