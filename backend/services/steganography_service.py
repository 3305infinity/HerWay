"""
StegService — thin wrapper around existing Haven steganography utilities.

Reuses:
  - backend.utils.steganography.encode_text_in_image
  - backend.utils.steganography.decode_text_from_image
  - backend.utils.common.load_image_from_url_or_file

DO NOT rebuild the LSB steganography logic — call the existing functions.
This service is invoked by ChatAgent's ``encode_message`` tool when a
high-danger case (domestic_violence / coercive_control) warrants discreet
communication capability.
"""

from __future__ import annotations

import io
import base64
import logging
from typing import Optional

from PIL import Image

from backend.utils.steganography import decode_text_from_image, encode_text_in_image

logger = logging.getLogger(__name__)


class StegService:
    """Wraps existing Haven LSB steganography for reuse by ChatAgent."""

    # ------------------------------------------------------------------ #
    # Encode text into image (discreet help message)
    # ------------------------------------------------------------------ #

    def encode_message_in_image(
        self,
        text: str,
        image_bytes: Optional[bytes] = None,
        image_b64: Optional[str] = None,
    ) -> str:
        """
        Encode ``text`` into the provided image using the existing LSB
        steganography implementation.

        Parameters
        ----------
        text        : The help message to hide in the image.
        image_bytes : Raw image bytes (PNG/JPEG).
        image_b64   : Base64-encoded image string (alternative to bytes).

        Returns
        -------
        Base64-encoded PNG of the encoded image, ready for frontend download.
        """
        if image_b64 and not image_bytes:
            image_bytes = base64.b64decode(image_b64)

        if not image_bytes:
            logger.error("StegService.encode: no image data provided")
            raise ValueError("No image data provided for steganography encoding.")

        try:
            pil_image = Image.open(io.BytesIO(image_bytes))
            encoded_image = encode_text_in_image(pil_image, text)  # existing function

            output_buf = io.BytesIO()
            encoded_image.save(output_buf, format="PNG")
            output_buf.seek(0)

            result_b64 = base64.b64encode(output_buf.read()).decode("utf-8")
            logger.info("StegService: encoded %d chars into image", len(text))
            return result_b64
        except Exception as exc:
            logger.error("StegService.encode failed: %s", exc)
            raise

    # ------------------------------------------------------------------ #
    # Decode text from image
    # ------------------------------------------------------------------ #

    def decode_message_from_image(
        self,
        image_bytes: Optional[bytes] = None,
        image_b64: Optional[str] = None,
    ) -> str:
        """
        Decode hidden text from an image using the existing LSB decode
        implementation.
        """
        if image_b64 and not image_bytes:
            image_bytes = base64.b64decode(image_b64)

        if not image_bytes:
            raise ValueError("No image data provided for steganography decoding.")

        try:
            pil_image = Image.open(io.BytesIO(image_bytes))
            decoded = decode_text_from_image(pil_image)  # existing function
            logger.info("StegService: decoded %d chars from image", len(decoded))
            return decoded
        except Exception as exc:
            logger.error("StegService.decode failed: %s", exc)
            raise
