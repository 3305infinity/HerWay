# HerWay — Production Reliability & India Readiness Report

Date: 1 October 2026

---

## 0. Headline

The product had **four crash-level defects that meant core features had never
worked at all** — not "worked badly", but raised `NameError` on every call.
The frontend could not be built for production. Any visitor could read, edit
or archive any other user's case file.

Those are fixed and verified. Backend tests went from **12 passing / 17 failing
/ 2 modules that could not even import** to **140 passing**. `npm run build`
went from failing to succeeding.

---

## 1. Feature health matrix

Status recorded **after** this pass. "Verified live" means exercised against
the real running stack, not only in tests.

| Feature | Frontend | Backend | DB | External dep | Error handling | Case-integrated | Status |
|---|---|---|---|---|---|---|---|
| Homepage / guided intake | ✅ | ✅ | ✅ | Gemini | ✅ | ✅ | **WORKING** |
| Case creation | ✅ | ✅ | ✅ | — | ✅ | ✅ | **WORKING** (verified live) |
| Case workspace | ✅ | ✅ | ✅ | — | ✅ | ✅ | **WORKING** |
| Case list / lifecycle | ✅ | ✅ | ✅ | — | ✅ | ✅ | **WORKING** (verified live) |
| Situation Agent | ✅ | ✅ | ✅ | Gemini | ✅ | ✅ | **WORKING** (LLM quota-limited today) |
| Research Agent / Orchestrator | ✅ | ✅ | ✅ | Gemini + SerpApi | ✅ | ✅ | **WORKING** (was 100% broken) |
| SerpApi Web | ✅ | ✅ | n/a | SerpApi | ✅ | ✅ | **WORKING** (verified live) |
| SerpApi Maps / Local | ✅ | ✅ | n/a | SerpApi | ✅ | ✅ | **WORKING** (verified live) |
| SerpApi News | ✅ | ✅ | n/a | SerpApi | ✅ | ✅ | **WORKING** |
| Source Verification | ✅ | ✅ | n/a | Gemini | ✅ | ✅ | **WORKING** (scoring verified live) |
| Action Planner | ✅ | ✅ | ✅ | Gemini | ✅ | ✅ | **WORKING** |
| Safety Plan | ✅ | ✅ | ✅ | Gemini | ✅ | ✅ | **WORKING** (was 100% broken) |
| Case-aware chat (Ask HerWay) | ✅ | ✅ | ✅ | Gemini | ✅ | ✅ | **WORKING** |
| Research Trail | ✅ | ✅ | ✅ | — | ✅ | ✅ | **WORKING** |
| LawBot / legal RAG | ✅ | ✅ | ✅ | Gemini + Mongo Atlas | ✅ | ✅ | **PARTIAL** — RAG needs an Atlas vector index |
| Niva / TherapyBot | ✅ | ✅ | ✅ | Gemini | ✅ | ✅ | **WORKING** |
| 3D avatar | ✅ | n/a | n/a | bundled `.glb` | ✅ | n/a | **WORKING** |
| Anonymous Community | ✅ | ✅ | ✅ | — | ✅ | ✅ | **WORKING** (verified live) |
| Community posts (create) | ✅ | ✅ | ✅ | Gemini/Groq/AWS | ✅ | ✅ | **PARTIAL** — image step needs AWS |
| Discreet messaging (steganography) | ✅ | ✅ | n/a | — | ✅ | ✅ | **WORKING** (was BROKEN; verified live) |
| Quick Exit | ✅ | n/a | n/a | — | ✅ | n/a | **WORKING** (claims now accurate) |
| Authentication / Clerk | ✅ | ✅ | ✅ | Clerk | ✅ | ✅ | **WORKING** (anonymous fallback isolated) |
| Authorization (case ownership) | ✅ | ✅ | ✅ | — | ✅ | ✅ | **WORKING** (verified live) |
| MongoDB persistence | n/a | ✅ | ⚠️ | MongoDB | ✅ | ✅ | **UNVERIFIED** — no Mongo running locally |
| Embeddings / RAG | n/a | ✅ | ⚠️ | Gemini + Atlas | ✅ | ✅ | **UNVERIFIED** — needs Atlas |
| Reports (formal complaint) | ✅ | ✅ | ✅ | Gemini + Groq | ✅ | ✅ | **PARTIAL** — Groq unset, Gemini-only |
| Legacy APIs | n/a | ✅ | ✅ | mixed | ✅ | ✅ | **WORKING** (verified live) |
| India resource registry | ✅ | ✅ | n/a | — | ✅ | ✅ | **WORKING** (new) |

