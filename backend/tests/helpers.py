"""Shared test fixtures for document files.

Test images must carry actual text: the verifier measures focus objectively,
and a blank page correctly reads as unreadable — which is right behaviour but
useless as a stand-in for a real document.
"""

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

_LINES = [
    "CITY MEDICAL CENTRE",
    "12 MG Road, Bengaluru - 560001",
    "Bill No: CMC/2024/08321   Date: 01-Nov-2024",
    "Patient Name: Rajesh Kumar",
    "Consultation Fee (OPD)      1000.00",
    "CBC (Complete Blood Count)   300.00",
    "Dengue NS1 Antigen Test      200.00",
    "Total Amount:               1500.00",
]


def legible_image(width: int = 620, height: int = 420) -> Image.Image:
    """A page with enough printed detail to pass the legibility floor."""
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    for i, line in enumerate(_LINES):
        draw.text((24, 20 + i * 34), line, fill="black")
    return image


def legible_page(path: Path) -> Path:
    """Write a legible page to `path` (format inferred from the suffix)."""
    legible_image().save(path)
    return path


def legible_bytes(fmt: str = "JPEG") -> bytes:
    buffer = BytesIO()
    legible_image().save(buffer, format=fmt)
    return buffer.getvalue()
