import os

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# ``models/text-embedding-004`` was retired and now answers 404 ("is not found
# for API version v1beta"), which silently broke every embedding call — and so
# both LawBot's legal retrieval and community culprit matching. See
# docs/KNOWN_ISSUES.md.
#
# ``gemini-embedding-001`` is the current stable replacement. Its native output
# is 3072-dimensional, but the existing Atlas index (``culpritIndex2``, see
# ``find_top_matches``) is declared with 768 dimensions, so the output is
# reduced to 768 to stay compatible with vectors already stored. Change both
# together or the index will reject the query.
DEFAULT_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001")
EMBEDDING_DIMENSIONS = int(os.getenv("GEMINI_EMBEDDING_DIMENSIONS", "768"))


def generate_text_embedding(text, task_type="retrieval_document"):
    """Embed ``text`` with the configured Gemini embedding model.

    ``task_type`` should be ``retrieval_document`` when storing a document and
    ``retrieval_query`` when embedding a user question; Gemini encodes the two
    differently and mixing them costs retrieval quality.
    """
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    response = genai.embed_content(
        model=DEFAULT_EMBEDDING_MODEL,
        content=text,
        task_type=task_type,
        output_dimensionality=EMBEDDING_DIMENSIONS,
    )
    return response["embedding"]


def calculate_similarity_percentage(query_vector, result_vector):
    # Calculate Euclidean distance manually
    distance = sum((q - r) ** 2 for q, r in zip(query_vector, result_vector)) ** 0.5

    # Estimate a maximum possible distance for normalization, e.g., sqrt(768) for 768-dimensional vectors
    max_distance = len(query_vector) ** 0.5

    # Convert distance to a similarity percentage
    similarity_percentage = max(0, (1 - distance / max_distance) * 100)
    return round(similarity_percentage, 2)


def find_top_matches(
    collection,
    description_embedding,
    num_results=1,
    num_candidates=100,
    path="culprit_embedding",
    index="culpritIndex2",
):
    """Atlas ``$vectorSearch`` over ``collection``.

    ``path`` and ``index`` are parameters rather than constants because the two
    callers search different collections: community posts embed under
    ``culprit_embedding``, while legal documents in ``doc_embedding`` store
    theirs under ``embedding``. Hardcoding the community field meant legal
    retrieval queried a field that does not exist in that collection. See
    docs/KNOWN_ISSUES.md — the legal collection also needs its own Atlas index
    and a non-pickled vector before this can return anything.
    """
    # Perform a vector search to get the top matches
    results_cursor = collection.aggregate(
        [
            {
                "$vectorSearch": {
                    "path": path,
                    "index": index,
                    "queryVector": description_embedding,
                    "numResults": num_results,
                    "numCandidates": num_candidates,  # Required for approximate search
                    "numDimensions": EMBEDDING_DIMENSIONS,
                    "similarity": "euclidean",  # Specify similarity metric
                    "type": "knn",  # Use "knn" for nearest-neighbor search
                    "limit": num_results,  # Set the limit parameter
                },
            },
            {
                "$project": {
                    "culprit": 1,  # Replace with the field that contains associated text
                    "culprit_embedding": 1,  # Include embedding only if needed
                    "_id": 1,  # Include the document ID if useful
                }
            },
        ]
    )

    # Convert the cursor to a list to access the results
    results = list(results_cursor)

    return results
