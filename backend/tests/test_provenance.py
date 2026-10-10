"""
Search provenance tests.

The point of these fields is that a reader can tell what a result actually is:
which SerpApi engine produced it, when it was fetched, and whether it came down
the wire just now, out of the cache, or from a saved example.

The assertion that matters most is the last kind: **a snapshot must never be
reportable as live**. Everything else is detail; that one is the honesty
guarantee.

All offline — the provider is a stand-in and no billable call is made.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.models.research import (
    DataOrigin,
    ResearchTraceEntry,
    SearchOutcome,
    SearchResult,
)
from backend.services.serpapi_service import _provider_engine_for


# ---------------------------------------------------------------------------
# Engine mapping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "vertical,expected",
    [
        ("web", "google"),
        ("google_search", "google"),
        ("news", "google_news"),
        ("google_news", "google_news"),
        ("maps", "google_maps"),
        ("local", "google_maps"),
        ("google_maps", "google_maps"),
    ],
)
def test_vertical_maps_to_the_right_serpapi_engine(vertical, expected):
    assert _provider_engine_for(vertical) == expected


def test_unknown_vertical_defaults_to_google_search():
    assert _provider_engine_for("something_else") == "google"
    assert _provider_engine_for("") == "google"


def test_only_implemented_engines_are_ever_reported():
    """Reporting an engine the integration cannot call would mislead a reader."""
    implemented = {"google", "google_news", "google_maps"}
    for vertical in ("web", "news", "maps", "local", "scholar", "", "nonsense"):
        assert _provider_engine_for(vertical) in implemented


# ---------------------------------------------------------------------------
# Data origin — the honesty guarantee
# ---------------------------------------------------------------------------

def test_the_four_origins_are_distinct():
    assert len({o.value for o in DataOrigin}) == 4
    assert DataOrigin.SNAPSHOT.value == "snapshot"
    assert DataOrigin.LIVE.value == "live"


def test_snapshot_is_not_live():
    """The whole reason the enum exists rather than a boolean."""
    assert DataOrigin.SNAPSHOT is not DataOrigin.LIVE
    assert DataOrigin.SNAPSHOT.value != DataOrigin.LIVE.value


def test_a_trace_entry_defaults_to_live_not_snapshot():
    """If origin is ever forgotten, the safe default is the truthful one for a
    real search — never 'snapshot', which would mislabel real data as sample."""
    entry = ResearchTraceEntry(
        task_id="T1", why_searched="why", query="q", engine="web",
        results_found=1, time_taken_ms=10.0, success=True,
    )
    assert entry.data_origin is DataOrigin.LIVE


def test_failed_search_can_be_marked_unavailable():
    entry = ResearchTraceEntry(
        task_id="T1", why_searched="why", query="q", engine="web",
        results_found=0, time_taken_ms=5.0, success=False,
        data_origin=DataOrigin.UNAVAILABLE,
    )
    assert entry.data_origin is DataOrigin.UNAVAILABLE
    assert entry.results_found == 0


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

def test_outcome_carries_engine_and_retrieval_time():
    now = datetime.now(timezone.utc)
    outcome = SearchOutcome(
        vertical="web", query="q", success=True,
        results=[SearchResult(title="t", url="https://x.gov.in", snippet="s")],
        provider_engine="google", retrieved_at=now,
    )
    assert outcome.provider_engine == "google"
    assert outcome.retrieved_at == now


def test_cache_hit_keeps_the_original_fetch_time():
    """A cache hit stamped with 'now' would present hour-old data as fresh.

    This is the behaviour verified live against SerpApi: a repeat search
    returns from_cache=True with the timestamp of the FIRST fetch.
    """
    original = datetime.now(timezone.utc) - timedelta(hours=1)
    outcome = SearchOutcome(
        vertical="web", query="q", success=True, results=[],
        from_cache=True, provider_engine="google", retrieved_at=original,
    )
    age = datetime.now(timezone.utc) - outcome.retrieved_at
    assert age > timedelta(minutes=55), "cache hit must not claim to be fresh"


def test_trace_entry_accepts_provenance():
    now = datetime.now(timezone.utc)
    entry = ResearchTraceEntry(
        task_id="T1", why_searched="Find the POSH complaint route",
        query="posh act internal committee", engine="web",
        results_found=5, time_taken_ms=820.0, success=True,
        provider_engine="google", retrieved_at=now, data_origin=DataOrigin.LIVE,
    )
    assert entry.provider_engine == "google"
    assert entry.data_origin is DataOrigin.LIVE
    assert entry.retrieved_at == now


def test_provenance_is_optional_for_backward_compatibility():
    """Trace entries stored before these fields existed must still load."""
    entry = ResearchTraceEntry.model_validate({
        "task_id": "T1", "why_searched": "w", "query": "q", "engine": "web",
        "results_found": 2, "time_taken_ms": 100.0, "success": True,
    })
    assert entry.provider_engine is None
    assert entry.retrieved_at is None


# ---------------------------------------------------------------------------
# Cache timestamp plumbing
# ---------------------------------------------------------------------------

def test_cache_reports_when_an_entry_was_written(tmp_path):
    from backend.services.search_cache import SerpApiCache, SqliteBackend

    cache = SerpApiCache(backend=SqliteBackend(path=str(tmp_path / "c.sqlite3")))
    args = ("one stop centre pune", "maps", "Pune", "in", "en", 1)

    assert cache.cached_at(*args) is None, "nothing written yet"

    cache.set(*args, [SearchResult(title="t", url="https://x.gov.in", snippet="s")])
    written = cache.cached_at(*args)

    assert written is not None
    assert abs((datetime.now(timezone.utc) - written).total_seconds()) < 10


def test_cache_timestamp_survives_a_broken_backend():
    """A cache fault must degrade to 'unknown', not raise into the request."""
    from backend.services.search_cache import SerpApiCache

    class Broken:
        name = "broken"

        def get(self, key):
            raise RuntimeError("down")

        def set(self, key, value, ttl_seconds):
            raise RuntimeError("down")

        def delete(self, key):
            pass

        def clear(self):
            pass

    cache = SerpApiCache(backend=Broken())
    assert cache.cached_at("q", "web", None, "in", "en", 1) is None
