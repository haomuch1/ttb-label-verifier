"""Mock backend: fixture-derived extractions, zero network.

Lets every downstream component - endpoints, PDF handling, UI, batch
mode, rate limiting - be built and tested end-to-end with no API calls
and no local model. Returns one of three canned extractions derived from
the real approved COLAs used as test fixtures, chosen deterministically
from the upload's bytes so a batch shows varied results.
"""

import asyncio
import hashlib

from app.extractors.base import ExtractionResult
from app.models import Extraction, FormFields, LabelImage, ProductType
from app.rules import CANONICAL_WARNING

_BARENJAGER = Extraction(
    form=FormFields(
        brand_name="BÄRENJÄGER",
        brand_name_label="BRAND NAME",
        product_type=ProductType.DISTILLED_SPIRITS,
        product_type_label="TYPE OF PRODUCT",
        alcohol_content_raw="35",
        alcohol_content_label="ALCOHOL CONTENT",
        net_contents_raw="750 ML",
        net_contents_label="NET CONTENTS",
    ),
    labels=[
        LabelImage(
            image_type="Brand (front) or keg collar",
            brand_name="Bärenjäger",
            class_type="Honey Liqueur",
            apparent_product_type=ProductType.DISTILLED_SPIRITS,
        ),
        LabelImage(
            image_type="Brand (front) or keg collar",
            abv_raw="39% ALC / VOL",
            net_contents="750ML",
        ),
        LabelImage(
            image_type="Back",
            government_warning=CANONICAL_WARNING.upper(),
            bottler_info="Imported by Sazerac Company, New Orleans, LA",
        ),
        LabelImage(image_type="Other"),
        LabelImage(image_type="Other", dimensions='1" x 1"'),
    ],
)

_CARLO_GIACOSA = Extraction(
    form=FormFields(
        brand_name="CARLO GIACOSA",
        brand_name_label="BRAND NAME",
        product_type=ProductType.WINE,
        product_type_label="TYPE OF PRODUCT",
        alcohol_content_raw="14%",
        alcohol_content_label="ALCOHOL CONTENT",
        net_contents_raw="750 ML",
        net_contents_label="NET CONTENTS",
    ),
    labels=[
        LabelImage(
            image_type="Brand (front) or keg collar",
            brand_name="Carlo Giacosa",
            class_type="Barbera d'Alba",
            abv_raw="14% ALC./VOL.",
            net_contents="750 ML",
            apparent_product_type=ProductType.WINE,
        ),
        LabelImage(
            image_type="Back",
            government_warning=CANONICAL_WARNING,
            bottler_info="Imported by Vinifera Imports, Ronkonkoma, NY",
        ),
    ],
)

_LENZ_MOSER_WARNING = (
    "GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON\n"
    "GENERAL, WOMEN SHOULD NOT DRINK ALCOHOLIC BEV-\n"
    "ERAGES DURING PREGNANCY BECAUSE OF THE RISK OF\n"
    "BIRTH DEFECTS. (2) CONSUMPTION OF ALCOHOLIC BEVERAGES\n"
    "IMPAIRS YOUR ABILITY TO DRIVE A CAR OR OPERATE\n"
    "MACHINERY, AND MAY CAUSE HEALTH PROBLEMS."
)

_LENZ_MOSER = Extraction(
    form=FormFields(
        brand_name="LENZ MOSER",
        brand_name_label="BRAND NAME",
        product_type=ProductType.WINE,
        product_type_label="TYPE OF PRODUCT",
        alcohol_content_raw="12%",
        alcohol_content_label="ALCOHOL CONTENT",
        net_contents_raw="750ML",
        net_contents_label="NET CONTENTS",
    ),
    labels=[
        LabelImage(
            image_type="Brand (front) or keg collar",
            brand_name="Lenz Moser",
            class_type="Blaufränkisch",
            apparent_product_type=ProductType.WINE,
        ),
        LabelImage(
            image_type="Back",
            government_warning=_LENZ_MOSER_WARNING,
            abv_raw="12% ALC/VOL",
            net_contents="750 ML",
            bottler_info="Produced and bottled by Weinkellerei Lenz Moser, Austria",
        ),
    ],
)

_CANNED = [_BARENJAGER, _CARLO_GIACOSA, _LENZ_MOSER]


class MockExtractor:
    name = "mock"

    async def extract(
        self, images: list[tuple[bytes, str]], region: str | None = None
    ) -> ExtractionResult:
        await asyncio.sleep(0.05)  # keep async paths honest
        digest = hashlib.sha256(images[0][0]).digest()
        extraction = _CANNED[digest[0] % len(_CANNED)]
        return ExtractionResult(
            extraction=extraction.model_copy(deep=True),
            input_tokens=0,
            output_tokens=0,
            model="mock",
        )