---

## 2. Crash-level defects found (features that had never worked)

These were not degradations. Each raised an exception on the first call.

| # | File | Defect | Blast radius |
|---|---|---|---|
| 1 | `backend/services/serpapi_service.py` | `Enum` used but never imported | **Every single SerpApi search** raised `NameError`. All live research was dead. |
| 2 | `backend/agents/safety_plan_agent.py` | `BaseModel` used but never imported | **Every safety plan** raised `NameError`. The core feature of the product. |
| 3 | `backend/services/research_orchestrator.py`<br>`backend/agents/research_agent.py` | `case_id: str = case_id` inside a class body | **All research planning** raised `NameError`. A class body cannot read a name it is assigning. |
| 4 | `backend/services/llm_service.py` | `exc` referenced outside its `except` block | The JSON-correction retry path always raised `NameError`, so any malformed LLM output became a crash. |

**None of these were caught by the test suite**, because
`test_e2e_cases.py` and `test_women_safety.py` imported names
(`ActionStep`, `SourceItem`, `VerificationStatus`) that have never existed in
`backend/models/research.py`. Both modules failed at collection, so neither
had ever run.

---

## 3. Security and privacy defects fixed

| Severity | Defect | Fix |
|---|---|---|
| **Critical** | Every case endpoint took `user_id` as an *optional query parameter from the browser*. Omitting it granted full access to any case. | `backend/auth.py` resolves identity server-side. Ownership is checked on every endpoint. |
| **Critical** | All anonymous users shared the literal owner id `"anonymous"`, so anonymous case files were pooled and mutually readable. | Each browser gets a signed, isolated anonymous session (`herway_sid`, httpOnly). |
| **Critical** | With no Clerk keys, `currentUser()` returned a fabricated admin with `isAdmin: true`, so **`/dashboard` — the list of every community abuse report — rendered for any visitor.** | Stand-in returns `null`. Dashboard requires configured Clerk **and** an `HERWAY_ADMIN_USER_IDS` allow-list. |
| **High** | `/close-issue/{id}` was unauthenticated — anyone could close any survivor's report. | Requires a signed-in user. |
| **High** | Community API returned `Contact info`, `phone`, `preferred way of contact`. `PostDetail` rendered them on a public page. | Stripped server-side and removed from the UI. |
| **High** | `/find-match?collection=` took the collection name from the query string — readable: `cases`. | Restricted to an allow-list. |
| **High** | `/save-extracted-data` inserted the whole request body, so a caller could set `_id` or `status`. | Field allow-list; `status` set server-side. |
| **Medium** | `/encode` wrote every result to a shared `encoded_image.png` on disk — concurrent users could receive each other's private message. | Streamed from memory. |
| **Medium** | `next.config.ts` allowed `remotePatterns: hostname: '**'` — any URL proxied through the image optimiser. | Restricted to the hosts actually used. |
| **Medium** | Unhandled errors returned HTML stack traces. | Middleware returns a plain, non-leaking JSON error. |

---

## 4. Honesty defects fixed (the product claiming more than it knew)

This category mattered most for a safety product.

- **Every resource carried a green "✓ Verified Resource" badge**, including
  unchecked Google Maps pins — `is_verified_gov_or_ngo` defaulted to `True` and
  `research-more` hardcoded it. Replaced with a three-level
  `ResourceVerification` (`official_source` / `likely_official` /
  `unverified_listing`), each with a plain-English note.
- **The research progress screen ticked off five named stages on a timer**,
  regardless of what the backend was doing. Replaced with an indeterminate
  indicator.
