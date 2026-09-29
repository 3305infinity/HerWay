# Haven Architecture

## Product Vision

> "Explain what happened. Haven figures out what information matters, researches current information, verifies useful sources, finds relevant resources, and turns the result into concrete next actions."

Haven is an **information and action-planning assistant** for real-world problems. It is **not** a legal/medical authority.

## Supported Situation Categories

| Category | Examples |
|---|---|
| Consumer Complaint | defective product, refund denial |
| Scam / Fraud | phishing, fake seller, identity theft |
| Rental / Housing | deposit dispute, eviction, repair |
| Workplace | harassment, unpaid wages, wrongful termination |
| Education | admission issue, grade dispute, scholarship |
| Cyber Harassment | online abuse, doxxing, revenge imagery |
| Lost / Stolen Document | passport, ID, vehicle papers |
| Travel Disruption | cancelled flight, visa issue, stranded |
| Service Dispute | billing error, contract issue |
| Legal Information | understanding a law, finding precedent |
| Nearby Assistance | finding a shelter, agency, office |
| Government Procedure | confusing bureaucratic process |
| Domestic Violence | legacy support from original Haven |
| Other | anything not above |

---

## Pipeline

```
USER (free-text situation description)
  │
  ▼
┌─────────────────────────┐
│   SituationAgent        │  Structured understanding of the problem
│   (LLM-powered)         │  → Situation model
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│   ResearchAgent         │  Plans searches, then executes via SerpApi
│   (LLM + SerpApi)       │  → ResearchPlan → list[SearchResult]
└──────────┬──────────────┘
           │
           ├── Google Search
           ├── Google News
           └── Google Maps / Local
           │
           ▼
┌─────────────────────────┐
│   SourceVerifier        │  Filters, extracts, assesses confidence
│   (LLM-powered)         │  → list[EvidenceItem]
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│   ActionPlanner         │  Synthesises evidence into concrete steps
│   (LLM-powered)         │  → ActionPlan
└──────────┬──────────────┘
           │
           ▼
      Case Workspace
   (persisted in MongoDB)
```

---

## Backend Structure

```
backend/
├── main.py                    # FastAPI app, mounts all routers
│
├── agents/                    # Pipeline stage classes
│   ├── situation_agent.py     # Raw text → Situation
│   ├── research_agent.py      # Situation → ResearchPlan → SearchResults
│   ├── source_verifier.py     # SearchResults → EvidenceItems
│   └── action_planner.py      # FinalResearchReport → ActionPlan
│
├── services/                  # External integrations
│   ├── llm_service.py         # Gemini wrapper (structured output)
│   ├── serpapi_service.py      # SerpApi HTTP client
│   ├── maps_service.py        # Google Maps search + geocoding
│   └── news_service.py        # Google News search helpers
│
├── models/                    # Pydantic schemas
│   ├── case.py                # Case, CaseCreate, CaseStatus, Location
│   ├── research.py            # Situation, ResearchPlan, SearchResult,
│   │                          #   EvidenceItem, FinalResearchReport
│   └── action_plan.py         # ActionPlan, ActionItem
│
├── routes/                    # FastAPI routers
│   ├── cases.py               # /api/v2/cases    — CRUD
│   ├── research.py            # /api/v2/research — pipeline orchestration
│   ├── chat.py                # /api/v2/chat     — conversational interface
│   └── legacy.py              # /                — ALL original endpoints
│
├── utils/                     # Original utility modules (preserved)
│   ├── ai_assitant.py         # Voice AI assistant (therapy bot backend)
│   ├── common.py              # serialize_object_id, file readers
│   ├── embedding.py           # Gemini text embeddings
│   ├── regex_ptr.py           # Regex-based info extraction
│   ├── steganography.py       # Image steganography
│   ├── text_llm.py            # Gemini/Gemma text generation
│   └── twitter.py             # Twitter posting
│
├── db.py                      # MongoDB connection (preserved)
├── logger.py                  # Custom formatter (preserved)
├── prompts.py                 # Legacy prompt templates (preserved)
├── schema.py                  # Legacy Pydantic schemas (preserved)
└── docs/                      # Reference documents
```

---

## API Versioning

