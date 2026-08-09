"""Local image handling for uploaded documents — no LLM involved.

Everything here answers questions we must not delegate to the vision model:
can this file be opened at all, is it legible enough to be worth reading, and
how do we hand its pages to a model that only accepts images.

The legibility check exists because the model's own quality rating proved
unreliable: a heavily blurred pharmacy bill came back classified as a
PRESCRIPTION with 0.95 confidence and quality GOOD. Measuring focus in code
is objective and free.
"""

import base64
import mimetypes
from io import BytesIO
from pathlib import Path

from app.models import DocumentQuality

MAX_PDF_PAGES = 5
PDF_RENDER_SCALE = 2  # ~144 DPI — legible for handwriting without huge payloads

# Focus measure: variance of the Laplacian. Sharp text produces strong
# second-derivative edges; blur flattens them.
#
# Calibrated on the sample documents in data/mock_documents:
#   sharp scans          ~3500
#   smudged, readable    ~5
#   illegible            ~0.4
#
# The gap is wide, so the thresholds sit well clear of both sides. They are
# calibrated on rendered documents, not phone photos of real bills — real
# traffic should recalibrate these against labelled samples, and the model's
# own rating still applies above the floor.
UNREADABLE_SHARPNESS = 2.0
POOR_SHARPNESS = 100.0


def _first_page(path: Path):
    """The document's first page as a PIL image, whatever the format."""
    from PIL import Image

    if path.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        try:
            return pdf[0].render(scale=PDF_RENDER_SCALE).to_pil()
        finally:
            pdf.close()
    return Image.open(path)


def sharpness(path: Path) -> float | None:
    """Focus score for a document's first page; None if unmeasurable."""
    import numpy as np

    try:
        image = _first_page(path).convert("L")
        image.thumbnail((1200, 1200))  # scale-independent comparison
        a = np.asarray(image, dtype=np.float64)
        if a.shape[0] < 3 or a.shape[1] < 3:
            return None
        laplacian = (
            a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:] - 4 * a[1:-1, 1:-1]
        )
        return float(laplacian.var())
    except Exception:
        return None


def measure_quality(path: Path) -> tuple[DocumentQuality | None, float | None]:
    """Legibility judged from the pixels: (quality, score).

    Returns (None, score) when the image is sharp enough that the vision
    model's own assessment should stand.
    """
    score = sharpness(path)
    if score is None:
        return None, None
    if score < UNREADABLE_SHARPNESS:
        return DocumentQuality.UNREADABLE, score
    if score < POOR_SHARPNESS:
        return DocumentQuality.POOR, score
    return None, score


def is_decodable(path: Path) -> bool:
    """Can this file be opened as an image or PDF at all?

    Checked locally before any vision call so a damaged upload is reported as
    a member-fixable document problem ("re-upload this file") instead of
    masquerading as an infrastructure outage.
    """
    try:
        if not path.exists() or path.stat().st_size == 0:
            return False
        if path.suffix.lower() == ".pdf":
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(str(path))
            try:
                return len(pdf) > 0
            finally:
                pdf.close()
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
        return True
    except Exception:
        return False


def _data_uri(mime: str, payload: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode()}"


def _render_pdf(path: Path) -> list[str]:
    """Render PDF pages to PNG data URIs.

    Vision models take images, not PDFs, so multi-page scanned bills are
    rasterized a page at a time and sent together — matching the guidance in
    `sample_documents_guide.md` ("process each page separately; aggregate line
    items"). Beyond MAX_PDF_PAGES the tail is dropped and the caller warns.
    """
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        uris = []
        for index in range(min(len(pdf), MAX_PDF_PAGES)):
            image = pdf[index].render(scale=PDF_RENDER_SCALE).to_pil()
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            uris.append(_data_uri("image/png", buffer.getvalue()))
        return uris
    finally:
        pdf.close()


def image_parts(path: Path) -> tuple[list[str], int]:
    """Data URIs for a document, plus its total page count (1 for images)."""
    if path.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        pages = len(pdf)
        pdf.close()
        return _render_pdf(path), pages
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return [_data_uri(mime, path.read_bytes())], 1