- **The research trail showed five green ticks** derived from `trace.length`,
  so a case where every search failed still looked complete. Now derived from
  what actually succeeded.
- **TherapyBot fabricated a supportive reply when the API failed**, visually
  identical to a real answer. Now says it could not reply and surfaces
  Tele-MANAS 14416.
- **A missing SerpApi key returned an empty list**, indistinguishable from "no
  results found". Now an explicit `SearchFailureReason` taxonomy.
- **Partial failures were invisible** — web results would show with no
  indication that the nearby-centre search had failed. Now reported per stage.
- **Quick Exit was presented as if it erased your tracks.** Corrected
  throughout, with a new `/privacy` page stating plainly what it cannot do.
- `"We don't log personal identifiers"` on the homepage — replaced with an
  accurate description.

---

## 5. India readiness

| Issue | Before | After |
|---|---|---|
| Search locale | `gl=us` — US helplines for Indian users | `gl=in`, with jurisdiction appended to queries (a live search for "women helpline 181" returned a **UK** helpline first) |
| `.nic.in` authority | Not recognised → `ncw.nic.in`, `edaakhil.nic.in` scored **0.65**, same as a random commercial site | Recognised → **0.95**. Verified live. |
| Emergency numbers | Prompts included `911` | Indian only: 112, 181, 1091, 1098, 1930, 14416 |
| Resource registry | None; numbers scattered in prompts | `backend/india_resources.py` — every entry carries its official source URL |
| Location | `"e.g. Austin, TX"` placeholder | State/UT dropdown (28 + 8), city, PIN validation. Never assumes a location. |
| Maps queries | Generic | One Stop Centre (Sakhi), Mahila Thana, DLSA, cyber cell |
| Legal framing | Generic | PWDVA 2005, POSH Act 2013, BNS/IPC, IT Act; DLSA/NALSA free legal aid |
| Formatting | US conventions | `+91 98765 43210`, `1 October 2026`, INR with lakh/crore grouping |
| Non-ASCII text | **Steganography corrupted Hindi/Tamil** (`ord()` per character, not UTF-8 bytes) | UTF-8 byte encoding. Hindi and Tamil round-trips verified live. |

---

## 6. Flow-by-flow verification

| Flow | Result |
|---|---|
| **A — Domestic violence** | Case creation, persistence, reload, lifecycle **verified live**. Safety plan generation covered by tests; blocked live today by Gemini quota. Plan prompts forbid confrontation (asserted in tests). |
| **B — Workplace harassment (POSH)** | SHe-Box + DLSA legal aid surfaced. "my manager keeps making sexual comments" now classifies as a safety case — **it did not before**: the keyword list had no entry for "sexual". |
| **C — Online harassment** | cybercrime.gov.in + 1930 surfaced; evidence-preservation steps carry safety caveats. |
| **D — Legal question** | Does **not** force a safety plan. LawBot labels claims `Fact:` / `Legal information:` / `Possible option:` / `Needs verification:` and never invents section numbers. |
| **E — Emotional distress** | Therapy mode blocks legal escalation and search tools. Avatar + voice preserved. "Save as a case" now works (was posting as `"anonymous"`, so saved sessions never appeared in My cases). |
| **F — Community** | Browse, detail, create-case **verified live**. Contact details confirmed stripped. Bad/missing IDs return 400/404. |
| **G — Discreet messaging** | **Verified live end to end** — encode → download → decode, in English, **Hindi and Tamil**. Previously this flow never encoded anything: it posted the image URL to a text endpoint and read a field that endpoint does not return, so the share link was literally `?url=undefined`. |

---

## 7. External dependencies

| Service | Required for | If missing |
|---|---|---|
| **Gemini** | All agents | 503/429 with an honest message + helpline numbers. App starts. |
| **SerpApi** | Live research | `not_configured` failure reason, distinct from "no results". App starts. |
| **MongoDB** | Persistence | Dev: in-memory + loud warning, reported at `/health`. **Production: refuses to start** rather than silently losing saved cases. |
| **Clerk** | Accounts | Anonymous isolated sessions. Dashboard inaccessible. |
| **OpenCage** | Reverse geocoding | User types their location; never guessed. |
| **Groq** | Second report draft | Gemini draft alone. |
| **AWS Bedrock + S3** | Community post images | That step reports unavailable. |

