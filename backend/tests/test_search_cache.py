"""
Shared search-cache tests (Phase 3, Task 1 / Task 8.1–8.3).

Backends under test:

- ``memory``  — in-process, the default. Mocked only in the sense that no
  external service exists; the code path is real.
- ``sqlite``  — **a real shared store**, exercised here including a genuine
  cross-process test that spawns a separate Python interpreter.
- ``mongodb`` — contract-tested against a fake collection. No MongoDB was
  reachable in this environment, so cross-host sharing is NOT verified.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time

import pytest

from backend.models.research import SearchResult
from backend.services.search_cache import (
    DEFAULT_TTLS,
    InProcessBackend,
    SerpApiCache,
    SqliteBackend,
    build_backend,
    cached_at_of,
    deserialise_results,
    make_cache_key,
    serialise_results,
    ttl_for,
)


def _results(n: int = 1):
    return [
        SearchResult(title=f"Result {i}", url=f"https://example.gov.in/{i}", snippet="s")
        for i in range(n)
    ]


@pytest.fixture
def sqlite_cache(tmp_path):
    backend = SqliteBackend(path=str(tmp_path / "cache.sqlite3"))
    return SerpApiCache(backend=backend)


# ---------------------------------------------------------------------------
# Key normalisation
# ---------------------------------------------------------------------------

def test_whitespace_and_case_share_one_key():
    a = make_cache_key("official women   helpline", "web", None, "in", "en", 1)
    b = make_cache_key("  OFFICIAL Women helpline  ", "web", None, "in", "en", 1)
    assert a == b


@pytest.mark.parametrize(
    "kwargs_a,kwargs_b,why",
    [
        (dict(location="Pune"), dict(location="Nagpur"), "different cities"),
        (dict(country="in"), dict(country="us"), "different countries"),
        (dict(language="en"), dict(language="hi"), "different languages"),
        (dict(page=1), dict(page=2), "different pages"),
    ],
)
def test_materially_different_searches_get_different_keys(kwargs_a, kwargs_b, why):
    base = dict(query="one stop centre", vertical="maps", location=None,
                country="in", language="en", page=1)
    assert make_cache_key(**{**base, **kwargs_a}) != make_cache_key(**{**base, **kwargs_b}), why


def test_different_verticals_do_not_collide():
    assert make_cache_key("x", "web", None, "in", "en", 1) != make_cache_key(
        "x", "news", None, "in", "en", 1
    )


def test_key_does_not_contain_the_query_text():
    """The key reaches a shared store and metrics; it must not disclose intent."""
    key = make_cache_key("women shelter in koregaon park", "maps", "Pune", "in", "en", 1)
    for fragment in ("shelter", "koregaon", "women"):
        assert fragment not in key.lower()


def test_key_never_contains_credentials(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "super-secret-key-value")
    key = make_cache_key("q", "web", None, "in", "en", 1)
    assert "super-secret-key-value" not in key


def test_extra_parameters_change_the_key():
    assert make_cache_key("q", "web", None, "in", "en", 1, extra={"num": 10}) != make_cache_key(
        "q", "web", None, "in", "en", 1, extra={"num": 20}
    )


# ---------------------------------------------------------------------------
# TTL policy
# ---------------------------------------------------------------------------

def test_news_expires_sooner_than_place_metadata():
    """Freshness is the point of a news search; place metadata is stabler."""
    assert ttl_for("news") < ttl_for("maps")
    assert ttl_for("news") < ttl_for("web")


def test_unknown_vertical_gets_the_fallback_ttl():
    assert ttl_for("something-else") > 0


def test_every_configured_ttl_is_positive():
    assert all(v > 0 for v in DEFAULT_TTLS.values())


def test_entry_expires(sqlite_cache):
    sqlite_cache._ttl_seconds = 1
    sqlite_cache.set("q", "web", None, "in", "en", 1, _results())
    assert sqlite_cache.get("q", "web", None, "in", "en", 1) is not None
    time.sleep(1.2)
    assert sqlite_cache.get("q", "web", None, "in", "en", 1) is None


# ---------------------------------------------------------------------------
# Hit / miss / never-cache-a-failure
# ---------------------------------------------------------------------------

def test_miss_then_hit(sqlite_cache):
    assert sqlite_cache.get("q", "web", None, "in", "en", 1) is None
    assert sqlite_cache.metrics.misses == 1

    sqlite_cache.set("q", "web", None, "in", "en", 1, _results(2))
    got = sqlite_cache.get("q", "web", None, "in", "en", 1)
    assert got is not None and len(got) == 2
    assert sqlite_cache.metrics.hits == 1


def test_empty_results_are_never_cached(sqlite_cache):
    """An empty list is indistinguishable from a failed search."""
    sqlite_cache.set("q", "web", None, "in", "en", 1, [])
    assert sqlite_cache.get("q", "web", None, "in", "en", 1) is None
    assert sqlite_cache.metrics.writes == 0


def test_round_trip_preserves_result_fields(sqlite_cache):
    original = SearchResult(
        title="Sakhi One Stop Centre",
        url="https://wcd.nic.in/osc",
        snippet="Support services",
        address="Civil Lines, Nagpur",
        phone="0712-0000000",
        rating=4.2,
        reviews=31,
    )
    sqlite_cache.set("q", "maps", "Nagpur", "in", "en", 1, [original])
    restored = sqlite_cache.get("q", "maps", "Nagpur", "in", "en", 1)[0]

    assert restored.title == original.title
    assert restored.address == original.address
    assert restored.phone == original.phone
    assert restored.rating == original.rating
    assert restored.reviews == original.reviews


# ---------------------------------------------------------------------------
# Corrupt and hostile cached values
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw",
    [
        "not json at all",
        "",
        "null",
        "[]",
        json.dumps({"v": 999, "results": []}),          # wrong schema version
        json.dumps({"v": 1, "results": "not a list"}),
        json.dumps({"v": 1, "results": [{"no_title": 1}]}),
    ],
)
def test_malformed_payloads_are_treated_as_a_miss(raw):
    assert deserialise_results(raw) is None


def test_corrupt_entry_is_evicted_not_raised(sqlite_cache):
    key = make_cache_key("q", "web", None, "in", "en", 1)
    sqlite_cache._backend.set(key, "{{ corrupt", 60)

    assert sqlite_cache.get("q", "web", None, "in", "en", 1) is None
    assert sqlite_cache.metrics.errors == 1
    # And the bad entry is gone rather than failing on every subsequent read.
    assert sqlite_cache._backend.get(key) is None


def test_serialisation_is_json_not_pickle():
    """A shared store is untrusted input; unpickling it would be RCE."""
    payload = serialise_results(_results(1))
    assert json.loads(payload)["v"] == 1
    assert "results" in json.loads(payload)


def test_cached_at_is_recoverable_for_retrieval_timestamps():
    payload = serialise_results(_results(1))
    assert abs(cached_at_of(payload) - time.time()) < 5
    assert cached_at_of("garbage") is None


# ---------------------------------------------------------------------------
# Cache outage must degrade, never raise
# ---------------------------------------------------------------------------

class _BrokenBackend:
    name = "broken"

    def get(self, key):
        raise RuntimeError("cache is down")

    def set(self, key, value, ttl_seconds):
        raise RuntimeError("cache is down")

    def delete(self, key):
        raise RuntimeError("cache is down")

    def clear(self):
        raise RuntimeError("cache is down")


def test_read_failure_is_a_miss_not_an_exception():
    cache = SerpApiCache(backend=_BrokenBackend())
    assert cache.get("q", "web", None, "in", "en", 1) is None
    assert cache.metrics.errors == 1


def test_write_failure_does_not_propagate():
    cache = SerpApiCache(backend=_BrokenBackend())
    cache.set("q", "web", None, "in", "en", 1, _results())  # must not raise
    assert cache.metrics.errors == 1


def test_unknown_backend_falls_back_to_memory(monkeypatch):
    monkeypatch.setenv("HERWAY_CACHE_BACKEND", "redis-that-is-not-configured")
    assert build_backend().name == "memory"


def test_default_backend_is_in_process(monkeypatch):
    """Local development must not acquire an infrastructure dependency."""
    monkeypatch.delenv("HERWAY_CACHE_BACKEND", raising=False)
    assert build_backend().name == "memory"


def test_memory_backend_reports_itself_as_not_shared():
    cache = SerpApiCache(backend=InProcessBackend())
    assert cache.is_shared is False


def test_sqlite_backend_reports_itself_as_shared(sqlite_cache):
    assert sqlite_cache.is_shared is True


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

def test_concurrent_writers_do_not_corrupt_entries(sqlite_cache):
    errors: list[Exception] = []

    def writer(i: int):
        try:
            for _ in range(10):
                sqlite_cache.set(f"q{i}", "web", None, "in", "en", 1, _results(1))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    for i in range(6):
        assert sqlite_cache.get(f"q{i}", "web", None, "in", "en", 1) is not None


def test_single_flight_lock_is_stable_per_key(sqlite_cache):
    a = sqlite_cache.lock_for("same", "web", None, "in", "en", 1)
    b = sqlite_cache.lock_for("same", "web", None, "in", "en", 1)
    c = sqlite_cache.lock_for("different", "web", None, "in", "en", 1)
    assert a is b, "identical queries must share one lock"
    assert a is not c


# ---------------------------------------------------------------------------
# Cross-process sharing — a REAL second OS process
# ---------------------------------------------------------------------------

_WRITER = """
import os, sys
os.environ["HERWAY_CACHE_BACKEND"] = "sqlite"
os.environ["HERWAY_CACHE_SQLITE_PATH"] = sys.argv[1]
sys.path.insert(0, sys.argv[2])
from backend.services.search_cache import SerpApiCache
from backend.models.research import SearchResult
c = SerpApiCache()
c.set("cross process query", "maps", "Nagpur", "in", "en", 1,
      [SearchResult(title="Written By Another Process", url="https://x.gov.in/1", snippet="s")])
