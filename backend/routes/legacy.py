"""
Legacy router — preserves ALL existing Haven endpoints.

These endpoints are mounted at the root (no /api/v2 prefix) so that the
existing frontend continues to work without changes.

Security policy (Phase 2)
=========================
The Phase 1 audit found twelve of these fourteen endpoints unauthenticated,
five of them invoking a paid model. Each was classified rather than blanket-
protected, because several are anonymous **by design**: the community feed
exists so that a woman can read other women's experiences, and post her own,
without first creating an account that ties her identity to a disclosure.

============================  ==================  =====================  ==========
Endpoint                      Classification      Control                Auth
============================  ==================  =====================  ==========
POST /text-generation         LLM / paid          LLM budget             no
POST /img-generation          LLM / paid          LLM budget             no
POST /text-decomposition      LLM / paid          LLM budget + length    no
GET  /poem-generation         LLM / paid          LLM budget + length    no
POST /generate-image          LLM / paid (AWS)    LLM budget             no
GET  /find-match              LLM / paid (embed)  LLM budget + length    no
POST /save-extracted-data     Public submission   Submission budget      no
POST /encode                  Public utility      Utility budget         no
POST /decode                  Public utility      Utility budget         no
GET  /get-admin-posts         Public read         Read budget            no
GET  /get-post/{id}           Public read         Read budget            no
POST /send-message            External publish    Submission budget      **yes**
POST /close-issue/{id}        Administrative      Submission budget      **yes**
POST /upload_embeddings/      Administrative      LLM budget             **yes**
============================  ==================  =====================  ==========

Why authentication was *not* added to the public ten
----------------------------------------------------
Five of the Next.js proxies in front of these routes (`/api/decompose`,
`/api/generate-text`, `/api/generate-image`, `/api/getPosts`, `/api/save`) do
not forward credentials, so requiring auth would break the community and
create-post flows outright. More importantly, anonymity is the product
decision here. The abuse risk those routes actually carry is cost and volume,
and a per-caller request budget addresses that without a login wall.

``POST /send-message`` is the exception: it publishes to a public Twitter
account, is not reachable from the current UI, and an open endpoint that posts
externally on a domestic-violence product is not defensible. It now requires an
authenticated identity.

Rate limiting is in-process and per worker — see ``backend.rate_limit`` for
what that does and does not protect against. Nothing carrying emergency
information is limited.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os

import boto3
from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from backend.auth import Identity, require_authenticated
from backend.db import get_database, upload_embeddings_to_mongo
from backend.rate_limit import (
    rate_limit_llm,
    rate_limit_read,
    rate_limit_submission,
    rate_limit_utility,
)

#: Upper bound on free-text sent to a model provider. Generous for a real
#: disclosure, small enough that a pasted file cannot run up a bill or stall a
#: worker. Validation happens before the provider is called.
MAX_TEXT_INPUT_CHARS = 8000
from backend.schema import FileContent, PostInfo
from backend.utils.common import (
    load_image_from_url_or_file,
    read_files_from_directory,
    serialize_object_id,
)
from backend.utils.embedding import find_top_matches, generate_text_embedding
from backend.utils.regex_ptr import extract_info
from backend.utils.steganography import decode_text_from_image, encode_text_in_image
from backend.utils.text_llm import (
    create_poem,
    decompose_user_text,
    expand_user_text_using_gemini,
    expand_user_text_using_gemma,
    text_to_image,
)
from backend.utils.twitter import send_message_to_twitter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["legacy"])

# ---------------------------------------------------------------------------
# AWS clients (same as original main.py)
# ---------------------------------------------------------------------------
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "shebuilds-womentechmakers")

try:
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION,
    )
    bedrock_client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
except Exception:
    s3_client = None
    bedrock_client = None
    logger.warning("Legacy: AWS clients not initialised (credentials missing?)")


def _db():
    db = get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return db


# ---------------------------------------------------------------------------
# Original endpoints — identical behaviour
# ---------------------------------------------------------------------------

@router.post("/text-generation", dependencies=[Depends(rate_limit_llm)])
async def get_post_and_expand_its_content(post_info: PostInfo):
    """Expand user input text for help message generation."""
    try:
        concatenated_text = (
            f"Name: {post_info.name}\n"
            f"Phone: {post_info.phone}\n"
            f"Location: {post_info.location}\n"
            f"Duration of Abuse: {post_info.duration_of_abuse}\n"
            f"Frequency of Incidents: {post_info.frequency_of_incidents}\n"
            f"Preferred Contact Method: {post_info.preferred_contact_method}\n"
            f"Current Situation: {post_info.current_situation}\n"
            f"Culprit Description: {post_info.culprit_description}\n"
            f"Custom Text: {post_info.custom_text}\n"
        )
        gemini_response = await expand_user_text_using_gemini(concatenated_text)
        gemma_response = await expand_user_text_using_gemma(concatenated_text)
        return {"gemini_response": gemini_response, "gemma_response": gemma_response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error expanding text: {e}")


@router.post("/img-generation", dependencies=[Depends(rate_limit_llm)])
async def create_image_from_prompt(input_data: str):
    """Generate an image based on a text prompt."""
    try:
        text_to_image(input_data)
        return {"received_text": input_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating image: {e}")


@router.post("/text-decomposition", dependencies=[Depends(rate_limit_llm)])
async def decompose_text_content(data: dict):
    """Decompose and extract information from user text.

    Validates before spending a model call: an absent or oversized body used to
    reach the provider regardless, which is both a cost and a latency problem.
    """
    text = (data or {}).get("text") if isinstance(data, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=422, detail="A non-empty 'text' field is required.")
    if len(text) > MAX_TEXT_INPUT_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"'text' must be {MAX_TEXT_INPUT_CHARS} characters or fewer.",
        )

    try:
        decomposed_text = decompose_user_text(text)
        return {"extracted_data": extract_info(decomposed_text)}
    except Exception:
        # The raw exception can carry provider detail and the user's own text.
        logger.exception("Error decomposing text")
        raise HTTPException(status_code=503, detail="That text could not be processed right now.")


#: Keys the community post form is allowed to write. Previously the whole
#: request body was inserted verbatim, so a caller could set arbitrary fields
#: (including ``_id`` or ``status``) on the public community collection.
_ALLOWED_POST_FIELDS = {
    "Name",
    "Location",
    "Frequency of domestic violence",
    "Relationship with perpetrator",
    "Severity of domestic violence",
    "Nature of domestic violence",
    "Impact on children",
    "Culprit details",
    "Other info",
}


@router.post("/save-extracted-data", dependencies=[Depends(rate_limit_submission)])
async def save_extracted_data(data: dict):
    """Save an anonymous community post.

    Only the known form fields are stored, and ``status`` is set server-side.
    Contact details are deliberately not persisted — the community feed is
    public, and a stored phone number would eventually be exposed.
    """
    if not isinstance(data, dict) or not data:
        raise HTTPException(status_code=400, detail="No post content supplied.")

    document = {
        key: str(value)[:2000]
        for key, value in data.items()
        if key in _ALLOWED_POST_FIELDS and value not in (None, "")
    }
    if not document:
        raise HTTPException(
            status_code=400,
            detail="The post was empty after validation. Please fill in the form fields.",
        )

    document["status"] = "pending"

    try:
        result = _db()["admin"].insert_one(document)
        return {"status": "Data saved successfully", "id": str(result.inserted_id)}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error saving community post")
        raise HTTPException(status_code=503, detail="Your post could not be saved right now.")


@router.post("/encode", dependencies=[Depends(rate_limit_utility)])
async def encode_text_in_image_endpoint(
    text: str, img_url: str = None, file: UploadFile = File(None)
):
    """Encode text into an image.

    Kept for backward compatibility. New clients should use
    ``POST /api/v2/discreet/encode``, which also reports capacity limits and
    the honest limitations of steganography.

    The response is streamed from memory. The previous implementation wrote
    every result to a single shared ``encoded_image.png`` on disk, so two
    concurrent users could be handed each other's private message, and the
    file was left behind afterwards.
    """
    try:
        image = load_image_from_url_or_file(img_url, file)
        encoded_image = encode_text_in_image(image, text)
        buf = io.BytesIO()
        encoded_image.save(buf, format="PNG")
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="image/png",
            headers={"Content-Disposition": "attachment; filename=photo.png"},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Legacy encode failed")
        raise HTTPException(status_code=500, detail="Could not encode the message into that image.")


@router.post("/decode", dependencies=[Depends(rate_limit_utility)])
async def decode_text_from_image_endpoint(
    img_url: str = None, file: UploadFile = File(None)
):
    """Decode text from an image.

    Kept for backward compatibility; see ``POST /api/v2/discreet/decode``.
    """
    try:
        image = load_image_from_url_or_file(img_url, file)
        decoded = decode_text_from_image(image)
        return {
            "decoded_text": decoded,
            "found": bool(decoded),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Legacy decode failed")
        raise HTTPException(status_code=400, detail="Could not read that image.")


@router.get("/poem-generation", dependencies=[Depends(rate_limit_llm)])
async def create_poem_endpoint(text: str):
    """Generate an inspirational poem based on input text."""
    if not (text or "").strip():
        raise HTTPException(status_code=422, detail="A non-empty 'text' value is required.")
    if len(text) > MAX_TEXT_INPUT_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"'text' must be {MAX_TEXT_INPUT_CHARS} characters or fewer.",
        )
    try:
        return {"poem": create_poem(text)}
    except Exception:
        logger.exception("Error generating poem")
        raise HTTPException(status_code=503, detail="A poem could not be generated right now.")


@router.post("/send-message", dependencies=[Depends(rate_limit_submission)])
async def send_message_to_twitter_endpoint(
    image_url: str,
    caption: str,
    identity: Identity = Depends(require_authenticated),
):
    """Publish a message to the configured Twitter account.

    **Requires authentication.** This is the one legacy endpoint that reaches
    outside HerWay and publishes in public. Leaving it open meant anyone who
    found the URL could post from the project's account; on a domestic-violence
    product that is not a risk worth carrying for an endpoint the current UI
    never calls.
    """
    if not (caption or "").strip():
        raise HTTPException(status_code=422, detail="A caption is required.")
    if len(caption) > 280:
        raise HTTPException(
            status_code=422, detail="A caption cannot be longer than 280 characters."
        )

    try:
        send_message_to_twitter(image_url, caption)
        return {"status": "Message sent successfully"}
    except Exception:
        # The upstream error can contain API credentials; do not echo it.
        logger.exception("Error sending message to Twitter")
        raise HTTPException(
            status_code=502, detail="The message could not be posted right now."
        )


# Fields on a community post that identify the person who wrote it or the way
# to reach them. The community feed is public, so these must never be returned
# by a public endpoint — publishing a survivor's phone number or email is a
# direct safety risk.
_PRIVATE_POST_FIELDS = {
    "contact info",
    "contact_info",
    "phone",
    "email",
    "preferred way of contact",
    "preferred_contact_method",
    "culprit_embedding",
    "embedding",
    "user_id",
}


def _public_post(post: dict) -> dict:
    """Strip contact and identifying fields from a community post."""
    serialized = serialize_object_id(post)
    return {
        k: v
        for k, v in serialized.items()
        if k.lower().strip() not in _PRIVATE_POST_FIELDS
    }


@router.get("/get-admin-posts", dependencies=[Depends(rate_limit_read)])
def get_all_posts():
    """Retrieve community posts with contact details removed."""
    try:
        posts = [_public_post(post) for post in _db()["admin"].find()]
        return JSONResponse(content=posts)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error retrieving community posts")
        raise HTTPException(
            status_code=503, detail="Community posts could not be loaded right now."
        )


@router.get("/find-match", dependencies=[Depends(rate_limit_llm)])
def find_top_matching_posts(info: str, collection: str):
    """Find top matches based on embedding similarity.

    The collection is restricted to a known allow-list; it used to be taken
    verbatim from the query string, which let a caller read any collection in
    the database, including ``cases``.
    """
    if collection not in {"admin", "complains2"}:
        raise HTTPException(status_code=400, detail="Unknown collection")
    if not (info or "").strip():
        raise HTTPException(status_code=422, detail="A non-empty 'info' value is required.")
    if len(info) > MAX_TEXT_INPUT_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"'info' must be {MAX_TEXT_INPUT_CHARS} characters or fewer.",
        )
    try:
        description_vector = generate_text_embedding(info)
        top_matches = find_top_matches(_db()[collection], description_vector)
        return [_public_post(match) for match in top_matches]
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error finding matches")
        raise HTTPException(status_code=503, detail="Matching is unavailable right now.")


@router.get("/get-post/{post_id}", dependencies=[Depends(rate_limit_read)])
def get_post_by_id(post_id: str):
    """Retrieve a specific community post, with contact details removed."""
    try:
        obj_id = ObjectId(post_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid post ID")

    try:
        post = _db()["admin"].find_one({"_id": obj_id})
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error retrieving post by ID")
        raise HTTPException(status_code=503, detail="That post could not be loaded right now.")

    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return JSONResponse(content=_public_post(post))


@router.post("/close-issue/{issue_id}", dependencies=[Depends(rate_limit_submission)])
async def close_issue(issue_id: str, identity: Identity = Depends(require_authenticated)):
    """Mark an issue as closed. Restricted to signed-in users.

    This was previously open to anyone, so any visitor could close any
    survivor's open case report.
    """
    try:
        obj_id = ObjectId(issue_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid issue ID")

    try:
        result = _db()["admin"].update_one(
            {"_id": obj_id},
            {"$set": {"status": "closed", "closed_by": identity.owner_id}},
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error closing issue")
        raise HTTPException(status_code=503, detail="Could not update that issue right now.")

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Issue not found")
    return {"status": "Issue marked as closed"}


@router.post("/upload_embeddings/", dependencies=[Depends(rate_limit_llm)])
async def upload_embeddings(identity: Identity = Depends(require_authenticated)):
    """Rebuild the legal-document embedding index.

    Requires a signed-in user: it is an expensive admin operation that calls
    the embedding API once per document, and was previously open to anyone.
    """
    try:
        file_contents = read_files_from_directory("backend/docs")
        upload_embeddings_to_mongo(file_contents)
        return {"message": "Embeddings uploaded successfully", "documents": len(file_contents)}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="No documents directory found to index.")
    except Exception:
        logger.exception("Error uploading embeddings")
        raise HTTPException(status_code=503, detail="Embedding upload failed.")


@router.post("/generate-image", dependencies=[Depends(rate_limit_llm)])
async def generate_image(data: dict):
    """Generate an image based on a text prompt using Amazon Bedrock and store it in S3."""
    if not bedrock_client or not s3_client:
        raise HTTPException(status_code=503, detail="AWS services not configured")
    try:
        prompt = data.get("prompt")
        body = json.dumps(
            {
                "taskType": "TEXT_IMAGE",
                "textToImageParams": {"text": prompt},
                "imageGenerationConfig": {
                    "numberOfImages": 3,
                    "quality": "standard",
                    "height": 1024,
                    "width": 1024,
                    "cfgScale": 7.5,
                    "seed": 42,
                },
            }
        )
        response = bedrock_client.invoke_model(
            body=body,
            modelId="amazon.titan-image-generator-v1",
            accept="application/json",
            contentType="application/json",
        )
        response_body = json.loads(response.get("body").read())
        images_b64 = response_body["images"]
        image_urls = []
        for img_b64 in images_b64:
            image_data = base64.b64decode(img_b64)
            image_key = f"generated-images/{ObjectId()}.png"
            s3_client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=image_key,
                Body=image_data,
                ContentType="image/png",
            )
            image_url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{image_key}"
            image_urls.append(image_url)
        return {"image_urls": image_urls}
    except Exception as e:
        logger.error("Error generating image: %s", e)
        raise HTTPException(status_code=500, detail=f"Error generating image: {e}")
