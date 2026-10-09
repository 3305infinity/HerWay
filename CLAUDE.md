# CLAUDE.md

Working notes for HerWay — a women's safety and support platform for users in
India. FastAPI backend, Next.js 15 frontend.

Read `docs/` for depth: `EXISTING_ARCHITECTURE_AUDIT.md` (what is verified vs
unproven), `KNOWN_ISSUES.md` (live register), and the per-phase reports.

---

## Running it — the traps that cost real time

### `.env` resolution depends on your working directory

`python-dotenv` searches upward from the **CWD**, and this repo has two `.env`
files with different contents:

| Run from | Loads | Has real keys? |
|---|---|---|
| `backend/` | `backend/.env` | **yes** |
| repo root | `.env` | no — template copy, keys blank |

```bash
cd backend && uvicorn main:app --reload --port 8000     # correct for this setup
```

Starting from the repo root gives a backend with **no Gemini and no SerpApi
key**, and the only symptom is features reporting outages. `GET /health` shows
which integrations actually came up.

> The README said to run from the root for a long time. It was wrong. If you
> change this, change both.

### Use the venv interpreter explicitly

System Python does not have the dependencies (`No module named 'jwt'`).

```bash
./backend/.venv/Scripts/python.exe -m pytest backend/tests -q     # Windows
```

### Never disturb a running dev server

Two rules, both learned the hard way:

1. **Do not run `npm run build` while `npm run dev` is running.** They share
   `frontend/.next/`; the production build replaces the dev chunks the running
   server is serving. Symptom: `ChunkLoadError: Loading chunk app/<route>/page
   failed`.
2. **Do not start a second dev server.** Next falls back to port 3001 when 3000
   is taken, and both write to the same `.next/`. Same symptom.

To verify a build without touching a running server, build into a separate
output directory. **`next build` has no `--distDir` flag** — it is a
`next.config.ts` option, wired here to an env var:

```bash
NEXT_DIST_DIR=.next-verify npx next build && rm -rf .next-verify
```

Check for two servers before assuming a build is broken:

```bash
netstat -ano | grep -E ":300[01] " | grep LISTENING
```

Two listeners means they are overwriting each other's chunks. A browser
`ChunkLoadError` almost always means this, not a compile failure — confirm with
an actual build before changing any code.

If `.next` does get corrupted: stop every Node process, `rm -rf .next`, start
one server, hard-reload the browser.

Deleting `.next` while a server runs also makes routes 404 transiently — the
server answers but has no manifest. A 404 *with* a response time is this, not a
missing route.

### Windows notes

- `[WinError 10013]` on a port usually means **in use**, not a permissions
  problem: `netstat -ano | findstr :8000` then `taskkill /PID <pid> /F`.
- Python `pathlib` cannot write to `/tmp` — use a path in the repo.
- Clean up any server you start. Leaving one on :3000 or :8000 blocks the user.

---

## Validation

```bash
./backend/.venv/Scripts/python.exe -m pytest backend/tests -q
cd frontend && npx tsc --noEmit && npm run lint
```

551 backend tests. **Almost all are offline/mocked** — a green run does not
demonstrate that Gemini, MongoDB or Atlas work. Say so when reporting results.

Genuinely real: the cross-process cache test (spawns a second interpreter) and
any live SerpApi smoke test you deliberately run.

---

## Product invariants

These are enforced in code and asserted by tests. Breaking one is a product
failure, not a style regression.

**Never invent a fact.** No phone number, address, section number or deadline
unless it came from a source. When research fails, say so — never answer from
model memory. `search_legal_docs` returning `[]` is ambiguous (no match *or*
retrieval down); LawBot falls through to live official sources for this reason.

**Never claim a place is safe.** Search results cannot establish it. There is no
safety-score field anywhere; comparisons carry no overall ranking; review
sentiment is never a verdict; absence of bad news is not evidence of safety.

**Show provenance.** Every resource is `official_source`, `likely_official` or
`unverified_listing`. A map pin is never shown as a confirmed service.

**Attempted ≠ completed.** `AgentExecution` distinguishes proposed → attempted →
completed. Never tell a user something was done when it was only tried.

**Emergency paths never depend on a provider.** `safety_triage.py` is pure
Python — no LLM, no search, no database. Urgency may only be raised, never
lowered. Emergency UI (112/181/1091, Quick Exit) **must not animate in**; it
renders immediately.

**Never suggest confronting the person causing harm.** `action_workflow.py`
filters this from every step regardless of origin.

**Honest capability claims.** Check-ins are not monitored (no background
execution exists). Sharing does not deliver (no SMS/WhatsApp provider).
Steganography is not encryption. Quick Exit cannot erase history. Saving a
trusted contact does not notify them.

**Server decides identity.** No endpoint accepts a caller-supplied `user_id`.
Safety Center records return **404** not 403 for non-owners — confirming
someone else's safety plan exists is itself a disclosure.

**No user content in logs.** Not messages, locations, case contents, contact
details or search queries. Use `log_fields()` from `backend/trace.py` — counts
and flags only.

---

## Architecture

```
backend/
  agents/      situation · chat (14 tools) · research · safety_plan · source_verifier · action_planner
  services/    llm · serpapi · search_cache · research_orchestrator · resource_resolver · place_research
  routes/      /api/v2/{cases,chat,research,discreet,resources,discover,safety-center} + legacy at root
  trace.py · safety_triage.py · rate_limit.py · auth.py · india_resources.py
```

- **`ChatAgent` is the integration layer**, not a chatbot. 14 tools wrapping
  existing capabilities. Do not rewrite it; extend it.
- **`ResearchOrchestrator` is the only research implementation.**
  `ResearchAgent` is a thin compatibility delegate — do not add a second
  pipeline.
- **`SafetyPlan`** (AI, case-embedded) and **`SafetyCenterPlan`** (user-authored,
  standalone) are different things. Both exist deliberately.

62 endpoints. Swagger at `/docs` is generated from code and always
authoritative.

---

## Frontend

Motion lives in `lib/motion.ts` and `components/motion/Reveal.tsx`. Calm by
design: nothing bouncy, nothing over 400ms, travel ≤16px. `MotionProvider` sets
`reducedMotion="user"` app-wide; `globals.css` handles the CSS half.

`apiGet/apiPost/apiPatch/apiDelete` from `lib/api.ts` return a result rather
than throwing — `result.error` is an object, use `result.error.message`.

Design: Inter + Playfair Display, rose primary, editorial rather than SaaS.
Avoid uniform card grids and repeated eyebrow→h2→paragraph→grid sections — that
sameness is what made the homepage read as generated.

---

## Unverified — do not claim otherwise

MongoDB persistence (all testing used the in-memory fallback; **data is lost on
restart**), Clerk sign-in, Atlas vector search, and any live LLM output (Gemini
free tier ~20 req/day, exhausted throughout development). LawBot retrieval is
broken: documents are stored as pickled binary, which `$vectorSearch` cannot
index.

No encryption at rest is configured. Do not claim it.
