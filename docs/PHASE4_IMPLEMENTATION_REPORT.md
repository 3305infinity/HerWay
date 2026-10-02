# HerWay — Phase 4 Implementation Report

**Actionable Workflows and Persistent Safety Center.** Completed 2026-10-01.
Builds on [`PHASE3_IMPLEMENTATION_REPORT.md`](PHASE3_IMPLEMENTATION_REPORT.md).

`safety_plan_agent` and `action_planner` were **not replaced**. No second
orchestrator was created, the frontend was not rebuilt, and nothing was deleted.

---

## 1. The two claims this phase refuses to make

A safety product that *looks* like it is protecting someone while doing nothing
is worse than one that admits its limits. Two capabilities were deliberately
built as less than they could appear to be:

**It does not monitor check-ins.** HerWay has no reliable background execution.
A timer in a browser tab dies when the tab closes; a server-side scheduler does
not exist here. So `CheckIn.is_overdue()` is computed **when the user looks at
it**, never by a background job, and the API response to starting a check-in
contains:

> *"HerWay is not monitoring this check-in. No one is alerted if the time
> passes."*

**It does not deliver messages.** No SMS or WhatsApp provider is configured.
`/share-draft` prepares text and returns `wa.me` / `sms:` / `mailto:` links the
user opens herself. `delivery_guarantee` is the literal string `"none"`, and the
notice says HerWay cannot confirm the message was delivered or read.

Both are asserted by tests, so neither can quietly become a false promise later.

---

## 2. Safety Center architecture

### Relationship to the existing safety plan

`backend/models/safety_plan.py` — `SafetyPlan`, the AI-generated crisis plan
embedded in a `Case`, phased into "right now / next 24h / document if safe /
support network / formal options" — is **untouched**. `safety_plan_agent` still
produces it and every existing caller still works.

