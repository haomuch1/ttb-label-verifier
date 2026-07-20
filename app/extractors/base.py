"""Extractor interface: the boundary between inference and judgment.

Every backend implements the same contract — take document images, return
a validated Extraction (verbatim text and observations, never verdicts).
The rules engine neither knows nor cares which model produced the
extraction. This is a first-class architecture decision: production
inside the Treasury network (which blocks most outbound ML endpoints)
runs the same app against self-hosted inference by changing one env var.
"""

import io
from dataclasses import dataclass
from typing import Protocol

from PIL import Image

from app.models import Extraction

# API-safe image bounds (Anthropic: ~5MB / 8000px; also sane for Ollama).
MAX_DIMENSION = 7900
MAX_BYTES = 4_500_000


@dataclass
class ExtractionResult:
    extraction: Extraction
    input_tokens: int   # 0 when the backend doesn't report usage
    output_tokens: int
    model: str


class Extractor(Protocol):
    """One vision call in, one validated Extraction out. No chaining.

    region: None for a whole document; "form" / "labels" when the caller
    split the page at the AFFIX-LABELS anchor and this call covers only
    one region (see app/pipeline.py).
    """

    name: str

    async def extract(
        self, images: list[tuple[bytes, str]], region: str | None = None
    ) -> ExtractionResult: ...


SYSTEM_PROMPT = """\
You are a document transcription engine for TTB COLA applications (Form \
5100.31) and alcohol beverage label images.

You transcribe and observe. You never judge. Do not evaluate compliance, do \
not compare fields against each other, and do not decide whether anything \
matches, passes, or is correct. Return only what the document literally shows.

The input is one or more images. A COLA printout contains a form section \
followed by the affixed label images; each affixed label is usually preceded \
by an "Image Type:" caption (e.g. "Brand (front) or keg collar", "Back", \
"Other") and its printed dimensions. A standalone photo of a label has no \
form section - return null for the form in that case.

Form fields:
- Locate each field by the label text printed next to it ("BRAND NAME", \
"ALCOHOL CONTENT", "NET CONTENTS", "TYPE OF PRODUCT" or the product-type \
checkboxes) - NEVER by item number. Item numbers shift between form \
revisions and are not reliable.
- For each form field you extract, also return the exact adjacent label text \
you found it next to (the *_label fields), so extraction can be audited.
- If a field is absent on this form revision, return null. Never guess or \
infer a value the form does not show.
- Values are verbatim as written: if the form says just "35", return "35".

Label images:
- Return one entry per affixed label image, in order, each with its "Image \
Type:" caption and stated dimensions when present. Report what is on each \
image separately; do not merge or aggregate information across images. An \
image with no regulated text still gets an entry with null fields.
- government_warning: transcribe the government health warning EXACTLY as \
printed. Preserve the original capitalization, the original line breaks (as \
newline characters), and any hyphenation at line ends (e.g. "BEV-\\nERAGES"). \
Do not normalize, correct, complete, re-case, or tidy the text in any way, \
even if it looks wrong, oddly cased, or truncated - the downstream checker \
requires the raw form as printed.
- abv_raw, proof_raw, net_contents, class_type, bottler_info: verbatim as \
printed (e.g. "39% ALC / VOL", "750ML").
- apparent_product_type: your observation of which category the label \
presents as (wine / distilled_spirits / malt_beverage), or null if unclear. \
This is an observation about the label's presentation, not a judgment.
"""

USER_PROMPT = "Extract this document into the required structure."

# Appended to the system prompt when the caller split the page at the
# "AFFIX COMPLETE SET OF LABELS BELOW" anchor and this call sees only one
# region of it.
REGION_HINTS = {
    "form": (
        "\nThis image contains ONLY the printed application form portion of "
        "the COLA - the affixed label artwork below the form has been removed. "
        "Extract the form fields and return an empty labels list. Keep each "
        "*_label field to the few words of the adjacent caption only - never "
        "transcribe surrounding form boilerplate into it."
    ),
    "labels": (
        "\nThis image contains ONLY the affixed label artwork (everything "
        "below the form's 'AFFIX COMPLETE SET OF LABELS BELOW' line) - the "
        "form portion has been removed. Return null for the form and one "
        "entry per affixed label image."
    ),
}


def system_prompt_for(region: str | None) -> str:
    return SYSTEM_PROMPT + (REGION_HINTS.get(region, "") if region else "")


def prepare_image(data: bytes, media_type: str) -> tuple[bytes, str]:
    """Downscale/re-encode only if the image exceeds backend limits."""
    if len(data) <= MAX_BYTES:
        img = Image.open(io.BytesIO(data))
        if max(img.size) <= MAX_DIMENSION:
            return data, media_type
    img = Image.open(io.BytesIO(data))
    scale = MAX_DIMENSION / max(img.size)
    if scale < 1:
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    return buf.getvalue(), "image/jpeg"
