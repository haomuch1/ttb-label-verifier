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


class RecordingExtractor:
    name = "fake"

    def __init__(self, delay=0.0, fail_regions=()):
        self.delay = delay
        self.fail_regions = set(fail_regions)
        self.calls = []

    async def extract(self, images, region=None):
        self.calls.append(region)
        await asyncio.sleep(self.delay)
        if region in self.fail_regions:
            raise RuntimeError("backend down")
        if region == "form":
            return make_result(form=FormFields(brand_name="FROM FORM REGION"))
        if region == "labels":
            return make_result(labels=[LabelImage(brand_name="FROM LABEL REGION")])
        return make_result(form=FormFields(brand_name="WHOLE PAGE"),
                           labels=[LabelImage(brand_name="WHOLE PAGE")])


FAKE_SPLIT = ([(b"form-bytes", "image/png")], [(b"label-bytes", "image/png")])


class TestPipeline:
    def test_split_merges_form_from_a_and_labels_from_b(self, monkeypatch):
        monkeypatch.setattr(pipeline, "split_document", lambda *a, **k: FAKE_SPLIT)
        ex = RecordingExtractor()
        result = asyncio.run(run_extraction(ex, [(b"page", "image/png")]))
        assert result.extraction.form.brand_name == "FROM FORM REGION"
        assert result.extraction.labels[0].brand_name == "FROM LABEL REGION"
        assert sorted(ex.calls, key=str) == ["form", "labels"]
        assert result.input_tokens == 20  # summed across both calls

    def test_region_calls_run_concurrently(self, monkeypatch):
        monkeypatch.setattr(pipeline, "split_document", lambda *a, **k: FAKE_SPLIT)
        ex = RecordingExtractor(delay=0.15)
        start = time.perf_counter()
        asyncio.run(run_extraction(ex, [(b"page", "image/png")]))
        elapsed = time.perf_counter() - start
        # two 0.15s calls in parallel ≈ 0.15s, not 0.30s
        assert elapsed < 0.27, f"calls appear sequential: {elapsed:.2f}s"

    def test_no_anchor_falls_back_to_whole_page(self, monkeypatch):
        monkeypatch.setattr(pipeline, "split_document", lambda *a, **k: None)
        ex = RecordingExtractor()
        result = asyncio.run(run_extraction(ex, [(b"page", "image/png")]))
        assert ex.calls == [None]
        assert result.extraction.form.brand_name == "WHOLE PAGE"

    def test_region_failure_falls_back_to_whole_page(self, monkeypatch):
        monkeypatch.setattr(pipeline, "split_document", lambda *a, **k: FAKE_SPLIT)
        ex = RecordingExtractor(fail_regions={"labels"})
        result = asyncio.run(run_extraction(ex, [(b"page", "image/png")]))
        assert ex.calls[-1] is None  # retried as single whole-page call
        assert result.extraction.form.brand_name == "WHOLE PAGE"

    def test_split_crash_never_propagates(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("splitter exploded")
        monkeypatch.setattr(pipeline, "split_document", boom)
        ex = RecordingExtractor()
        result = asyncio.run(run_extraction(ex, [(b"page", "image/png")]))
        assert result.extraction.form.brand_name == "WHOLE PAGE"
