"""
Discreet messaging — LSB steganography encode/decode.

This replaces the previous ``/encode`` behaviour, which wrote every encoded
image to a single shared file (``encoded_image.png``) in the working directory.
Two users encoding at the same time could receive each other's image, and the
file persisted on disk afterwards. Everything here stays in memory.

Honesty about what this does
----------------------------
Hiding text in the low bits of an image conceals it from a casual look. It is
**not** encryption and it is **not** tamper-proof:

* anyone who suspects steganography can extract it with free tools;
* phone-monitoring software sees the message as you type it;
* WhatsApp, Instagram and most chat apps re-compress images, which destroys the
  hidden bits entirely.

Every response carries these limitations so the UI can show them. We do not
describe this feature as "secure".
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from backend.utils.steganography import decode_text_from_image, encode_text_in_image

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/discreet", tags=["discreet"])

#: Reject oversized uploads before decoding them into memory.
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB
MAX_MESSAGE_CHARS = 2000

LIMITATIONS = [
    "This hides your message from a casual look. It is not encryption.",
    "Send the image as a file or document attachment. WhatsApp, Instagram and "
    "similar apps compress photos, which destroys the hidden message.",
    "If someone has monitoring software on your device, they can see what you "
    "type regardless of this feature.",
    "The person receiving it needs to open it here to read the message.",
]


class EncodeResponse(BaseModel):
    image_base64: str = Field(..., description="PNG image with the message embedded")
    filename: str
    message_length: int
    capacity_used_percent: float
    limitations: list[str] = Field(default_factory=lambda: list(LIMITATIONS))


class DecodeResponse(BaseModel):
    found: bool
    message: Optional[str] = None
    note: str


def _load_image(data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        return image
    except UnidentifiedImageError:
        raise HTTPException(
            status_code=400,
            detail="That file is not an image we can read. Please upload a PNG or JPG.",
        )
    except Exception as exc:
        logger.warning("Discreet: could not open uploaded image: %s", exc)
        raise HTTPException(
            status_code=400, detail="That image could not be opened. Please try another one."
        )


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file was empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Please use an image smaller than {MAX_IMAGE_BYTES // (1024 * 1024)} MB.",
        )
    return data


@router.post("/encode", response_model=EncodeResponse)
async def encode(
    message: str = Form(..., description="The text to hide inside the image"),
    file: UploadFile = File(..., description="Cover image (PNG recommended)"),
):
    """Hide ``message`` inside the uploaded image and return a PNG."""
    text = (message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Please enter a message to hide.")
    if len(text) > MAX_MESSAGE_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Please keep the message under {MAX_MESSAGE_CHARS} characters.",
        )

    data = await _read_upload(file)
    image = _load_image(data)

    # One bit per pixel (red channel), plus a 16-bit end marker.
    width, height = image.size
    capacity_bits = width * height
    needed_bits = len(text.encode("utf-8")) * 8 + 16
    if needed_bits > capacity_bits:
        raise HTTPException(
            status_code=400,
            detail=(
                "This image is too small for that message. Use a larger image "
                f"(this one holds about {max(0, (capacity_bits - 16) // 8)} characters)."
            ),
        )

    try:
        encoded = encode_text_in_image(image, text)
        buf = io.BytesIO()
        # PNG is lossless. Saving as JPEG would destroy the hidden bits.
        encoded.save(buf, format="PNG")
        buf.seek(0)
        payload = base64.b64encode(buf.read()).decode("ascii")
    except Exception as exc:
        logger.exception("Discreet: encoding failed")
        raise HTTPException(
            status_code=500,
            detail="The message could not be hidden in that image. Please try another image.",
        )

    logger.info("Discreet: encoded %d characters into a %dx%d image", len(text), width, height)
    return EncodeResponse(
        image_base64=payload,
        filename="photo.png",
        message_length=len(text),
        capacity_used_percent=round(needed_bits / capacity_bits * 100, 1),
    )


@router.post("/decode", response_model=DecodeResponse)
async def decode(file: UploadFile = File(..., description="Image that may contain a message")):
    """Read a hidden message out of an uploaded image."""
    data = await _read_upload(file)
    image = _load_image(data)

    try:
        text = decode_text_from_image(image)
    except Exception as exc:
        logger.warning("Discreet: decoding failed: %s", exc)
        raise HTTPException(
            status_code=400,
            detail=(
                "That image could not be read. If it was sent through a chat app it "
                "was probably compressed, which removes the hidden message. Ask for "
                "it to be sent again as a file attachment."
            ),
        )

    if not text:
        return DecodeResponse(
            found=False,
            message=None,
            note=(
                "No hidden message was found in this image. If you were expecting one, "
                "the image may have been compressed by a chat app — ask for it to be "
                "sent again as a file or document attachment."
            ),
        )

    return DecodeResponse(
        found=True,
        message=text,
        note="Message recovered. It has not been stored on our servers.",
    )


@router.get("/limitations")
async def limitations():
    """What this feature can and cannot protect against."""
    return {
        "is_encryption": False,
        "limitations": LIMITATIONS,
        "recommended_format": "PNG",
        "max_message_chars": MAX_MESSAGE_CHARS,
    }
