"""
EmbeddingService — thin wrapper around existing Haven embedding utilities.

Reuses:
  - backend.utils.embedding.generate_text_embedding  (Gemini text-embedding-004)
  - backend.utils.embedding.find_top_matches         (MongoDB Atlas $vectorSearch)
  - backend.db.get_database                          (existing SheBuilds connection)

DO NOT rebuild the embedding logic — call the existing functions directly.
This service is invoked by ChatAgent's ``invoke_lawbot`` and
``search_community`` tools.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.db import get_database
from backend.utils.embedding import find_top_matches, generate_text_embedding
from backend.utils.common import serialize_object_id

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Wraps the existing Haven RAG infrastructure for reuse by agents."""

    # ------------------------------------------------------------------ #
    # Legal / Document RAG (LawBot capability)
    # ------------------------------------------------------------------ #

    def search_legal_docs(
        self,
        query: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Vector-search the ``doc_embedding`` collection using the existing
        ``generate_text_embedding`` + ``find_top_matches`` pipeline.

        Returns a list of dicts with 'filename', 'content' (preview), and
        similarity score metadata.
        """
        db = get_database()
        if db is None:
            logger.warning("EmbeddingService.search_legal_docs: DB unavailable")
            return []

        try:
            query_vector = generate_text_embedding(query)
            collection = db["doc_embedding"]
            results = find_top_matches(
                collection, query_vector, num_results=top_k, num_candidates=50
            )
            return [serialize_object_id(r) for r in results]
        except Exception as exc:
            logger.error("EmbeddingService.search_legal_docs failed: %s", exc)
            return []

    # ------------------------------------------------------------------ #
    # Community / culprit matching
    # ------------------------------------------------------------------ #

    def search_community_posts(
        self,
        query: str,
        collection_name: str = "admin",
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Find top community posts whose culprit_embedding is closest to the
        embedded query string.  Uses the existing Haven ``find_top_matches``
        MongoDB Atlas vector search.

        Falls back to a text-based ``find`` if vector search is unavailable
        (e.g., index not yet created).
        """
        db = get_database()
        if db is None:
            logger.warning("EmbeddingService.search_community_posts: DB unavailable")
            return []

        try:
            query_vector = generate_text_embedding(query)
            collection = db[collection_name]
            results = find_top_matches(
                collection, query_vector, num_results=top_k, num_candidates=50
            )
            return [serialize_object_id(r) for r in results]
        except Exception as exc:
            # Graceful fallback — return most-recent posts without vector search
            logger.warning(
                "EmbeddingService: vector search unavailable (%s), falling back to recency sort",
                exc,
            )
            try:
                fallback = list(db[collection_name].find().sort("_id", -1).limit(top_k))
                return [serialize_object_id(r) for r in fallback]
            except Exception as exc2:
                logger.error("EmbeddingService fallback also failed: %s", exc2)
                return []
