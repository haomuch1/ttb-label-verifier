"""Unit tests for text normalization — the highest-risk piece of the build.

The warning normalization must rejoin real-world line wrapping and
hyphenation (Lenz Moser: "ALCOHOLIC BEV- / ERAGES") while never touching
case, because case is what catches title-case violations.
"""

from app.textnorm import (
    collapse_whitespace,
    normalize_loose,
    normalize_warning,
    parse_abv,
    parse_proof,
    rejoin_hyphenated_breaks,
)


class TestHyphenRejoin:
    def test_lenz_moser_hyphenation(self):
        assert (
            rejoin_hyphenated_breaks("ALCOHOLIC BEV-\nERAGES")
            == "ALCOHOLIC BEVERAGES"
        )

    def test_hyphen_with_trailing_space_before_break(self):
        assert rejoin_hyphenated_breaks("BEV- \n  ERAGES") == "BEVERAGES"

    def test_inline_hyphen_untouched(self):
        assert rejoin_hyphenated_breaks("SEMI-DRY WINE") == "SEMI-DRY WINE"

    def test_hyphen_at_break_without_following_word_untouched(self):
        assert rejoin_hyphenated_breaks("ends with -\n (1)") == "ends with -\n (1)"


class TestNormalizeWarning:
    def test_collapses_line_wrap_to_single_spaces(self):
        wrapped = "GOVERNMENT WARNING: (1) According to\nthe Surgeon General"
        assert (
            normalize_warning(wrapped)
            == "GOVERNMENT WARNING: (1) According to the Surgeon General"
        )

    def test_case_is_preserved(self):
        assert normalize_warning("Government Warning:") == "Government Warning:"

    def test_hyphenation_and_wrap_combined(self):
        text = "impairs your ability to drive a car or operate machin-\nery, and"
        assert (
            normalize_warning(text)
            == "impairs your ability to drive a car or operate machinery, and"
        )

    def test_curly_apostrophe_normalized(self):
        assert normalize_warning("driver’s") == "driver's"

    def test_idempotent_on_clean_text(self):
        clean = "GOVERNMENT WARNING: (1) Text here. (2) More text."
        assert normalize_warning(clean) == clean


class TestNormalizeLoose:
    def test_stones_throw_case_and_apostrophe(self):
        assert normalize_loose("STONE'S THROW") == normalize_loose("Stone's Throw")

    def test_apostrophe_deleted_not_spaced(self):
        assert normalize_loose("STONE'S") == "stones"

    def test_curly_apostrophe_matches_straight(self):
        assert normalize_loose("Stone’s Throw") == normalize_loose("Stone's Throw")

    def test_hyphen_treated_as_space(self):
        assert normalize_loose("Stone-Throw") == normalize_loose("Stone Throw")

    def test_accented_letters_survive(self):
        assert normalize_loose("BÄRENJÄGER") == normalize_loose("Bärenjäger")

    def test_different_names_do_not_collide(self):
        assert normalize_loose("Stone's Throw") != normalize_loose("Stone Cold")


class TestParseAbv:
    def test_bare_number_barenjager_form(self):
        assert parse_abv("35") == 35.0

    def test_percent_lenz_moser_form(self):
        assert parse_abv("12%") == 12.0

    def test_label_style_alc_vol(self):
        assert parse_abv("39% ALC / VOL") == 39.0

    def test_alc_prefix_style(self):
        assert parse_abv("ALC. 35% BY VOL.") == 35.0

    def test_decimal(self):
        assert parse_abv("12.5% ALC/VOL") == 12.5

    def test_percent_number_preferred_over_earlier_bare_number(self):
        assert parse_abv("750 ML 12% ALC/VOL") == 12.0

    def test_out_of_range_rejected(self):
        assert parse_abv("750") is None

    def test_none_and_empty(self):
        assert parse_abv(None) is None
        assert parse_abv("") is None
        assert parse_abv("no numbers here") is None


class TestParseProof:
    def test_proof_statement(self):
        assert parse_proof("70 PROOF") == 70.0

    def test_bare_number(self):
        assert parse_proof("70") == 70.0

    def test_none(self):
        assert parse_proof(None) is None


class TestCollapseWhitespace:
    def test_mixed_whitespace(self):
        assert collapse_whitespace("  a \t b \n\n c  ") == "a b c"
