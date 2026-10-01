import os
import pickle
import logging  
from bson import Binary, ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient

from backend.utils.embedding import generate_text_embedding
from backend.logger import CustomFormatter

load_dotenv()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(CustomFormatter())
logger.addHandler(handler)

# ---------------------------------------------------------------------------
# In-Memory Resilient Fallback Database
# Used when MongoDB (local or Atlas) is not running or unreachable
# ---------------------------------------------------------------------------

def _matches_query(doc: dict, query: dict) -> bool:
    if not query:
        return True
    for k, v in query.items():
        doc_val = doc.get(k)
        if k == "_id":
            if str(doc_val) != str(v):
                return False
        elif isinstance(v, dict):
            for op, op_val in v.items():
                if op == "$eq" and doc_val != op_val:
                    return False
                elif op == "$ne" and doc_val == op_val:
                    return False
                elif op == "$in" and doc_val not in op_val:
                    return False
        else:
            if doc_val != v:
                return False
    return True


class _InMemoryCursor:
    def __init__(self, docs):
        self._docs = list(docs)
        self._pos = 0

    def sort(self, key_or_list, direction=1):
        if isinstance(key_or_list, list):
            for key, direct in reversed(key_or_list):
                rev = direct < 0
                self._docs.sort(key=lambda d: str(d.get(key) or ""), reverse=rev)
        elif isinstance(key_or_list, str):
            rev = direction < 0
            self._docs.sort(key=lambda d: str(d.get(key_or_list) or ""), reverse=rev)
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(self._docs)

    def __next__(self):
        if self._pos < len(self._docs):
            doc = self._docs[self._pos]
            self._pos += 1
            return doc
        raise StopIteration


class _InsertResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class _UpdateResult:
    def __init__(self, matched_count=1, modified_count=1):
        self.matched_count = matched_count
        self.modified_count = modified_count


class _DeleteResult:
    def __init__(self, deleted_count=1):
        self.deleted_count = deleted_count


class _InMemoryCollection:
    def __init__(self, name: str):
        self.name = name
        self._docs = []

    def insert_one(self, doc: dict):
        doc_copy = dict(doc)
        if "_id" not in doc_copy:
            doc_copy["_id"] = ObjectId()
        elif isinstance(doc_copy["_id"], str) and ObjectId.is_valid(doc_copy["_id"]):
            doc_copy["_id"] = ObjectId(doc_copy["_id"])
        self._docs.append(doc_copy)
        return _InsertResult(doc_copy["_id"])

    def find_one(self, query=None):
        query = query or {}
        for d in self._docs:
            if _matches_query(d, query):
                return dict(d)
        return None

    def find(self, query=None):
        query = query or {}
        matched = [dict(d) for d in self._docs if _matches_query(d, query)]
        return _InMemoryCursor(matched)

    def update_one(self, query, update):
        query = query or {}
        for d in self._docs:
            if _matches_query(d, query):
                if "$set" in update:
                    for k, v in update["$set"].items():
                        d[k] = v
                if "$push" in update:
                    for k, v in update["$push"].items():
                        if k not in d or not isinstance(d[k], list):
                            d[k] = []
                        d[k].append(v)
                return _UpdateResult(matched_count=1, modified_count=1)
        return _UpdateResult(matched_count=0, modified_count=0)

    def delete_one(self, query):
        query = query or {}
        for i, d in enumerate(self._docs):
            if _matches_query(d, query):
                del self._docs[i]
                return _DeleteResult(deleted_count=1)
        return _DeleteResult(deleted_count=0)

    def count_documents(self, query=None):
        query = query or {}
        return sum(1 for d in self._docs if _matches_query(d, query))

    def create_index(self, *args, **kwargs):
        pass


class _InMemoryDatabase:
    def __init__(self, name="SheBuilds"):
        self.name = name
        self._collections = {}

    def __getitem__(self, item: str):
        if item not in self._collections:
            self._collections[item] = _InMemoryCollection(item)
        return self._collections[item]


# Global cached database handles
db_client = None
_in_memory_db = None
_mongo_attempted = False


def _seed_sample_data(db):
    """Seed illustrative community records for local development only.

    These are clearly marked as samples and carry **no contact details** —
    seeding plausible-looking email addresses or phone numbers into a domestic
    violence product risks them being read as real people to contact. Disable
    entirely with ``HERWAY_SEED_SAMPLE_DATA=false``.
    """
    admin_col = db["admin"]
    if admin_col.count_documents({}) == 0:
        sample_posts = [
            {
                "_id": ObjectId("660000000000000000000001"),
                "Name": "Anonymous (sample post)",
                "Location": "Delhi",
                "Frequency of domestic violence": "Weekly",
                "Relationship with perpetrator": "Spouse",
                "Severity of domestic violence": "High",
                "Nature of domestic violence": "Verbal abuse, intimidation, and financial control",
                "Impact on children": "Anxiety and fear at home",
                "Culprit details": "Not described",
                "Other info": (
                    "Sample post for local development. Reached out to a Sakhi One Stop "
                    "Centre and found temporary accommodation."
                ),
                "status": "pending",
                "is_sample": True,
            },
            {
                "_id": ObjectId("660000000000000000000002"),
                "Name": "Anonymous (sample post)",
                "Location": "Mumbai, Maharashtra",
                "Frequency of domestic violence": "Daily",
                "Relationship with perpetrator": "In-laws",
                "Severity of domestic violence": "Medium",
                "Nature of domestic violence": "Isolation and harassment over dowry demands",
                "Impact on children": "None",
                "Culprit details": "Not described",
                "Other info": (
                    "Sample post for local development. Filed an application under the "
                    "Protection of Women from Domestic Violence Act, 2005 with a legal aid advocate."
                ),
                "status": "closed",
                "is_sample": True,
            },
        ]
        for p in sample_posts:
            admin_col.insert_one(p)