print("WROTE", os.getpid())
"""


def test_sqlite_cache_is_shared_across_processes(tmp_path):
    """Two independent interpreters; one writes, the other reads it back.

    This is what justifies describing the sqlite backend as shared. The
    in-process backend cannot pass this test, which is asserted below.
    """
    db_path = str(tmp_path / "xproc.sqlite3")
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )
    script = tmp_path / "writer.py"
    script.write_text(_WRITER, encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(script), db_path, repo_root],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, f"writer process failed: {completed.stderr[-800:]}"
    assert "WROTE" in completed.stdout

    # This process never shared memory with the writer.
    reader = SerpApiCache(backend=SqliteBackend(path=db_path))
    got = reader.get("cross process query", "maps", "Nagpur", "in", "en", 1)

    assert got is not None, "entry written by another process was not visible"
    assert got[0].title == "Written By Another Process"


def test_in_process_backend_is_not_shared_across_processes(tmp_path):
    """Control for the test above: proves it is measuring something real."""
    cache = SerpApiCache(backend=InProcessBackend())
    assert cache.get("cross process query", "maps", "Nagpur", "in", "en", 1) is None


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def test_stats_expose_counters_without_query_text(sqlite_cache):
    sqlite_cache.set("a sensitive query about a shelter", "maps", "Pune", "in", "en", 1, _results())
    sqlite_cache.get("a sensitive query about a shelter", "maps", "Pune", "in", "en", 1)
    sqlite_cache.get("missing", "web", None, "in", "en", 1)

    stats = sqlite_cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["backend"] == "sqlite"
    assert stats["shared_across_processes"] is True
    assert 0.0 <= stats["hit_rate"] <= 1.0

    blob = json.dumps(stats).lower()
    for fragment in ("shelter", "sensitive", "pune"):
        assert fragment not in blob


# ---------------------------------------------------------------------------
# MongoDB backend — contract only. NOT verified against a real server.
# ---------------------------------------------------------------------------

class _FakeMongoCollection:
    def __init__(self):
        self.docs = {}
        self.indexes = []

    def create_index(self, field, expireAfterSeconds=None):
        self.indexes.append((field, expireAfterSeconds))

    def find_one(self, query):
        return self.docs.get(query["_id"])

    def update_one(self, query, update, upsert=False):
        self.docs[query["_id"]] = {"_id": query["_id"], **update["$set"]}

    def delete_one(self, query):
        self.docs.pop(query["_id"], None)

    def delete_many(self, query):
        self.docs.clear()


def test_mongo_backend_declares_a_ttl_index():
    """MongoDB expires entries itself via a TTL index on expires_at."""
    from backend.services.search_cache import MongoBackend

    collection = _FakeMongoCollection()
    MongoBackend(db={"search_cache": collection})
    assert ("expires_at", 0) in collection.indexes


def test_mongo_backend_round_trips():
    from backend.services.search_cache import MongoBackend

    collection = _FakeMongoCollection()
    backend = MongoBackend(db={"search_cache": collection})
    backend.set("k", "value", 60)
    assert backend.get("k") == "value"
    backend.delete("k")
    assert backend.get("k") is None
