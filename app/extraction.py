"""The single Claude vision call. The model extracts; app/rules.py judges.

One request per document, no chaining — the 5-second budget allows exactly
one round trip. The response is structured JSON validated against the
Extraction schema; it contains verbatim text and observations only, never
verdicts. The inference call is isolated behind extract() so the backend
can be swapped (e.g. for self-hosted inference inside the Treasury
network) without touching the rules engine.
"""

import base64
import io
import os

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from PIL import Image

from app.models import Extraction

load_dotenv()

# Default chosen for the hard <5s warm-latency requirement (a prior vendor
# pilot died at 30-40s). claude-haiku-4-5 is the fastest current model and
# supports both vision and structured outputs; override via EXTRACTION_MODEL
# to trade latency for accuracy (e.g. claude-opus-4-8).
MODEL = os.environ.get("EXTRACTION_MODEL", "claude-haiku-4-5")
MAX_TOKENS = 4096

# API limits: ~5MB per image, 8000px max dimension.
MAX_DIMENSION = 7900
MAX_BYTES = 4_500_000

_client: AsyncAnthropic | None = None


def get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic()
    return _client


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


def prepare_image(data: bytes, media_type: str) -> tuple[bytes, str]:
    """Downscale/re-encode only if the image exceeds API limits."""
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


async def extract(images: list[tuple[bytes, str]]) -> Extraction:
    """Run the single vision call over a document's page/label images.

    images: list of (bytes, media_type) covering the whole document —
    rendered PDF pages or uploaded photos. Returns the validated
    Extraction; raises anthropic errors upward for the caller to map.
    """
    content = []
    for data, media_type in images:
        data, media_type = prepare_image(data, media_type)
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.standard_b64encode(data).decode(),
            },
        })
    content.append({
        "type": "text",
        "text": "Extract this document into the required structure.",
    })

    response = await get_client().messages.parse(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
        output_format=Extraction,
    )
    return response.parsed_output