def _is_production() -> bool:
    return os.getenv("HERWAY_ENV", "").strip().lower() == "production"


def database_mode() -> str:
    """Report which store is backing the app: 'mongodb' or 'in-memory'.

    Exposed on /health so an operator can see at a glance that cases are not
    actually being persisted.
    """
    if db_client is not None:
        return "mongodb"
    if _in_memory_db is not None:
        return "in-memory"
    return "uninitialised"


def get_database():
    """
    Connect to MongoDB (MONGO_ENDPOINT or MONGODB_URI) with a short timeout.

    When MongoDB is unreachable the app falls back to an in-memory store so a
    developer is not blocked. **This fallback loses all data on restart**, so it
    is refused outright when ``HERWAY_ENV=production``: a woman returning to a
    saved safety plan and finding it gone is worse than a clear outage.
    """
    global db_client, _in_memory_db, _mongo_attempted

    if db_client is not None:
        try:
            return db_client["SheBuilds"]
        except Exception:
            pass

    if not _mongo_attempted:
        _mongo_attempted = True
        uri = os.getenv("MONGO_ENDPOINT") or os.getenv("MONGODB_URI")
        if uri:
            try:
                client = MongoClient(
                    uri,
                    serverSelectionTimeoutMS=int(os.getenv("MONGO_TIMEOUT_MS", "4000")),
                    connectTimeoutMS=int(os.getenv("MONGO_TIMEOUT_MS", "4000")),
                    socketTimeoutMS=int(os.getenv("MONGO_SOCKET_TIMEOUT_MS", "8000")),
                    retryWrites=True,
                )
                client.admin.command("ping")
                db_client = client
                logger.info("Connected to MongoDB (%s)", uri.split("@")[-1])
                return db_client["SheBuilds"]
            except Exception as exc:
                if _is_production():
                    logger.critical("MongoDB is unreachable in production: %s", exc)
                    raise RuntimeError(
                        "Cannot reach MongoDB. Refusing to serve requests from a "
                        "volatile in-memory store in production, because saved "
                        "cases would be silently lost."
                    ) from exc
                logger.warning(
                    "MongoDB connection could not be established (%s). "
                    "Falling back to an IN-MEMORY store. Data will NOT persist "
                    "across restarts. Set MONGODB_URI for real persistence.",
                    exc,
                )
        elif _is_production():
            raise RuntimeError(
                "MONGODB_URI (or MONGO_ENDPOINT) must be set when HERWAY_ENV=production."
            )
        else:
            logger.warning(
                "No MONGODB_URI/MONGO_ENDPOINT configured. Using an IN-MEMORY store; "
                "data will NOT persist across restarts."
            )

    if _in_memory_db is None:
        _in_memory_db = _InMemoryDatabase("SheBuilds")
        if os.getenv("HERWAY_SEED_SAMPLE_DATA", "true").strip().lower() != "false":
            _seed_sample_data(_in_memory_db)
        logger.info("In-memory database store initialized.")

    return _in_memory_db


def insert_data_into_db(
    name, location, contact_info, severity, culprit, relationship_to_culprit, other_info
):
    db = get_database()
    if db is None:
        return None

    collection = db["complains2"]
    document = {
        "name": name,
        "location": location,
        "contact_info": contact_info,
        "severity": severity,
        "culprit": culprit,
        "relationship_to_culprit": relationship_to_culprit,
        "other_info": other_info,
        "status": "Pending",
    }
    try:
        culprit_embedding = generate_text_embedding(culprit)
        document["culprit_embedding"] = culprit_embedding
    except Exception:
        pass

    try:
        result = collection.insert_one(document)
        return result.inserted_id
    except Exception as e:
        logger.error("Error inserting data into DB: %s", e)
        return None


def upload_embeddings_to_mongo(file_contents):
    db = get_database()
    if db is None:
        return
    collection = db["doc_embedding"]
    for filename, content in file_contents:
        try:
            embedding = generate_text_embedding(content)
            doc = {
                "filename": filename,
                "embedding": Binary(pickle.dumps(embedding)),
                "content": content[:500],
            }
            collection.insert_one(doc)
        except Exception as e:
            logger.warning("Could not upload embedding for %s: %s", filename, e)
