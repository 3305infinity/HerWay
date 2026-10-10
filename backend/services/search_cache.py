"""
Shared search-result cache.

Why this exists
---------------
``SerpApiCache`` was a plain dict on the service instance. Every uvicorn worker
held its own copy, so an N-worker deployment paid for the same SerpApi query up
to N times and a restart threw the whole cache away. SerpApi is billed per
search, so that is money, and — because a cache hit is instant — it is also
latency for a woman waiting on a result.

What infrastructure this uses
-----------------------------
Nothing new is required. The repository has no Redis, Memcached or any other
shared store configured (verified), so rather than introduce a service that
local development and deployment would then depend on, this module ships three
interchangeable backends and defaults to the one that changes nothing:

==============  =================================  ==========================
Backend         Sharing                            When to use
==============  =================================  ==========================
``memory``      none — per process                 Default. Local dev, tests.
``sqlite``      across processes on **one host**   Multi-worker uvicorn on a
                                                   single machine. Needs only
                                                   a writable file path.
``mongodb``     across hosts                       Production. Reuses the
                                                   MongoDB the app already
                                                   needs; TTL index does the
                                                   expiry.
==============  =================================  ==========================

Select with ``HERWAY_CACHE_BACKEND``. An unavailable backend degrades to
in-process rather than failing a search — a cache outage must never become a
user-visible outage.

Honesty note
------------
Cross-process reuse is **verified for the sqlite backend** (two independent
Python processes, see ``backend/tests/test_search_cache.py`` and the Phase 3
report). The mongodb backend is implemented against the same contract but
**could not be verified here**: no MongoDB is reachable in this environment.

What is never cached
--------------------
Failures, empty-but-failed outcomes, and anything user-specific. A cached error
would turn one provider blip into an hour of wrong answers.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from backend.models.research import SearchResult
from backend.trace import log_fields

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TTL policy
# ---------------------------------------------------------------------------
# Different information decays at different rates. Caching a news search for an
# hour would hide a development the user needs; caching a statutory procedure
# for only a minute wastes credits on something that has not changed in years.

DEFAULT_TTLS: Dict[str, int] = {
    # Recent developments. Short — the point of a news search is freshness.
    "news": int(os.getenv("CACHE_TTL_NEWS", "900")),            # 15 min
    # Place listings: name, address, phone. Stable for hours, but opening hours
    # and "temporarily closed" status drift, so not longer than a few hours.
    "maps": int(os.getenv("CACHE_TTL_MAPS", "10800")),          # 3 h
    "local": int(os.getenv("CACHE_TTL_MAPS", "10800")),
    # General web: procedures, statutes, portal pages. Changes slowly.
    "web": int(os.getenv("CACHE_TTL_WEB", "3600")),             # 1 h
    "scholar": int(os.getenv("CACHE_TTL_WEB", "3600")),
}

FALLBACK_TTL = int(os.getenv("CACHE_TTL_DEFAULT", "3600"))


def ttl_for(vertical: Optional[str]) -> int:
    """Seconds to keep a result for ``vertical``."""
    return DEFAULT_TTLS.get((vertical or "web").strip().lower(), FALLBACK_TTL)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@dataclass
class CacheMetrics:
    """Counters only. Never a query string — these are safe to log and expose."""

    hits: int = 0
    misses: int = 0
    expiries: int = 0
    errors: int = 0
    writes: int = 0
    single_flight_waits: int = 0

    def snapshot(self) -> Dict[str, int]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "expiries": self.expiries,
            "errors": self.errors,
            "writes": self.writes,
            "single_flight_waits": self.single_flight_waits,
        }

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return round(self.hits / total, 4) if total else 0.0


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class CacheBackend(Protocol):
    """Stores an opaque string under a key with a TTL."""

    name: str

    def get(self, key: str) -> Optional[str]: ...
    def set(self, key: str, value: str, ttl_seconds: int) -> None: ...
    def delete(self, key: str) -> None: ...
    def clear(self) -> None: ...


class InProcessBackend:
    """A dict with expiry. No sharing — this is the honest default."""

    name = "memory"

    def __init__(self) -> None:
        self._store: Dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at < time.time():
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        with self._lock:
            self._store[key] = (time.time() + ttl_seconds, value)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


class SqliteBackend:
    """Cross-process cache on a single host, using only the standard library.

    SQLite in WAL mode supports concurrent readers with one writer across
    processes, which is exactly the shape of a multi-worker uvicorn deployment
    on one machine. It needs no daemon, no credentials and no new dependency —
    just a writable path.

    It does **not** span hosts. Use the mongodb backend for that.
    """

    name = "sqlite"

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or os.getenv(
            "HERWAY_CACHE_SQLITE_PATH", os.path.join(os.getcwd(), ".herway-cache.sqlite3")
        )
        self._local = threading.local()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
            # WAL is what makes concurrent cross-process access workable.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS search_cache ("
            "  key TEXT PRIMARY KEY,"
            "  value TEXT NOT NULL,"
            "  expires_at REAL NOT NULL"
            ")"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_search_cache_expiry ON search_cache(expires_at)"
        )

    def get(self, key: str) -> Optional[str]:
        conn = self._connect()
        row = conn.execute(
            "SELECT value, expires_at FROM search_cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        value, expires_at = row
        if expires_at < time.time():
            # SQLite has no TTL of its own; expire lazily on read and
            # opportunistically sweep so the file does not grow without bound.
            conn.execute("DELETE FROM search_cache WHERE expires_at < ?", (time.time(),))
            return None
        return value

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._connect().execute(
            "INSERT INTO search_cache (key, value, expires_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, expires_at=excluded.expires_at",
            (key, value, time.time() + ttl_seconds),
        )

    def delete(self, key: str) -> None:
        self._connect().execute("DELETE FROM search_cache WHERE key = ?", (key,))

    def clear(self) -> None:
        self._connect().execute("DELETE FROM search_cache")


class MongoBackend:
    """Cross-host cache in the MongoDB the application already requires.

    Expiry is delegated to a TTL index on ``expires_at`` (``expireAfterSeconds:
    0``), so MongoDB removes stale documents itself. Note the background
    reaper runs roughly once a minute, so a document can survive briefly past
    its expiry — reads therefore check the timestamp as well.

    **Not verified.** No MongoDB was reachable in the environment where this
    was written; see the Phase 3 report.
    """

    name = "mongodb"

    COLLECTION = "search_cache"

    def __init__(self, db: Any = None) -> None:
        if db is None:
            from backend.db import get_database

            db = get_database()
        self._collection = db[self.COLLECTION]
        try:
            self._collection.create_index("expires_at", expireAfterSeconds=0)
        except Exception as exc:  # pragma: no cover - needs a real server
            logger.warning(
                "Search cache: could not create the TTL index; entries will not "
                "be reaped automatically (%s)",
                exc,
            )

    def get(self, key: str) -> Optional[str]:
        doc = self._collection.find_one({"_id": key})
        if not doc:
            return None
        expires_at = doc.get("expires_at")
        if expires_at is not None and expires_at.timestamp() < time.time():
            return None
        return doc.get("value")

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        from datetime import datetime, timedelta, timezone

        self._collection.update_one(
            {"_id": key},
            {
                "$set": {
                    "value": value,
                    "expires_at": datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
                }
            },
            upsert=True,
        )

    def delete(self, key: str) -> None:
        self._collection.delete_one({"_id": key})

    def clear(self) -> None:
        self._collection.delete_many({})


def build_backend(name: Optional[str] = None) -> CacheBackend:
    """Construct the configured backend, degrading to in-process on failure."""
    choice = (name or os.getenv("HERWAY_CACHE_BACKEND", "memory")).strip().lower()

    if choice in ("memory", "", "none"):
        return InProcessBackend()

    try:
        if choice == "sqlite":
            return SqliteBackend()
        if choice in ("mongo", "mongodb"):
            return MongoBackend()
    except Exception as exc:
        # A cache that cannot start must not stop the application.
        logger.warning(
            "Search cache: backend %r unavailable, falling back to in-process (%s)",
            choice,
            exc,
        )
        return InProcessBackend()

    logger.warning("Search cache: unknown backend %r, using in-process", choice)
    return InProcessBackend()


# ---------------------------------------------------------------------------
# Key construction
# ---------------------------------------------------------------------------

def make_cache_key(
    query: str,
    vertical: Optional[str],
    location: Optional[str],
    country: Optional[str],
    language: Optional[str],
    page: int = 1,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """A normalised, non-reversible key for one search.

    Normalisation collapses whitespace and case so ``"women  helpline"`` and
    ``"Women Helpline"`` share an entry rather than costing two credits.
    Location, country, language and page are all part of the key, because a
    result for Pune is not a result for Nagpur and an English result is not a
    Hindi one.

    The query is **hashed**, not stored. The key is written to a shared store
    and appears in metrics, and a raw key would otherwise disclose that someone
    searched for, say, a women's shelter in a named district. Hashing keeps the
    cache working while making the stored key useless to a reader.

    API keys and tokens are never part of the key.
    """
    clean_query = " ".join((query or "").lower().split())
    clean_vertical = (vertical or "web").strip().lower()
    clean_location = " ".join((location or "").lower().split())
    clean_country = (country or "in").strip().lower()
    clean_language = (language or "en").strip().lower()

    material = "|".join(
        [
            clean_vertical,
            clean_query,
            clean_location,
            clean_country,
            clean_language,
            str(page or 1),
            json.dumps(extra or {}, sort_keys=True, default=str),
        ]
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    # Vertical kept in the clear so entries can be reasoned about and swept by
    # type; it discloses nothing about the user.
    return f"serp:{clean_vertical}:{digest}"


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------
# JSON, never pickle. Cached values come from a shared store that other
# processes write to; unpickling such a value would be arbitrary code execution.

_SCHEMA_VERSION = 1


def serialise_results(results: List[SearchResult]) -> str:
    return json.dumps(
        {
            "v": _SCHEMA_VERSION,
            "cached_at": time.time(),
            "results": [r.model_dump(mode="json") for r in results],
        }
    )


def deserialise_results(raw: str) -> Optional[List[SearchResult]]:
    """Parse a cached payload, returning ``None`` if it is unusable.

    Anything malformed, truncated, of a different schema version, or written by
    an older build is treated as a miss. A corrupt entry must never surface as
    a result or raise into the request path.
    """
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None

    if not isinstance(payload, dict) or payload.get("v") != _SCHEMA_VERSION:
        return None

    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        return None

    try:
        return [SearchResult.model_validate(item) for item in raw_results]
    except Exception:
        return None


def cached_at_of(raw: str) -> Optional[float]:
    """When the payload was written, for retrieval timestamps in the UI."""
    try:
        value = json.loads(raw).get("cached_at")
        return float(value) if value is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# The cache
# ---------------------------------------------------------------------------

class SerpApiCache:
    """Search-result cache with a pluggable, optionally shared backend.

    The ``get``/``set`` signatures are unchanged from the original in-memory
    implementation, so ``SerpApiService`` and its tests work untouched.
    """

    def __init__(
        self,
        ttl_seconds: Optional[int] = None,
        backend: Optional[CacheBackend] = None,
    ) -> None:
        #: Kept for callers that passed an explicit TTL. When ``None`` the
        #: per-vertical policy in ``DEFAULT_TTLS`` applies instead.
        self._ttl_seconds = ttl_seconds
        self._backend: CacheBackend = backend or build_backend()
        self.metrics = CacheMetrics()
        #: One lock per in-flight key, so two concurrent identical requests in
        #: the same process result in one provider call rather than two.
        self._inflight: Dict[str, threading.Lock] = {}
        self._inflight_guard = threading.Lock()

    @property
    def backend_name(self) -> str:
        return getattr(self._backend, "name", "unknown")

    @property
    def is_shared(self) -> bool:
        """Whether this backend is visible to other processes."""
        return self.backend_name in ("sqlite", "mongodb")

    def _ttl(self, vertical: Optional[str]) -> int:
        return self._ttl_seconds if self._ttl_seconds is not None else ttl_for(vertical)

    def _make_key(
        self,
        query: str,
        vertical: str,
        location: Optional[str],
        country: Optional[str],
        language: Optional[str],
        page: int,
    ) -> str:
        """Key for one search.

        Retained with its original name and signature because existing tests
        call it directly to assert that whitespace and case variants collapse
        onto one entry. Delegates to :func:`make_cache_key`.
        """
        return make_cache_key(query, vertical, location, country, language, page)

    # -- public API (unchanged signatures) --------------------------------

    def get(
        self,
        query: str,
        vertical: str,
        location: Optional[str],
        country: Optional[str],
        language: Optional[str],
        page: int = 1,
    ) -> Optional[List[SearchResult]]:
        key = make_cache_key(query, vertical, location, country, language, page)
        try:
            raw = self._backend.get(key)
        except Exception as exc:
            # A broken cache is a miss, never an error for the caller.
            self.metrics.errors += 1
            logger.warning(
                "Search cache read failed %s",
                log_fields(backend=self.backend_name, reason=type(exc).__name__),
            )
            return None

        if raw is None:
            self.metrics.misses += 1
            return None

        results = deserialise_results(raw)
        if results is None:
            # Corrupt or stale-schema entry: drop it and treat as a miss.
            self.metrics.errors += 1
            self.metrics.misses += 1
            try:
                self._backend.delete(key)
            except Exception:
                pass
            return None

        self.metrics.hits += 1
        logger.info(
            "Search cache HIT %s",
            log_fields(
                backend=self.backend_name, vertical=vertical, cached_results=len(results)
            ),
        )
        return results

    def cached_at(
        self,
        query: str,
        vertical: str,
        location: Optional[str],
        country: Optional[str],
        language: Optional[str],
        page: int = 1,
    ):
        """When this entry was originally written, or ``None``.

        Lets a cache hit report the real fetch time rather than the time of the
        request that happened to read it — otherwise hour-old data is presented
        as seconds old, which is precisely the kind of quiet inaccuracy this
        product cannot afford.
        """
        from datetime import datetime, timezone

        key = make_cache_key(query, vertical, location, country, language, page)
        try:
            raw = self._backend.get(key)
        except Exception:
            return None
        if raw is None:
            return None
        written = cached_at_of(raw)
        return datetime.fromtimestamp(written, tz=timezone.utc) if written else None

    def set(
        self,
        query: str,
        vertical: str,
        location: Optional[str],
        country: Optional[str],
        language: Optional[str],
        page: int,
        results: List[SearchResult],
    ) -> None:
        # Never cache an empty list: it is indistinguishable from a provider
        # failure that returned nothing, and caching it would persist the
        # failure for the whole TTL.
        if not results:
            return

        key = make_cache_key(query, vertical, location, country, language, page)
        try:
            self._backend.set(key, serialise_results(results), self._ttl(vertical))
            self.metrics.writes += 1
        except Exception as exc:
            self.metrics.errors += 1
            logger.warning(
                "Search cache write failed %s",
                log_fields(backend=self.backend_name, reason=type(exc).__name__),
            )

    # -- single flight -----------------------------------------------------

    def lock_for(self, query: str, vertical: str, location: Optional[str],
                 country: Optional[str], language: Optional[str], page: int = 1):
        """A per-key lock, so duplicate concurrent searches collapse into one.

        In-process only. Two *different* workers racing on the same key will
        still each call the provider once; eliminating that needs a distributed
        lock, which is deliberately out of scope here (see the Phase 3 report).
        """
        key = make_cache_key(query, vertical, location, country, language, page)
        with self._inflight_guard:
            lock = self._inflight.get(key)
            if lock is None:
                lock = threading.Lock()
                self._inflight[key] = lock
            return lock

    def stats(self) -> Dict[str, Any]:
        """Metrics safe to log or expose. Contains no query text."""
        return {
            "backend": self.backend_name,
            "shared_across_processes": self.is_shared,
            "hit_rate": self.metrics.hit_rate,
            **self.metrics.snapshot(),
        }

    def clear(self) -> None:
        try:
            self._backend.clear()
        except Exception:
            pass
        self.metrics = CacheMetrics()
