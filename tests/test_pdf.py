"""Instruction-page classification against the real blank 04/2023 form.

Runs on pypdf's text layer only — no poppler needed, so this works on any
dev box even though rendering itself requires the Docker image.
"""

from pathlib import Path

import pytest

import app.pdf as pdf_module
from app.pdf import MAX_RENDERED_PAGES, is_instruction_page, render_pdf, select_pages

BLANK_FORM = Path(__file__).parent / "fixtures" / "blank-form-5100-31-2023-04.pdf"


class TestIsInstructionPage:
    def test_form_page_kept_even_though_it_mentions_paperwork_act(self):
        # Page 1 references the Paperwork Reduction Act notice; that alone
        # must not classify it as boilerplate.
        text = (
            "APPLICATION FOR AND CERTIFICATION/EXEMPTION OF LABEL/BOTTLE "
            "APPROVAL (See Instructions and Paperwork Reduction Act Notice) "
            "8. BRAND NAME ..."
        )
        assert not is_instruction_page(text)

    def test_conditions_page_skipped(self):
        assert is_instruction_page(
            "A. This certificate does not relieve you from liability for "
            "violations of the Federal Alcohol Administration Act."
        )

    def test_allowable_revisions_page_skipped(self):
        assert is_instruction_page("V. ALLOWABLE REVISIONS TO APPROVED LABELS ...")

    def test_scanned_page_without_text_layer_kept(self):
        assert not is_instruction_page(None)
        assert not is_instruction_page("   ")

    def test_label_artwork_page_kept(self):
        assert not is_instruction_page("Image Type: Brand (front) or keg collar")


class TestPageCap:
    def test_render_pdf_caps_page_count(self, monkeypatch):
        # A crafted PDF whose surviving pages exceed the cap must be
        # truncated, so it can't fan out unbounded rendering / inference.
        many_pages = list(range(1, MAX_RENDERED_PAGES + 20))
        monkeypatch.setattr(pdf_module, "select_pages", lambda _b: many_pages)

        rendered_pages = []

        class FakeImage:
            def save(self, buf, format):
                buf.write(b"\x89PNG\r\n\x1a\n")

        def fake_convert(_bytes, dpi, first_page, last_page, poppler_path):
            rendered_pages.append(first_page)
            return [FakeImage()]

        monkeypatch.setattr(pdf_module, "convert_from_bytes", fake_convert)

        images = render_pdf(b"%PDF-fake")
        assert len(images) == MAX_RENDERED_PAGES
        assert len(rendered_pages) == MAX_RENDERED_PAGES


@pytest.mark.skipif(not BLANK_FORM.exists(), reason="blank form fixture missing")
class TestBlankFormFixture:
    def test_only_the_form_page_survives(self):
        # The 04/2023 blank form: page 1 is the form, pages 2-5 are static
        # instructions. All four instruction pages must be skipped.
        assert select_pages(BLANK_FORM.read_bytes()) == [1]
