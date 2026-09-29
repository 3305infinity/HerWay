"""
NewsService — convenience wrapper for news-specific searches.

Thin layer over SerpApiService that always uses the Google News engine
and adds time-range filtering and source-preference logic.
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.models.research import SearchResult, SearchType
from backend.services.serpapi_service import SerpApiService

logger = logging.getLogger(__name__)


class NewsService:
    """News-specific search helpers."""

    def __init__(self, serpapi: SerpApiService) -> None:
        self._serpapi = serpapi

    async def search_news(
        self,
        query: str,
        location: Optional[str] = None,
        num_results: int = 10,
    ) -> list[SearchResult]:
        """Search Google News for recent articles.

        Parameters
        ----------
        query:
            The news search query.
        location:
            Optional location bias.
        num_results:
            Maximum number of results.
        """
        return await self._serpapi.search(
            query=query,
            search_type=SearchType.GOOGLE_NEWS,
            location=location,
            num_results=num_results,
        )

    async def search_topic_news(
        self,
        topic: str,
        entities: list[str],
        location: Optional[str] = None,
    ) -> list[SearchResult]:
        """Build a targeted news query from a topic and entity list.

        Combines the topic with key entities to find the most relevant
        recent coverage.
        """
        # Build a focused query: e.g. "consumer complaint Flipkart refund"
        entity_str = " ".join(entities[:3])  # Limit to avoid query bloat
        query = f"{topic} {entity_str}".strip()

        return await self.search_news(
            query=query,
            location=location,
            num_results=5,
        )
