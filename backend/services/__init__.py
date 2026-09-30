"""Haven service layer — external integrations and shared infrastructure.

Existing services (unchanged):
  - LLMService            → llm_service.py
  - SerpApiService        → serpapi_service.py
  - MapsService           → maps_service.py
  - NewsService           → news_service.py
  - ResearchOrchestrator  → research_orchestrator.py

New thin-wrapper services (reuse existing utils, do not rebuild):
  - EmbeddingService      → embedding_service.py   (wraps utils/embedding.py)
  - ReportService         → report_service.py      (wraps utils/text_llm.py)
  - StegService           → steganography_service.py (wraps utils/steganography.py)
"""
