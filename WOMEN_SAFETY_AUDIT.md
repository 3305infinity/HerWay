# Haven Women Safety & Existing Capability Audit

This document provides a comprehensive audit of Haven's existing codebase, inspecting all capabilities related to women's safety, domestic violence, harassment, mental health support, legal information, helplines, community features, and existing AI bots.

---

## 1. Feature-by-Feature Audit

### 1. Domestic Violence & Abuse Support
- **Relevant Files**:
  - `backend/routes/legacy.py` (`/text-generation`, `/save-extracted-data`)
  - `backend/models/case.py` (`CaseCategory.DOMESTIC_VIOLENCE`)
  - `backend/schema.py` (`PostInfo` model containing `duration_of_abuse`, `frequency_of_incidents`, `current_situation`, `culprit_description`)
  - `frontend/src/components/InputForm.tsx`
- **Current Implementation**: Captures abuse details (duration, frequency, situation, culprit description) and passes them to Gemini & Gemma LLMs to generate expanded support reports stored in MongoDB `admin` collection.
- **What Works**: Data collection, structured parsing, text decomposition via LLM, and persistence in MongoDB `admin` collection.
- **What Is Incomplete**: Lacks automatic live search for nearby shelters/helplines and safety-first action ordering.
- **What Can Be Improved**: Integrate with the new SerpApi research pipeline to fetch live verified helplines and shelters automatically when abuse is detected.
- **What Must NOT Be Removed**: The `PostInfo` schema, `/text-generation` endpoint, `/save-extracted-data` endpoint, and MongoDB `admin` collection.

---

### 2. Legal Information & LawBot
- **Relevant Files**:
  - `frontend/src/app/lawbot/page.tsx`
  - `backend/routes/chat.py` / `frontend/src/app/api/chat/route.ts`
  - `backend/utils/text_llm.py`
  - `backend/docs/` (legal information & IPC embeddings)
- **Current Implementation**: Interactive conversational AI chatbot pre-configured with prompt suggestions for Indian Law, IPC 320, Women Rights, and Women Safety. Uses RAG embeddings stored in MongoDB.
- **What Works**: High-quality markdown responses for legal inquiries, prompt suggestion chips, responsive UI.
- **What Is Incomplete**: The generic endpoint did not link legal advice directly to verifiable official government URLs or live SerpApi search.
- **What Can Be Improved**: Retain LawBot intact while grounding its advice in verified source links and live SerpApi legal research when requested.
- **What Must NOT Be Removed**: The `/lawbot` frontend page, prompt suggestions, and existing legal documentation embeddings.

---

### 3. Mental Health & Therapy Support (Avatar / TherapyBot)
- **Relevant Files**:
  - `frontend/src/app/therapybot/page.tsx`
  - `@avatechai/avatars/react` integration
- **Current Implementation**: Employs an interactive 3D AI avatar (`avatarId: af3f42c9-d1d7-4e14-bd81-bf2e05fd11a3`) providing empathetic conversational therapy and mental health support.
- **What Works**: Interactive 3D avatar rendering and audio/visual response interface.
- **What Is Incomplete**: Standalone avatar view; could be linked to survivor support options.
- **What Can Be Improved**: Keep TherapyBot avatar active and accessible from safety action plans for survivor emotional support.
- **What Must NOT Be Removed**: The `/therapybot` frontend page and Avatech Avatar integration.

---

### 4. Anonymous Community & Posts Workflow
- **Relevant Files**:
  - `frontend/src/app/create-post/page.tsx`
  - `frontend/src/app/post/[id]/page.tsx`
  - `frontend/src/components/InputForm.tsx`, `ImageGen.tsx`, `Share.tsx`
  - `backend/routes/legacy.py` (`/get-admin-posts`, `/get-post/{id}`, `/close-issue/{id}`)
- **Current Implementation**: Multi-step wizard allowing users to describe their situation anonymously, decompose details, generate supporting imagery, and share posts for community support and admin review.
- **What Works**: Multi-step posting pipeline, image generation, admin dashboard review, and community engagement.
- **What Is Incomplete**: Disconnect between public community posts and private research cases.
- **What Can Be Improved**: Preserve all post endpoints and community views while enabling users to convert posts into research-backed cases.
- **What Must NOT Be Removed**: `/create-post`, `/post/[id]`, `/dashboard`, `/get-admin-posts`, `/close-issue` endpoints and `admin` MongoDB collection.

---

### 5. Steganography & Discreet Information Sharing
- **Relevant Files**:
  - `backend/routes/legacy.py` (`/encode`, `/decode`)
  - `backend/utils/steganography.py`
- **Current Implementation**: Encodes sensitive text inside image files and decodes text from steganographic images, allowing discreet evidence/message transmission.
- **What Works**: Pure Python PIL image steganography encoding and decoding via HTTP endpoints.
- **What Is Incomplete**: Frontend UI exposure for discreet exit and hidden evidence storage.
- **What Can Be Improved**: Add a global Quick Exit mechanism (`Escape` key or Quick Exit button) and discreet page title formatting.
- **What Must NOT Be Removed**: `/encode` and `/decode` endpoints and `backend/utils/steganography.py`.

---

## 2. Mandatory Preservation Checklist

The following existing components are **NON-NEGOTIABLE** and must be preserved without breaking changes:
1. `backend/routes/legacy.py`: All 13 legacy API endpoints.
2. `frontend/src/app/lawbot/page.tsx`: LawBot legal assistant.
3. `frontend/src/app/therapybot/page.tsx`: Avatech 3D Therapy Avatar.
4. `frontend/src/app/create-post/page.tsx` & `frontend/src/app/post/[id]/page.tsx`: Community post creation & detail view.
5. `frontend/src/app/dashboard/page.tsx`: Admin issue dashboard.
6. MongoDB `admin` collection & Clerk authentication model.
