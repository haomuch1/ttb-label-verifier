"""PDF handling: classify pages, skip static instructions, render the rest.

Form 5100.31 PDFs carry static instruction/conditions pages after the
form (pages 2-5 on the 04/2023 revision). Sending those to the vision
model wastes tokens and latency, so pages are classified by their text
layer: a page is kept if it looks like the form itself, skipped if it
matches instruction boilerplate, and kept when in doubt (scanned pages
with no text layer are always kept - we can't judge them).

Classification uses pypdf (pure Python); rendering uses pdf2image, which
requires poppler (installed in the Docker image; on bare Windows/macOS
dev boxes install poppler or test with image uploads instead).
"""

import io
import os

from pdf2image import convert_from_bytes
from pypdf import PdfReader

# Where poppler's binaries live when they're not on PATH (typical on
# Windows dev boxes; the Docker image has them on PATH).
POPPLER_PATH = os.environ.get("POPPLER_PATH") or None

# Unique to the form page itself (page 1 of every revision examined).
FORM_MARKERS = [
    "application for and certification/exemption of",
]

# Each matches exactly one static instruction page of the 04/2023 blank
# form and none of the form/label pages.
INSTRUCTION_MARKERS = [
    "this certificate does not relieve you from liability",
    "allowable revisions to approved labels",
    "bottle deposit information, or container recycling",
    "what is mandatory information and what is non-mandatory information",
]

RENDER_DPI = 150


def _normalize(text: str) -> str:
    return " ".join(text.split()).lower()


def is_instruction_page(page_text: str | None) -> bool:
    """True only when the page is confidently static boilerplate."""
    if not page_text or not page_text.strip():
        return False  # no text layer (scanned page) — keep, can't judge
    norm = _normalize(page_text)
    if any(marker in norm for marker in FORM_MARKERS):
        return False
    return any(marker in norm for marker in INSTRUCTION_MARKERS)


def select_pages(pdf_bytes: bytes) -> list[int]:
    """Return 1-based page numbers worth sending to the vision model."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    kept = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text()
        except Exception:
            text = None  # unextractable page — keep rather than drop silently
        if not is_instruction_page(text):
            kept.append(i)
    # A pathological PDF where everything matched boilerplate: keep page 1
    # rather than sending nothing.
    return kept or [1]


def render_pdf(pdf_bytes: bytes) -> list[tuple[bytes, str]]:
    """Render the non-instruction pages to PNGs for the extractor."""
    pages = select_pages(pdf_bytes)
    images = []
    for page_no in pages:
        rendered = convert_from_bytes(
            pdf_bytes, dpi=RENDER_DPI, first_page=page_no, last_page=page_no,
            poppler_path=POPPLER_PATH,
        )
        buf = io.BytesIO()
        rendered[0].save(buf, format="PNG")
        images.append((buf.getvalue(), "image/png"))
    return images
