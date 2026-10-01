"""
LSB steganography over the red channel of an image.

Encoding is **UTF-8 byte based**. The original implementation wrote
``format(ord(char), "08b")`` per character, which silently corrupted any text
outside ASCII: ``ord("न")`` is 2344, so ``format(..., "08b")`` produced 12 bits
while the decoder read 8, desynchronising the whole stream. For a product used
across India — where a message may well be written in Hindi, Bengali, Tamil or
Marathi — that meant the feature quietly destroyed the message.

Encoding ASCII text produces the same bytes as before, so images encoded by the
previous version still decode correctly.
"""

from __future__ import annotations

from PIL import Image

#: Marks the end of the hidden payload. 16 bits that cannot appear inside a
#: valid UTF-8 byte stream read 8 bits at a time.
END_MARKER = "1111111111111110"


def capacity_in_bytes(image: Image.Image) -> int:
    """How many UTF-8 bytes this image can hold (one bit per pixel)."""
    width, height = image.size
    usable_bits = max(0, (width * height) - len(END_MARKER))
    return usable_bits // 8


def encode_text_in_image(image: Image.Image, text: str) -> Image.Image:
    """Encode ``text`` into the image using LSB steganography on the red channel.

    Raises
    ------
    ValueError
        If the image does not have enough pixels to hold the message.
    """
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")

    payload = text.encode("utf-8")
    binary_text = "".join(format(byte, "08b") for byte in payload) + END_MARKER

    width, height = image.size
    if len(binary_text) > width * height:
        raise ValueError(
            f"Message needs {len(binary_text)} pixels but the image only has "
            f"{width * height}. Use a larger image or a shorter message."
        )

    encoded_image = image.copy()
    pixels = encoded_image.load()
    has_alpha = encoded_image.mode == "RGBA"
    idx = 0

    for y in range(height):
        for x in range(width):
            if idx >= len(binary_text):
                return encoded_image

            pixel = pixels[x, y]
            if has_alpha:
                r, g, b, a = pixel
            else:
                r, g, b = pixel
                a = None

            # Replace the least significant bit of the red channel.
            r = (r & ~1) | int(binary_text[idx])
            idx += 1

            pixels[x, y] = (r, g, b, a) if a is not None else (r, g, b)

    return encoded_image


def decode_text_from_image(image: Image.Image) -> str:
    """Decode hidden text from an image. Returns "" when nothing is found."""
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")

    pixels = image.load()
    width, height = image.size
    has_alpha = image.mode == "RGBA"

    bits: list[str] = []
    for y in range(height):
        for x in range(width):
            pixel = pixels[x, y]
            r = pixel[0] if isinstance(pixel, tuple) else pixel
            bits.append(str(r & 1))

            # Check for the terminator once we have enough bits.
            if len(bits) >= len(END_MARKER) and "".join(bits[-len(END_MARKER):]) == END_MARKER:
                payload_bits = bits[: -len(END_MARKER)]
                return _bits_to_text(payload_bits)

    # No end marker: this image does not carry a message we wrote.
    return ""


def _bits_to_text(bits: list[str]) -> str:
    """Turn a bit list into text, ignoring a trailing partial byte."""
    usable = len(bits) - (len(bits) % 8)
    if usable <= 0:
        return ""
    data = bytes(
        int("".join(bits[i : i + 8]), 2) for i in range(0, usable, 8)
    )
    # Replace rather than raise: a partially-damaged image should still show
    # whatever survived instead of failing outright.
    return data.decode("utf-8", errors="replace")