`GET /health` reports all of this truthfully. Live example — note `mongodb: true`
(configured) but `database: in-memory` (could not connect):

```json
{"status":"ok","database":"in-memory",
 "integrations":{"gemini":true,"serpapi":true,"mongodb":true,"clerk":false},
 "degraded":["clerk","groq","aws_bedrock"]}
```

Full variable reference: **`.env.example`** (new).

Production-critical: `HERWAY_SESSION_SECRET`, `MONGODB_URI`, `CLERK_ISSUER`,
`CLERK_SECRET_KEY`, `HERWAY_ADMIN_USER_IDS`, `HERWAY_ENV=production`.

---

## 8. Test results

```
Backend:  140 passed          (was: 12 passed, 14 failed, 3 errors,
                                     2 modules failing to import)
Lint:     No ESLint warnings or errors   (was: ~45 errors)
Build:    Compiled successfully          (was: FAILED — undeployable)
```

New suites: `test_authorization.py` (19 tests — cross-user access on every
endpoint), `test_llm_service.py` (17 — outage/quota/timeout classification).
Rewritten: `test_e2e_cases.py` (33 — all seven flows + failure paths),
`test_women_safety.py` (16).

---

## 9. Files

- **Modified: 52**
- **New: 18**
- **Deleted: 1** — `frontend/src/app/api/hero-image/route.ts`

The single deletion was dead code containing a **hardcoded absolute path to a
developer's machine** (`C:\Users\Nishtha\.gemini\antigravity-ide\brain\...`)
which it would `copyFileSync` from at request time. Nothing referenced it; the
homepage loads `/images/haven-hero.jpg` from `public/` directly. Restorable
with `git checkout` if you want it back.

---

## 10. Remaining production risks

Ordered by severity.

1. **Gemini free-tier quota is 20 requests/day.** One full case consumes
   roughly 5–8. This is a billing issue, not a code issue, but the product is
   unusable for real users without a paid key.
2. **MongoDB persistence is unverified** — no instance was reachable during
   this pass. All testing ran on the in-memory store. The code path is
   covered by tests, but **run one real create → restart → reload cycle
   against Atlas before launch.**
3. **LawBot RAG is unverified.** `find_top_matches` needs a MongoDB Atlas
   `$vectorSearch` index named `culpritIndex2` over `doc_embedding`. Without
   it, LawBot silently falls back to live web search. Create the index, or
   accept the fallback knowingly.
4. **SerpApi's `google` engine was intermittently slow** during testing —
   several 30s timeouts, then sub-second. Retry handles it and failures are
   reported honestly, but users will sometimes see "that search did not
   complete".
5. **Safety-plan quality is not verified against real output.** Structure,
   grounding rules and the no-confrontation mandate are enforced in prompts
   and asserted in tests, but **a trained DV professional should review
   generated plans for several real scenarios before this reaches users.**
   No amount of testing substitutes for that.
6. **`google-generativeai` is deprecated** by Google (migrate to
   `google-genai`). Working today, emits a deprecation warning.
7. **No rate limiting on HerWay's own endpoints.** A single client can drain
   the SerpApi and Gemini budget.
8. **Anonymous sessions are per-browser.** Clearing cookies loses access to
   saved cases permanently. This is deliberate — the alternative is asking
   abuse survivors to create accounts — but users should be told.
9. **`/create-post` image generation needs AWS.** Unconfigured, that step of
   the community flow cannot complete.

---

## 11. What was deliberately not changed

- No existing feature was removed. LawBot, Niva, the 3D avatar, Community,
  steganography, embeddings/RAG, and all legacy endpoints remain.
- Legacy `/encode` and `/decode` kept for backward compatibility alongside the
  new `/api/v2/discreet/*`.
- `/api/chat` kept, now forwarding to the backend agent rather than making its
  own differently-configured Gemini call.
- The agentic layer orchestrates the original capabilities; it does not
  replace them.
