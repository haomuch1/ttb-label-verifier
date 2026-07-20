"""Two-region concurrent extraction with graceful fallback.

When the page splits at the "AFFIX COMPLETE SET OF LABELS BELOW" anchor,
the form region and the label region are extracted concurrently
(asyncio.gather) and merged into the one Extraction the rules engine
already consumes: form fields from region A, label observations from
region B. Wall-clock cost is roughly the slower of the two calls.

Every failure path — anchor not found, either region call erroring —
falls back to the single whole-page extraction that was the working
baseline. The split can only improve input quality, never break it.
"""

import asyncio

from app.extractors.base import ExtractionResult, Extractor
from app.models import Extraction
from app.regions import split_document


async def run_extraction(
    extractor: Extractor,
    images: list[tuple[bytes, str]],
    pdf_info: tuple[bytes, int] | None = None,
) -> ExtractionResult:
    try:
        split = split_document(images, pdf_info)
    except Exception:
        split = None
    if split is None:
        return await extractor.extract(images)

    form_images, label_images = split
    form_result, labels_result = await asyncio.gather(
        extractor.extract(form_images, region="form"),
        extractor.extract(label_images, region="labels"),
        return_exceptions=True,
    )
    if isinstance(form_result, BaseException) or isinstance(labels_result, BaseException):
        # Never worse than the baseline: one whole-page call.
        return await extractor.extract(images)

    return ExtractionResult(
        extraction=Extraction(
            form=form_result.extraction.form,
            labels=labels_result.extraction.labels,
        ),
        input_tokens=form_result.input_tokens + labels_result.input_tokens,
        output_tokens=form_result.output_tokens + labels_result.output_tokens,
        model=labels_result.model,
    )
