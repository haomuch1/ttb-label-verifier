"""Data models: what the extraction call returns and what the rules produce.

Design rules baked into these shapes, learned from real approved COLAs
(Bärenjäger, Carlo Giacosa, Lenz Moser):

- Every form field is Optional. Item numbers shift between form revisions
  (Carlo Giacosa's 6/2006 revision lacks "Source of Product", moving brand
  name to Item 5), and older revisions carry fields the blank 04/2023 form
  does not. A cross-check runs when its form field is present and falls
  back to standalone compliance when absent — a missing form field is
  never a failure.

- A filing carries multiple affixed label images (Bärenjäger has five)
  with mandatory information scattered across them. Rules therefore
  operate on the combined set: "does this appear anywhere across the
  images", never per-image.

- Extraction returns verbatim text and observations only. Verdicts exist
  solely in CheckResult/VerificationReport, which only the rules engine
  produces.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ProductType(str, Enum):
    WINE = "wine"
    DISTILLED_SPIRITS = "distilled_spirits"
    MALT_BEVERAGE = "malt_beverage"


CFR_PART: dict[ProductType, str] = {
    ProductType.WINE: "27 CFR Part 4",
    ProductType.DISTILLED_SPIRITS: "27 CFR Part 5",
    ProductType.MALT_BEVERAGE: "27 CFR Part 7",
}

PRODUCT_TYPE_DISPLAY: dict[ProductType, str] = {
    ProductType.WINE: "Wine",
    ProductType.DISTILLED_SPIRITS: "Distilled Spirits",
    ProductType.MALT_BEVERAGE: "Malt Beverages",
}


class FormFields(BaseModel):
    """Fields read from the COLA form portion of the document.

    Extraction locates these by adjacent label text ("BRAND NAME",
    "ALCOHOL CONTENT", "NET CONTENTS", "TYPE OF PRODUCT"), never by item
    number — item numbers are not stable across form revisions.
    """

    brand_name: Optional[str] = None
    brand_name_label: Optional[str] = Field(
        default=None, description="Exact form-label text the value was found next to"
    )
    product_type: Optional[ProductType] = None
    product_type_label: Optional[str] = None
    alcohol_content_raw: Optional[str] = Field(
        default=None,
        description='Verbatim, e.g. "35" (Bärenjäger) or "12%" (Lenz Moser)',
    )
    alcohol_content_label: Optional[str] = None
    net_contents_raw: Optional[str] = None
    net_contents_label: Optional[str] = None


class LabelImage(BaseModel):
    """Observations from one affixed label image. All fields optional —
    mandatory information is scattered across the label set."""

    image_type: Optional[str] = Field(
        default=None,
        description='The "Image Type:" caption, e.g. "Brand (front) or keg collar", "Back", "Other"',
    )
    dimensions: Optional[str] = None
    brand_name: Optional[str] = None
    government_warning: Optional[str] = Field(
        default=None,
        description="Verbatim as printed, preserving line breaks, hyphenation, and case",
    )
    abv_raw: Optional[str] = None
    proof_raw: Optional[str] = None
    net_contents: Optional[str] = None
    class_type: Optional[str] = Field(
        default=None, description='Class/type designation, e.g. "Liqueur", "Barbera d\'Alba"'
    )
    bottler_info: Optional[str] = Field(
        default=None, description="Bottler/producer/importer name and address as printed"
    )
    apparent_product_type: Optional[ProductType] = Field(
        default=None,
        description="What category the label presents as — an observation, not a verdict",
    )


class Extraction(BaseModel):
    """Everything the single vision call returns. No verdicts."""

    form: Optional[FormFields] = Field(
        default=None, description="None when the input is a standalone label photo"
    )
    labels: list[LabelImage] = Field(default_factory=list)


class Verdict(str, Enum):
    PASS = "PASS"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"  # e.g. cross-check with no form field; never affects the overall verdict


class CheckSource(str, Enum):
    CROSS_CHECK = "cross-check"      # form vs. label artwork
    STANDALONE = "standalone"        # label alone vs. the CFR


class CheckResult(BaseModel):
    check_id: str
    name: str
    source: CheckSource
    verdict: Verdict
    detail: str


class VerificationReport(BaseModel):
    verdict: Verdict
    cfr_part: Optional[str] = None
    checks: list[CheckResult]
