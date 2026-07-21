"""Scenario tests reconstructing three real approved COLAs from TTB's
Public COLA Registry.

These are hand-written Extraction objects encoding the observed facts of
each filing (field values, image counts, where mandatory information sits).
They pin the rules-engine behavior those documents demand:

- Bärenjäger (rev 07/2012): five affixed images with mandatory info
  scattered across them — the combined-set case. Form and labels both
  read 35% ALC/VOL (consistent), so it exercises a clean cross-check
  across scattered images, not a discrepancy.
- Carlo Giacosa (rev 6/2006): older form revision (no "Source of Product"
  field — irrelevant here because rules never see item numbers).
- Lenz Moser: warning printed in all capitals and hyphenated across a
  line break (ALCOHOLIC BEV- / ERAGES).

Once the extraction call exists, the PNG fixtures in tests/fixtures/ feed
end-to-end tests; these unit scenarios stay as the fast regression net.
"""

from app.models import Extraction, FormFields, LabelImage, ProductType, Verdict
from app.rules import CANONICAL_WARNING, verify


def check(report, check_id):
    return next(c for c in report.checks if c.check_id == check_id)


BARENJAGER = Extraction(
    form=FormFields(
        brand_name="BÄRENJÄGER",
        product_type=ProductType.DISTILLED_SPIRITS,
        alcohol_content_raw="35",
        net_contents_raw="750 ML",
    ),
    labels=[
        # Image 1 — front: brand only
        LabelImage(
            image_type="Brand (front) or keg collar",
            brand_name="Bärenjäger",
            class_type="Honey Liqueur",
            apparent_product_type=ProductType.DISTILLED_SPIRITS,
        ),
        # Image 2 — front: ABV and net contents live here
        LabelImage(
            image_type="Brand (front) or keg collar",
            abv_raw="35% ALC / VOL",
            net_contents="750ML",
        ),
        # Image 3 — back: government warning lives here
        LabelImage(
            image_type="Back",
            government_warning=CANONICAL_WARNING.upper(),
            bottler_info="Imported by Sazerac Company, New Orleans, LA",
        ),
        # Images 4-5 — illustration and 1"x1" medallion: no regulated text
        LabelImage(image_type="Other"),
        LabelImage(image_type="Other", dimensions='1" x 1"'),
    ],
)


class TestBarenjager:
    def test_overall_passes(self):
        # Form and labels are consistent; every mandatory element is present
        # somewhere across the five images.
        report = verify(BARENJAGER)
        assert report.verdict == Verdict.PASS

    def test_abv_matches_form_across_scattered_images(self):
        # ABV lives on image 2, not the form-adjacent image; the cross-check
        # still finds it (35 on the form, 35% ALC/VOL on the label).
        report = verify(BARENJAGER)
        abv_cross = check(report, "abv_form_match")
        assert abv_cross.verdict == Verdict.PASS
        assert "35" in abv_cross.detail

    def test_everything_passes_across_the_combined_set(self):
        # Per-image checking would fail this document: no single image
        # carries all mandatory information.
        report = verify(BARENJAGER)
        for check_id in (
            "brand_name_match",
            "product_type_match",
            "abv_form_match",
            "net_contents_form_match",
            "health_warning",
            "abv_present",
            "net_contents_present",
            "class_type_present",
            "bottler_present",
        ):
            assert check(report, check_id).verdict == Verdict.PASS, check_id

    def test_cfr_part_5_selected(self):
        assert verify(BARENJAGER).cfr_part == "27 CFR Part 5"


CARLO_GIACOSA = Extraction(
    # Rev 6/2006 form: brand name sits at Item 5 on paper, but the rules
    # engine never sees item numbers — extraction is by adjacent label text.
    form=FormFields(
        brand_name="CARLO GIACOSA",
        product_type=ProductType.WINE,
        alcohol_content_raw="14%",
        net_contents_raw="750 ML",
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


class TestCarloGiacosa:
    def test_passes_overall(self):
        report = verify(CARLO_GIACOSA)
        assert report.verdict == Verdict.PASS

    def test_brand_case_difference_noted_not_failed(self):
        result = check(verify(CARLO_GIACOSA), "brand_name_match")
        assert result.verdict == Verdict.PASS
        assert "case/punctuation" in result.detail

    def test_cfr_part_4_selected(self):
        assert verify(CARLO_GIACOSA).cfr_part == "27 CFR Part 4"


# Warning as printed on the Lenz Moser back label: all capitals, wrapped,
# with ALCOHOLIC BEV- / ERAGES hyphenated across the line break.
LENZ_MOSER_WARNING = (
    "GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON\n"
    "GENERAL, WOMEN SHOULD NOT DRINK ALCOHOLIC BEV-\n"
    "ERAGES DURING PREGNANCY BECAUSE OF THE RISK OF\n"
    "BIRTH DEFECTS. (2) CONSUMPTION OF ALCOHOLIC BEVERAGES\n"
    "IMPAIRS YOUR ABILITY TO DRIVE A CAR OR OPERATE\n"
    "MACHINERY, AND MAY CAUSE HEALTH PROBLEMS."
)

LENZ_MOSER = Extraction(
    form=FormFields(
        brand_name="LENZ MOSER",
        product_type=ProductType.WINE,
        alcohol_content_raw="12%",
        net_contents_raw="750ML",
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
            government_warning=LENZ_MOSER_WARNING,
            abv_raw="12% ALC/VOL",
            net_contents="750 ML",
            bottler_info="Produced and bottled by Weinkellerei Lenz Moser, Austria",
        ),
    ],
)


class TestLenzMoser:
    def test_passes_overall(self):
        assert verify(LENZ_MOSER).verdict == Verdict.PASS

    def test_hyphenated_all_caps_warning_passes(self):
        result = check(verify(LENZ_MOSER), "health_warning")
        assert result.verdict == Verdict.PASS

    def test_net_contents_spacing_difference_matches(self):
        # Form says 750ML, label says 750 ML.
        result = check(verify(LENZ_MOSER), "net_contents_form_match")
        assert result.verdict == Verdict.PASS
