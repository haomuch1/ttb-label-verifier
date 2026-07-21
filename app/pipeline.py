"""Two-region concurrent extraction with a fast fraction split + fallbacks.

Fast default: split the page at a fixed fraction of its height (no OCR,
~30ms), extract the form region and label region concurrently, and merge
form fields from region A with label observations from region B.

A cheap sanity check on the results guards the fast cut: if region A didn't
yield form fields or region B lacks any plausible label content, the fixed
cut probably sliced wrong, so this document falls back to the anchor-OCR
split (tesseract, ~750ms) and re-extracts. If anchor detection also fails,
the last resort is a single whole-page extraction. Each step can only
improve input quality, never break the working baseline.
"""

import asyncio

from app.extractors.base import ExtractionResult, Extractor
from app.models import Extraction, FormFields, LabelImage
from app.regions import fraction_split_document, split_document
from app.rules import MIN_READABLE_SIGNALS, readable_signals


def split_looks_wrong(form: FormFields | None, labels: list[LabelImage]) -> bool:
    """Heuristic mis-split check on extraction results — protects the warning.

    A correct split yields a form region with form fields AND a label region
    that is a real label region: enough distinct content to judge
    (>= MIN_READABLE_SIGNALS) AND carrying the government health warning. A
    too-low fixed cut slices the warning-bearing label into the form region,
    so a warning missing from region B is the strongest signal the fixed cut
    went wrong — that's when the caller falls back to anchor OCR. Cheap: it
    only inspects the structured results already in hand.

    (A false positive — a genuinely warning-less label, or a warning the
    model happened to miss — costs only one anchor-split retry, which then
    reads the warning region correctly or confirms it is truly absent. It
    never degrades correctness, only spends the fallback it was meant to.)
    """
    if not (form and (form.brand_name or form.product_type)):
        return True
    if readable_signals(labels) < MIN_READABLE_SIGNALS:
        return True
    if not any(l.government_warning for l in labels):
        return True
    return False


def _merge(form_result: ExtractionResult, labels_result: ExtractionResult) -> ExtractionResult:
    return ExtractionResult(
        extraction=Extraction(
            form=form_result.extraction.form,
            labels=labels_result.extraction.labels,
        ),
        input_tokens=form_result.input_tokens + labels_result.input_tokens,
        output_tokens=form_result.output_tokens + labels_result.output_tokens,
        model=labels_result.model,
    )


async def _extract_regions(
    extractor: Extractor, split
) -> ExtractionResult | None:
    """Extract a (form_images, label_images) split concurrently and merge.
    Returns None if either region call errors."""
    form_images, label_images = split
    form_result, labels_result = await asyncio.gather(
        extractor.extract(form_images, region="form"),
        extractor.extract(label_images, region="labels"),
        return_exceptions=True,
    )
    if isinstance(form_result, BaseException) or isinstance(labels_result, BaseException):
        return None
    return _merge(form_result, labels_result)


async def run_extraction(
    extractor: Extractor,
    images: list[tuple[bytes, str]],
    pdf_info: tuple[bytes, int] | None = None,
) -> ExtractionResult:
    # Fast default: fixed-fraction geometry split, no OCR.
    try:
        fast = fraction_split_document(images)
    except Exception:
        fast = None
    if fast is not None:
        merged = await _extract_regions(extractor, fast)
        if merged is not None and not split_looks_wrong(
            merged.extraction.form, merged.extraction.labels
        ):
            return merged
        # Fast cut looked wrong (or a region errored) — fall through to the
        # real anchor split for this document only.

    # Fallback: cheap-anchor tesseract split.
    try:
        anchor = split_document(images, pdf_info)
    except Exception:
        anchor = None
    if anchor is not None:
        merged = await _extract_regions(extractor, anchor)
        if merged is not None:
            return merged

    # Last resort: single whole-page extraction.
    return await extractor.extract(images)