| Path prefix | Purpose | Status |
|---|---|---|
| `/` (root) | Legacy endpoints used by current frontend | **Preserved** — no changes |
| `/api/v2/cases` | Case CRUD | **New** |
| `/api/v2/research` | Pipeline orchestration | **New** |
| `/api/v2/chat` | Conversational assistant | **New** |
| `/health` | Health check | **New** |

The frontend continues to call its existing Next.js API routes (`/api/chat`, `/api/generate-text`, etc.), which proxy to the backend's root-level legacy endpoints. **Nothing breaks.**

---

## Key Design Decisions

### 1. No LangChain
The pipeline uses plain Python agent classes with Pydantic I/O. Each agent has:
- A single `LLMService` injected via constructor.
- A concrete `async` method with typed input and output.
- A system prompt that instructs the LLM to return structured JSON.

If LangGraph becomes genuinely useful (e.g., for retry loops or human-in-the-loop), it can be introduced for specific agents without rewriting the rest.

### 2. Services, not utilities
External integrations (Gemini, SerpApi, geocoding) live in `services/`. These are instantiated classes with methods, not bare functions. This makes them testable and mockable.

The existing `utils/` functions remain for legacy endpoints.

### 3. Typed models everywhere
Every boundary between agents uses a Pydantic model:
- `Situation` (situation_agent → research_agent)
- `ResearchPlan` (research_agent.plan → research_agent.execute)
- `SearchResult` (serpapi_service → source_verifier)
- `EvidenceItem` (source_verifier → action_planner)
- `ActionPlan` (action_planner → frontend)

### 4. Legacy preservation
All original code lives in `routes/legacy.py` and `utils/`. Nothing was deleted. The original `prompts.py` and `schema.py` remain untouched.

---

## Data Flow (MongoDB Collections)

| Collection | Purpose | Status |
|---|---|---|
| `admin` | Legacy posts/issues from the original app | **Preserved** |
| `complains2` | Legacy complaints with embeddings | **Preserved** |
| `doc_embedding` | Document embeddings | **Preserved** |
| `cases` | New Case documents | **New** |
| `research_reports` | FinalResearchReport documents | **New** |
| `action_plans` | ActionPlan documents | **New** |

---

## Migration Map: Old → New

| Old Functionality | Where It Lived | Where It Is Now | Migration Status |
|---|---|---|---|
| Post creation (InputForm) | `main.py` `/text-generation` | `routes/legacy.py` | Preserved — will map to Case creation |
| Text decomposition | `main.py` `/text-decomposition` | `routes/legacy.py` | Preserved — replaced by SituationAgent |
| Lawbot chat | Next.js `/api/chat` (Gemini direct) | `routes/chat.py` `/api/v2/chat` | New endpoint available; old route still works |
| Admin dashboard (posts list) | `main.py` `/get-admin-posts` | `routes/legacy.py` | Preserved — will evolve into Case dashboard |
| Post detail + close issue | `main.py` various | `routes/legacy.py` | Preserved |
| Image generation (Bedrock) | `main.py` `/generate-image` | `routes/legacy.py` | Preserved — to be evaluated for removal |
| Steganography | `main.py` `/encode`, `/decode` | `routes/legacy.py` | Preserved — to be evaluated for removal |
| Twitter sharing | `main.py` `/send-message` | `routes/legacy.py` | Preserved — to be evaluated for removal |
| Poem generation | `main.py` `/poem-generation` | `routes/legacy.py` | Preserved — to be evaluated for removal |
| Embedding upload | `main.py` `/upload_embeddings` | `routes/legacy.py` | Preserved |
| Therapy bot avatar | External Vercel app + `therapybot/page.tsx` | Untouched | Preserved |
| AI voice assistant | `utils/ai_assitant.py` | Untouched | Preserved |

---

## What's Next (not in this task)

1. **Frontend redesign** — new conversation-first UI with case workspace.
2. **Connect frontend** to `/api/v2/cases` and `/api/v2/research`.
3. **Add SerpApi key** configuration and test live search.
4. **Implement chat memory** with case context awareness.
5. **Add authentication middleware** to v2 routes using Clerk.
6. **Deprecate** legacy endpoints once the frontend is migrated.