Phase 4 adds a different object: `SafetyCenterPlan`, in
`backend/models/safety_center.py`. It belongs to a **person** rather than an
incident, outlives any one case, and a user can hold several at once ("getting
home late", "when he is released").

| | `SafetyPlan` (existing) | `SafetyCenterPlan` (new) |
|---|---|---|
| Owner | a Case | a user |
| Author | the LLM | the user |
| Count | one per case | many |
| Lifetime | the case | until deleted |
| Storage | inside the Case doc | `safety_plans` collection |

A `SafetyCenterPlan` may *reference* a case (`case_id`) and research
(`research_refs`) without copying their contents.

### The honesty boundary in the schema

`PlanStep.origin` is the most important field in this phase:

```
user                 she wrote it
accepted_suggestion  HerWay suggested it, she explicitly accepted it
suggested            HerWay suggested it, she has not decided
```

Suggestions live in `plan.suggestions`, **not** `plan.steps`. Until she accepts
one it is not part of her plan and the UI shows it separately. When she rewrites
a suggestion, `user_edited_text` holds her wording and `original_suggestion`
keeps the provenance — her phrasing is what the plan displays, because the words
someone chooses for their own safety plan matter.

---

## 3. Persistence — what is and is not verified

Everything goes through `backend.db.get_database()`, the same abstraction cases
use. That is deliberate: it inherits the in-memory fallback, the loud warning,
and the production guard that refuses the fallback when `HERWAY_ENV=production`.

> **Persistence is UNVERIFIED.** No MongoDB was reachable in this environment.
> Every test ran against the in-memory fallback, where a plan is lost on
> restart. The code is written against the real PyMongo API, but *"the tests
> pass"* is not evidence that a woman's safety plan survives a restart in
> production. Proving that requires a real `mongod` and one
> create → restart → reload cycle.

**No claim is made that data is encrypted at rest.** Nothing in this repository
configures storage encryption, and asserting it would be false.

Collections: `safety_plans`, `trusted_contacts`, `check_ins`.

---

## 4. Authorization

Every repository method takes an `owner_id` and filters on it. There is
deliberately **no** "get by id" that omits the owner — such a function is one
call site away from leaking a safety plan.

Unauthorised access returns **404, not 403**: confirming that a plan exists but
belongs to someone else is itself a disclosure.

Verified live against a running server with two cookie jars:

```
A creates: plan, contact, check-in
B: GET    /plans/{id}        -> 404
B: DELETE /plans/{id}        -> 404
B: PATCH  /contacts/{id}     -> 404
B: DELETE /check-ins/{id}    -> 404
B: GET    /plans             -> 0 plans
```

`DELETE /all-data` removes only the caller's records — asserted by a test where
two users hold data and one deletes.

---

## 5. Trusted contacts

```
display_name, method (phone|email|other), value?, relationship?, notes?,
enabled, contact_has_consented = False (permanently)
```

**A saved contact has agreed to nothing.** They are not notified when added,
have no account, and `contact_has_consented` cannot become true because HerWay
has no mechanism to obtain their consent. The contacts list response carries:

> *"Saving someone here does not tell them. They have not agreed to be part of a
> safety plan — if you want them to know, ask them yourself."*

**Phone validation is deliberately permissive.** Indian numbers appear as
`+91XXXXXXXXXX`, `0XXXXXXXXXX`, bare, with spaces or hyphens, and landlines have
STD codes of varying length; users also save family abroad. Rejecting a real
number someone needs in an emergency is far worse than storing an odd one, so
validation checks shape, not conformance to one national format. Six formats are
tested, including UK and US.

Deleting a contact **detaches it from every plan** that referenced it, so a
deleted person cannot linger in a plan's contact list.

Contact details never reach the logs — repository logging records
`method=phone`, never the name or number.

---

## 6. Check-in lifecycle

```
                 start
                   │
                 ACTIVE ──── user: "I'm safe" ──► COMPLETED_SAFE
                   │   └──── user: cancel ──────► CANCELLED
                   │
                   └── expected time passes ──► is_overdue() == True
                                                 (a derived status.
                                                  Nothing is sent.
                                                  Nobody is alerted.)
```

- `expected_back_at` **must be timezone-aware**; a naive datetime is rejected
  with 422 rather than assumed to be server time, which would make a check-in
  overdue at the wrong moment for the user.
- `OVERDUE` cannot be set by a client — the API rejects it with 422. It is
  derived from the clock on read.
- There is no background timer, by design. A fragile in-memory timer presented
  as monitoring is exactly what Task 5 forbids.

---

## 7. Sharing

`POST /api/v2/safety-center/share-draft` returns a `ShareDraft`:

```
message, recipient_name?, recipient_value?,
wa_me_url?, sms_url?, mailto_url?,
delivery_guarantee = "none",
notice = "Nothing has been sent..."
```

Defaults chosen for safety:

| | Default | Reason |
|---|---|---|
| Destination | **excluded** | Opt-in per message |
| Precise location | **excluded** | Opt-in per message, never automatic |
| Plan steps | **never included** | Steps can hold details she has not chosen to share — only the plan *title* goes out |
| Case contents | **never included** | — |

The UI shows the full message and recipient before anything opens, and a Cancel
button beside the send links.

---

## 8. Structured action workflow

`backend/services/action_workflow.py` — a deterministic presentation layer over
the existing `action_planner`, not a replacement.

Buckets: **do now · next · alternatives · save · share · limitations**.

Three rules enforced in code, not prompt wording:

1. **Confrontation is filtered out of every step regardless of origin.** Eight
   phrasings are matched (`confront`, `tell him you know`, `stand up to them`,
   `demand an apology`…). Telling someone to confront a person who may hurt them
   is the most dangerous output this product could produce, and a model can
   phrase it many ways.
2. **Proportionality.** `do_now` is capped at 3 and `next` at 5. A simple
   question gets one step, not a programme.
3. **Reporting is never mandatory.** Only immediate-safety steps are
   `optional=False`; no code path makes going to the police non-optional.

`emergency_fallback()` is **pure Python** — no LLM, no search, no database. It
returns concrete steps (move to people, 112, 181, SMS to 112, ERSS panic button)
and states plainly that HerWay cannot call anyone or tell anyone where she is.
It makes no promise about response times. A test strips every credential from
the environment and asserts the guidance is still produced.

---

## 9. Integration with cases and research

- `SafetyCenterPlan.case_id` and `research_refs` are **references, not copies**.
- Linking requires an explicit request; nothing is linked automatically, and an
  everyday safety question never becomes an incident.
- Case access control is untouched — a plan referencing a case grants no access
  to it.
- A dangling reference (deleted or archived case) leaves the plan fully usable;
  the id simply resolves to nothing.
- `ResolvedResource.to_dict()` from Phase 3 is directly saveable as a plan step
  with its `source_urls` preserved — tested.

---

## 10. Tests

| Suite | Result |
|---|---|
| **Backend total** | **551 passed**, 0 failed, 0 skipped (~56s) |
| ├─ pre-Phase-4 | 451 passed, unmodified |
| ├─ `test_safety_center.py` | **62** new |
| └─ `test_action_workflow.py` | **38** new |
| Frontend `tsc --noEmit` | clean |
| Frontend `next lint` | clean |

### Mocked vs real

**Mocked / in-memory (everything except below):** all persistence runs on the
in-memory fallback. No MongoDB, no messaging provider, no LLM.

**Real:** the live cross-user authorization check in §4, run against a running
uvicorn with two independent cookie jars, and the live share-draft check showing
`delivery_guarantee: none` with a correctly-formed `wa.me` link.

### Coverage against Task 10

| # | Required | Covered |
|---|---|---|
| 1 | Plan CRUD | ✅ |
| 2 | Existing safety-plan compatibility | ✅ (untouched; 451 prior tests pass) |
| 3 | Action-plan schema | ✅ |
| 4 | User approval of suggestions | ✅ |
| 5 | Contact CRUD | ✅ |
| 6 | Cross-user authorization | ✅ unit **and live** |
| 7 | Check-in lifecycle | ✅ |
| 8 | Timezone handling | ✅ naive rejected |
| 9 | Missed check-in behaviour | ✅ derived, no false alert |
| 10 | Sharing + confirmation | ✅ |
| 11 | Emergency independent of LLM/search | ✅ credentials stripped |
| 12 | Case/research references | ✅ |
| 13 | Missing infrastructure | ✅ in-memory fallback |
| 14 | Frontend states | ⚠️ loading/empty/error states implemented and type-checked; **no automated frontend tests** — the repo has no frontend test runner |
| 15 | Chat/dashboard regression | ✅ 451 prior tests pass |

---

## 11. Files changed

**New (6)**

```
backend/models/safety_center.py                 plans, contacts, check-ins, sharing
backend/services/safety_center_repository.py    owner-scoped persistence
backend/services/action_workflow.py             structured steps + emergency fallback
backend/routes/safety_center.py                 14 endpoints
backend/tests/test_safety_center.py             62 tests
backend/tests/test_action_workflow.py           38 tests
frontend/src/app/safety-center/page.tsx         Safety Center UI
docs/PHASE4_IMPLEMENTATION_REPORT.md            this document
```

**Modified (3)**

```
backend/main.py                      mounted the safety-center router
frontend/src/lib/api.ts              added apiDelete
frontend/src/components/Navbar.tsx   "Safety Center" link
```

**Deleted: 0. Endpoints removed: 0. Features removed: 0.**

---

## 12. Remaining limitations

1. **Persistence unverified** (the big one). No MongoDB was reachable; all tests
   used the in-memory fallback.
2. **No encryption-at-rest claim** — nothing configures it.
3. **No message delivery.** A paid provider was deliberately not added to make
   the UI look complete. If one is introduced later, `ShareDraft` already has the
   shape to carry real delivery status.
4. **No background scheduling**, so no server-side check-in reminders.
5. **No automated frontend tests** — no runner exists in the repo.
6. **Clerk unverified**, so Safety Center records are keyed to anonymous browser
   sessions. **A user who clears cookies loses access to their plans.** This is
   the most user-visible consequence of the unverified auth stack.
7. Carried forward: legal RAG broken, Gemini quota exhausted, no CI, per-process
   rate limiting.

---

## 13. Recommended starting point for Phase 5

Phase 5 is *Incident Workspace and Private Evidence Management* — the highest
privacy stakes in the project. Evidence may be the only record of abuse **and**
dangerous if exposed.

**Do not start with the evidence model. Start by resolving two prerequisites:**

1. **Prove persistence** (unchanged from the Phase 3 recommendation, now more
   urgent). Evidence that silently vanishes on restart is worse than no evidence
   feature, because a woman may discard the original believing it is stored.
2. **Write the retention and deletion policy before any code.** Phase 5 requires
   that deletion be real rather than a soft flag, which is a storage-design
   decision — not something to retrofit.

Then reuse `SafetyCenterRepository`'s owner-scoping pattern verbatim: the
`_owned_plan` / 404-not-403 idiom and the `delete_all_for_owner` behaviour are
exactly what evidence needs, and the cross-user test matrix in
`test_safety_center.py` is directly adaptable.
