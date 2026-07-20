"""Split a COLA page at its fixed structural anchor.

Every TTB Form 5100.31 prints the boilerplate line "AFFIX COMPLETE SET OF
LABELS BELOW": everything above it is the printed application form,
everything below is the affixed label artwork. Splitting there lets each
region get the model's full image-token budget — the fix for small-print
warning text degrading when a whole tall page is encoded at once.

Detection is best-effort by design: PDFs locate the phrase in the
extractable text layer (pypdf visitor coordinates); images locate it by
OCR (tesseract, when installed). Any failure returns None and the caller
sends the whole page as a single extraction — the split is an enhancement
over the working baseline, never a replacement that can break it.
"""

import io
import os
import shutil

from PIL import Image
from pypdf import PdfReader

# Matching the prefix is enough and robust to OCR noise on later words.
ANCHOR_PREFIX = "affix complete set"

SPLIT_PAD = 6        # px below the anchor line's bottom edge
MIN_REGION_PX = 120  # both regions must be at least this tall to be plausible


def _tesseract_cmd() -> str | None:
    explicit = os.environ.get("TESSERACT_CMD")
    if explicit and os.path.exists(explicit):
        return explicit
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    default = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(default):
        return default
    return None


def anchor_y_in_image(image_bytes: bytes) -> int | None:
    """Bottom y-pixel of the anchor line, via OCR. None if not found."""
    cmd = _tesseract_cmd()
    if cmd is None:
        return None
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = cmd
        img = Image.open(io.BytesIO(image_bytes))
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    except Exception:
        return None

    lines: dict[tuple, list[int]] = {}
    texts: dict[tuple, list[str]] = {}
    for i, word in enumerate(data["text"]):
        if not word.strip():
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        texts.setdefault(key, []).append(word)
        lines.setdefault(key, []).append(data["top"][i] + data["height"][i])
    for key, words in texts.items():
        if ANCHOR_PREFIX in " ".join(words).lower():
            return max(lines[key])
    return None


def anchor_fraction_in_pdf_page(pdf_bytes: bytes, page_number: int) -> float | None:
    """Anchor's vertical position on a PDF page as a fraction from the top."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        page = reader.pages[page_number - 1]
        height = float(page.mediabox.height)
        chunks: list[tuple[str, float]] = []

        def visit(text, cm, tm, font_dict, font_size):
            if text.strip():
                chunks.append((text, tm[5]))

        page.extract_text(visitor_text=visit)
    except Exception:
        return None
    # Text arrives in arbitrarily small chunks; scan a sliding window.
    for i in range(len(chunks)):
        window = "".join(t for t, _ in chunks[i:i + 8]).lower()
        if ANCHOR_PREFIX in window:
            y_baseline = chunks[i][1]
            fraction = 1 - (y_baseline / height)
            return fraction if 0 < fraction < 1 else None
    return None


def _split_image_at(image_bytes: bytes, y: int) -> tuple[bytes, bytes] | None:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    cut = min(img.height, y + SPLIT_PAD)
    if cut < MIN_REGION_PX or img.height - cut < MIN_REGION_PX:
        return None
    halves = []
    for box in [(0, 0, img.width, cut), (0, cut, img.width, img.height)]:
        buf = io.BytesIO()
        img.crop(box).save(buf, format="PNG")
        halves.append(buf.getvalue())
    return halves[0], halves[1]


def split_document(
    images: list[tuple[bytes, str]],
    pdf_info: tuple[bytes, int] | None = None,
) -> tuple[list[tuple[bytes, str]], list[tuple[bytes, str]]] | None:
    """Split the first page into (form region, label region).

    Returns (form_images, label_images), where label_images also carries
    any subsequent pages unchanged. None whenever the anchor can't be
    located — the caller falls back to whole-page extraction.
    """
    if not images:
        return None
    first_bytes, _ = images[0]

    y = None
    if pdf_info is not None:
        fraction = anchor_fraction_in_pdf_page(*pdf_info)
        if fraction is not None:
            page_height = Image.open(io.BytesIO(first_bytes)).height
            y = int(fraction * page_height)
    if y is None:
        y = anchor_y_in_image(first_bytes)
    if y is None:
        return None

    halves = _split_image_at(first_bytes, y)
    if halves is None:
        return None
    form_png, labels_png = halves
    return [(form_png, "image/png")], [(labels_png, "image/png")] + images[1:]
