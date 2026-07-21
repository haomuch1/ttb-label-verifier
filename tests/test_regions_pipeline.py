"""Anchor-split region detection and the two-region extraction pipeline."""

import asyncio
import io
import time
from pathlib import Path

import pytest
from PIL import Image

import app.pipeline as pipeline
import app.regions as regions
from app.extractors.base import ExtractionResult
from app.models import Extraction, FormFields, LabelImage
from app.pipeline import run_extraction
from app.regions import anchor_fraction_in_pdf_page, split_document

FIXTURE = Path(__file__).parent / "fixtures" / "carlo-giacosa" / "Carlo Giacosatest.png"
BLANK_FORM = Path(__file__).parent / "fixtures" / "blank-form-5100-31-2023-04.pdf"

tesseract_available = regions._tesseract_cmd() is not None


def image_height(data: bytes) -> int:
    return Image.open(io.BytesIO(data)).height


class TestAnchorDetection:
    @pytest.mark.skipif(not tesseract_available, reason="tesseract not installed")
    def test_real_fixture_splits_at_anchor(self):
        data = FIXTURE.read_bytes()
        split = split_document([(data, "image/png")])
        assert split is not None
        (form_imgs, label_imgs) = split
        assert len(form_imgs) == 1 and len(label_imgs) == 1
        total = image_height(form_imgs[0][0]) + image_height(label_imgs[0][0])
        assert total == image_height(data)
        # anchor sits roughly mid-page on this printout
        ratio = image_height(form_imgs[0][0]) / image_height(data)
        assert 0.35 < ratio < 0.75

    @pytest.mark.skipif(not tesseract_available, reason="tesseract not installed")
    def test_image_without_anchor_returns_none(self):
        img = Image.new("RGB", (600, 800), "white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        assert split_document([(buf.getvalue(), "image/png")]) is None

    def test_missing_tesseract_falls_back_cleanly(self, monkeypatch):
        monkeypatch.setattr(regions, "_tesseract_cmd", lambda: None)
        data = FIXTURE.read_bytes()
        assert regions.anchor_y_in_image(data) is None

    @pytest.mark.skipif(not BLANK_FORM.exists(), reason="blank form missing")
    def test_pdf_anchor_via_text_layer(self):
        fraction = anchor_fraction_in_pdf_page(BLANK_FORM.read_bytes(), 1)
        assert fraction is not None
        assert 0.4 < fraction < 0.7


class TestTruncatedJsonRepair:
    def test_mid_string_truncation_recovers_other_fields(self):
        # The live failure mode: a repetition loop in one field hits the
        # token budget and truncates the JSON mid-string.
        from app.extractors.ollama_extractor import parse_extraction
        truncated = (
            '{"form": {"brand_name": "EAGLEMOUNT", "product_type": "wine", '
            '"net_contents_raw": "750 ML (If any) (If any) (If an'
        )
        ex = parse_extraction(truncated)
        assert ex.form.brand_name == "EAGLEMOUNT"

    def test_valid_json_untouched(self):
        from app.extractors.ollama_extractor import parse_extraction
        ex = parse_extraction('{"form": null, "labels": []}')
        assert ex.form is None

    def test_hopeless_garbage_still_raises(self):
        from app.extractors.ollama_extractor import parse_extraction
        with pytest.raises(Exception):
            parse_extraction("not json at all")


def make_result(form=None, labels=(), tokens=10):
    return ExtractionResult(
        extraction=Extraction(form=form, labels=list(labels)),
        input_tokens=tokens, output_tokens=tokens, model="fake",
    )


GOOD_LABEL = LabelImage(brand_name="ACME", government_warning="GOVERNMENT WARNING: ...")
EMPTY_LABEL = LabelImage()


class FakeExtractor:
    """Returns form/label content keyed by region + image bytes, so a test
    can simulate a good fraction split, a mis-split, or a region error."""
    name = "fake"

    def __init__(self, frac_label_empty=False, fail_region=None, delay=0.0):
        self.calls = []            # (region, marker)
        self.frac_label_empty = frac_label_empty
        self.fail_region = fail_region
        self.delay = delay

    async def extract(self, images, region=None):
        marker = images[0][0].decode()
        self.calls.append((region, marker))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_region is not None and region == self.fail_region:
            raise RuntimeError("backend down")
        if region == "form":
            return make_result(form=FormFields(brand_name=f"FORM/{marker}"))
        if region == "labels":
            if marker.startswith("frac") and self.frac_label_empty:
                return make_result(labels=[EMPTY_LABEL])   # mis-split signal
            return make_result(labels=[GOOD_LABEL])
        return make_result(form=FormFields(brand_name="WHOLE"),
                           labels=[LabelImage(brand_name="WHOLE")])


FRAC_SPLIT = ([(b"frac-form", "image/png")], [(b"frac-label", "image/png")])
ANCHOR_SPLIT = ([(b"anchor-form", "image/png")], [(b"anchor-label", "image/png")])


class TestFractionHybrid:
    def _patch(self, monkeypatch, frac=FRAC_SPLIT, anchor=ANCHOR_SPLIT):
        monkeypatch.setattr(pipeline, "fraction_split_document", lambda imgs: frac)
        called = {"anchor": False}

        def anchor_spy(*a, **k):
            called["anchor"] = True
            return anchor

        monkeypatch.setattr(pipeline, "split_document", anchor_spy)
        return called

    def test_fraction_default_used_no_anchor_when_valid(self, monkeypatch):
        called = self._patch(monkeypatch)
        ex = FakeExtractor()
        result = asyncio.run(run_extraction(ex, [(b"page", "image/png")]))
        assert called["anchor"] is False           # tesseract never touched
        assert ("form", "frac-form") in ex.calls
        assert ("labels", "frac-label") in ex.calls
        assert result.extraction.form.brand_name == "FORM/frac-form"
        assert result.extraction.labels[0].government_warning

    def test_region_calls_run_concurrently(self, monkeypatch):
        self._patch(monkeypatch)
        ex = FakeExtractor(delay=0.15)
        start = time.perf_counter()
        asyncio.run(run_extraction(ex, [(b"page", "image/png")]))
        assert time.perf_counter() - start < 0.27   # two 0.15s calls in parallel

    def test_missplit_falls_back_to_anchor(self, monkeypatch):
        called = self._patch(monkeypatch)
        ex = FakeExtractor(frac_label_empty=True)   # frac label region empty
        result = asyncio.run(run_extraction(ex, [(b"page", "image/png")]))
        assert called["anchor"] is True             # fallback fired
        assert ("labels", "anchor-label") in ex.calls
        assert result.extraction.form.brand_name == "FORM/anchor-form"
        assert result.extraction.labels[0].government_warning

    def test_fraction_none_uses_anchor(self, monkeypatch):
        called = self._patch(monkeypatch, frac=None)
        ex = FakeExtractor()
        result = asyncio.run(run_extraction(ex, [(b"page", "image/png")]))
        assert called["anchor"] is True
        assert result.extraction.form.brand_name == "FORM/anchor-form"

    def test_both_fail_falls_back_to_whole_page(self, monkeypatch):
        self._patch(monkeypatch, frac=None, anchor=None)
        ex = FakeExtractor()
        result = asyncio.run(run_extraction(ex, [(b"page", "image/png")]))
        assert ex.calls[-1] == (None, "page")
        assert result.extraction.form.brand_name == "WHOLE"

    def test_region_error_falls_back_to_whole_page(self, monkeypatch):
        self._patch(monkeypatch)
        ex = FakeExtractor(fail_region="labels")    # both frac & anchor labels error
        result = asyncio.run(run_extraction(ex, [(b"page", "image/png")]))
        assert result.extraction.form.brand_name == "WHOLE"


class TestFractionSplitGeometry:
    def test_cut_at_fraction_of_height(self):
        img = Image.new("RGB", (400, 1000), "white")
        buf = io.BytesIO(); img.save(buf, format="PNG")
        split = regions.fraction_split_document([(buf.getvalue(), "image/png")])
        assert split is not None
        form_h = image_height(split[0][0][0])
        label_h = image_height(split[1][0][0])
        assert form_h + label_h == 1000            # full height preserved
        assert abs(form_h - 500) <= 1              # cut at 0.5

    def test_short_page_returns_none(self):
        img = Image.new("RGB", (400, 200), "white")  # < 2*MIN_REGION_PX
        buf = io.BytesIO(); img.save(buf, format="PNG")
        assert regions.fraction_split_document([(buf.getvalue(), "image/png")]) is None


class TestSplitLooksWrong:
    def _good_labels(self):
        # real label region: >=2 signals AND the warning present
        return [LabelImage(brand_name="ACME", government_warning="GOVERNMENT WARNING: ...")]

    def test_good_split_ok(self):
        assert pipeline.split_looks_wrong(FormFields(brand_name="X"), self._good_labels()) is False

    def test_empty_form_flags(self):
        assert pipeline.split_looks_wrong(None, self._good_labels()) is True
        assert pipeline.split_looks_wrong(FormFields(), self._good_labels()) is True

    def test_empty_labels_flags(self):
        assert pipeline.split_looks_wrong(FormFields(brand_name="X"), []) is True
        assert pipeline.split_looks_wrong(FormFields(brand_name="X"), [LabelImage()]) is True

    def test_too_few_signals_flags(self):
        # only one signal (warning alone) — region B not a full label region
        assert pipeline.split_looks_wrong(
            FormFields(brand_name="X"), [LabelImage(government_warning="W")]) is True

    def test_missing_warning_flags_even_with_other_content(self):
        # >=2 signals but NO warning — the too-low-cut failure mode that lost
        # the warning to region A. Must trigger fallback.
        assert pipeline.split_looks_wrong(
            FormFields(brand_name="X"),
            [LabelImage(brand_name="Y", abv_raw="12%", net_contents="750 ML")]) is True
