"""Unit tests for the deterministic rules engine."""

from app.models import (
    Extraction,
    FormFields,
    LabelImage,
    ProductType,
    Verdict,
)
from app.rules import (
    CANONICAL_WARNING,
    check_abv_cross,
    check_brand_name,
    check_health_warning,
    check_net_contents_cross,
    check_product_type,
    check_proof_consistency,
    verify,
)


def label(**kwargs) -> LabelImage:
    return LabelImage(**kwargs)


class TestHealthWarningStrict:
    def test_exact_statutory_text_passes(self):
        result = check_health_warning([label(government_warning=CANONICAL_WARNING)])
        assert result.verdict == Verdict.PASS

    def test_line_wrapped_text_passes(self):
        wrapped = CANONICAL_WARNING.replace(
            "According to the Surgeon General,", "According to\nthe Surgeon General,"
        )
        result = check_health_warning([label(government_warning=wrapped)])
        assert result.verdict == Verdict.PASS
        assert "rejoin" in result.detail

    def test_hyphenated_line_break_passes(self):
        hyphenated = CANONICAL_WARNING.replace(
            "alcoholic beverages during", "alcoholic bev-\nerages during"
        )
        result = check_health_warning([label(government_warning=hyphenated)])
        assert result.verdict == Verdict.PASS

    def test_all_caps_body_passes_with_note(self):
        # Approved labels (Lenz Moser) print the whole statement in capitals;
        # 27 CFR 16.22 requires only the heading in caps and does not forbid this.
        result = check_health_warning([label(government_warning=CANONICAL_WARNING.upper())])
        assert result.verdict == Verdict.PASS
        assert "capitals" in result.detail

    def test_all_caps_with_hyphenated_wrap_passes(self):
        text = CANONICAL_WARNING.upper().replace(
            "ALCOHOLIC BEVERAGES DURING", "ALCOHOLIC BEV-\nERAGES DURING"
        )
        result = check_health_warning([label(government_warning=text)])
        assert result.verdict == Verdict.PASS

    def test_title_case_heading_fails(self):
        title_case = CANONICAL_WARNING.replace(
            "GOVERNMENT WARNING:", "Government Warning:"
        )
        result = check_health_warning([label(government_warning=title_case)])
        assert result.verdict == Verdict.FAIL
        assert "capital" in result.detail.lower()

    def test_missing_warning_fails(self):
        result = check_health_warning([label(brand_name="Stone's Throw")])
        assert result.verdict == Verdict.FAIL

    def test_missing_numbered_clause_fails(self):
        no_clause_2 = CANONICAL_WARNING.split(" (2)")[0]
        result = check_health_warning([label(government_warning=no_clause_2)])
        assert result.verdict == Verdict.FAIL
        assert "(2)" in result.detail

    def test_small_wording_deviation_goes_to_human_not_fail(self):
        # A one-word difference is within plausible transcription error —
        # uncertainty becomes triage (NEEDS_REVIEW), not a wrong answer.
        # Observed live: a local model reading "BIRTH EFFECTS" for
        # "birth defects".
        altered = CANONICAL_WARNING.upper().replace("BIRTH DEFECTS", "BIRTH EFFECTS")
        result = check_health_warning([label(government_warning=altered)])
        assert result.verdict == Verdict.NEEDS_REVIEW
        assert "similar" in result.detail

    def test_heavily_deviating_text_still_fails(self):
        result = check_health_warning([label(
            government_warning="Drink responsibly. Alcohol may be bad for you."
        )])
        assert result.verdict == Verdict.FAIL

    def test_warning_embedded_in_surrounding_label_text_passes(self):
        # Extraction sometimes returns the whole label block; the statement
        # itself is verbatim inside it (observed live with qwen2.5vl).
        blob = (
            "Austria's newest rosé combines fruitiness and freshness.\n"
            + CANONICAL_WARNING.upper()
            + "\nPRODUCED AND BOTTLED BY WEINKELLEREI, AUSTRIA\n750ML"
        )
        result = check_health_warning([label(government_warning=blob)])
        assert result.verdict == Verdict.PASS

    def test_embedded_near_miss_needs_review(self):
        blob = (
            "Some marketing text first.\n"
            + CANONICAL_WARNING.upper().replace("BIRTH DEFECTS", "BIRTH EFFECTS")
            + "\nBOTTLER LINE AFTER"
        )
        result = check_health_warning([label(government_warning=blob)])
        assert result.verdict == Verdict.NEEDS_REVIEW

    def test_warning_found_on_any_image_in_set(self):
        # Combined-set semantics: warning on image 3 of 5, nowhere else.
        labels = [
            label(brand_name="X"),
            label(abv_raw="39% ALC / VOL"),
            label(government_warning=CANONICAL_WARNING),
            label(),
            label(),
        ]
        assert check_health_warning(labels).verdict == Verdict.PASS


class TestBrandCrossCheck:
    def test_stones_throw_case_difference_passes_with_note(self):
        form = FormFields(brand_name="STONE'S THROW")
        result = check_brand_name(form, [label(brand_name="Stone's Throw")])
        assert result.verdict == Verdict.PASS
        assert "case/punctuation" in result.detail

    def test_exact_match_passes_without_note(self):
        form = FormFields(brand_name="Stone's Throw")
        result = check_brand_name(form, [label(brand_name="Stone's Throw")])
        assert result.verdict == Verdict.PASS
        assert "Exact" in result.detail

    def test_real_mismatch_needs_review(self):
        form = FormFields(brand_name="Stone's Throw")
        result = check_brand_name(form, [label(brand_name="Stone Cold")])
        assert result.verdict == Verdict.NEEDS_REVIEW

    def test_missing_form_field_is_not_applicable(self):
        result = check_brand_name(FormFields(), [label(brand_name="Anything")])
        assert result.verdict == Verdict.NOT_APPLICABLE

    def test_no_form_at_all_is_not_applicable(self):
        result = check_brand_name(None, [label(brand_name="Anything")])
        assert result.verdict == Verdict.NOT_APPLICABLE

    def test_real_diacritic_only_difference_passes_with_note(self):
        # Approved COLA observed live: form 'BARENJAGER', label 'Bärenjäger'.
        form = FormFields(brand_name="BARENJAGER")
        result = check_brand_name(form, [label(brand_name="Bärenjäger")])
        assert result.verdict == Verdict.PASS
        assert "diacritics" in result.detail

    def test_warning_check_does_not_fold_diacritics(self):
        # The strict warning comparison must be untouched by diacritic
        # folding: a diacritic substitution in the statutory text is still
        # not an exact match (it lands in the near-miss tier, not PASS).
        altered = CANONICAL_WARNING.replace("alcoholic", "älcoholic")
        result = check_health_warning([label(government_warning=altered)])
        assert result.verdict != Verdict.PASS

    def test_brand_on_second_image_passes(self):
        form = FormFields(brand_name="Bärenjäger")
        labels = [label(), label(brand_name="Bärenjäger")]
        assert check_brand_name(form, labels).verdict == Verdict.PASS


class TestProductTypeCrossCheck:
    def test_match_selects_cfr_part(self):
        form = FormFields(product_type=ProductType.WINE)
        result = check_product_type(
            form, [label(apparent_product_type=ProductType.WINE)]
        )
        assert result.verdict == Verdict.PASS
        assert "Part 4" in result.detail

    def test_mismatch_needs_review(self):
        form = FormFields(product_type=ProductType.WINE)
        result = check_product_type(
            form, [label(apparent_product_type=ProductType.DISTILLED_SPIRITS)]
        )
        assert result.verdict == Verdict.NEEDS_REVIEW


class TestAbvCrossCheck:
    def test_bare_form_number_vs_label_statement(self):
        form = FormFields(alcohol_content_raw="12")
        result = check_abv_cross(form, [label(abv_raw="12% ALC/VOL")])
        assert result.verdict == Verdict.PASS

    def test_mismatch_flagged_not_failed(self):
        form = FormFields(alcohol_content_raw="35")
        result = check_abv_cross(form, [label(abv_raw="39% ALC / VOL")])
        assert result.verdict == Verdict.NEEDS_REVIEW
        assert "Discrepancy" in result.detail

    def test_missing_form_field_not_applicable(self):
        result = check_abv_cross(FormFields(), [label(abv_raw="12%")])
        assert result.verdict == Verdict.NOT_APPLICABLE


class TestNetContentsCrossCheck:
    def _check(self, form_raw, label_raw):
        form = FormFields(net_contents_raw=form_raw)
        return check_net_contents_cross(form, [label(net_contents=label_raw)])

    def test_identical_notation_passes(self):
        result = self._check("750 ML", "750 ML")
        assert result.verdict == Verdict.PASS

    def test_spelled_out_vs_abbreviated_passes(self):
        # The real case observed live: Bärenjäger's form says
        # 750 MILLILITERS, the label says 750 ML — same quantity.
        result = self._check("750 MILLILITERS", "750 ML")
        assert result.verdict == Verdict.PASS
        assert "same quantity" in result.detail

    def test_case_and_spacing_variants_pass(self):
        assert self._check("750 mL", "750ml").verdict == Verdict.PASS

    def test_liters_vs_milliliters_scale_passes(self):
        result = self._check("0.75 L", "750 ML")
        assert result.verdict == Verdict.PASS

    def test_metric_vs_fluid_ounces_not_auto_converted(self):
        # 25.4 fl oz ≈ 750 mL, but cross-system conversion is a
        # standards-of-fill question — never silently agree.
        result = self._check("750 ML", "25.4 FL. OZ.")
        assert result.verdict == Verdict.NEEDS_REVIEW
        assert "measurement system" in result.detail

    def test_different_quantities_flagged(self):
        result = self._check("750 ML", "700 ML")
        assert result.verdict == Verdict.NEEDS_REVIEW

    def test_unparseable_falls_back_to_string_match(self):
        result = self._check("one magnum", "ONE MAGNUM")
        assert result.verdict == Verdict.PASS

    def test_missing_form_field_not_applicable(self):
        result = check_net_contents_cross(FormFields(), [label(net_contents="750 ML")])
        assert result.verdict == Verdict.NOT_APPLICABLE


class TestProofConsistency:
    def test_consistent(self):
        result = check_proof_consistency([label(abv_raw="35%", proof_raw="70 PROOF")])
        assert result.verdict == Verdict.PASS

    def test_inconsistent_fails(self):
        result = check_proof_consistency([label(abv_raw="35%", proof_raw="80 PROOF")])
        assert result.verdict == Verdict.FAIL

    def test_no_proof_is_not_applicable(self):
        result = check_proof_consistency([label(abv_raw="12%")])
        assert result.verdict == Verdict.NOT_APPLICABLE

    def test_abv_and_proof_on_different_images(self):
        labels = [label(abv_raw="40% ALC/VOL"), label(proof_raw="80 PROOF")]
        assert check_proof_consistency(labels).verdict == Verdict.PASS


class TestAggregation:
    def _complete_label(self) -> LabelImage:
        return label(
            brand_name="Stone's Throw",
            government_warning=CANONICAL_WARNING,
            abv_raw="12% ALC/VOL",
            net_contents="750 ML",
            class_type="Red Wine",
            bottler_info="Bottled by Stone's Throw Winery, Napa, CA",
            apparent_product_type=ProductType.WINE,
        )

    def test_all_good_passes(self):
        extraction = Extraction(
            form=FormFields(
                brand_name="STONE'S THROW",
                product_type=ProductType.WINE,
                alcohol_content_raw="12%",
                net_contents_raw="750ML",
            ),
            labels=[self._complete_label()],
        )
        report = verify(extraction)
        assert report.verdict == Verdict.PASS
        assert report.cfr_part == "27 CFR Part 4"

    def test_missing_form_fields_never_fail(self):
        # Photo-only path: no form at all. Cross-checks all NOT_APPLICABLE;
        # verdict comes entirely from standalone compliance.
        report = verify(Extraction(form=None, labels=[self._complete_label()]))
        assert report.verdict == Verdict.PASS
        cross = [c for c in report.checks if c.source.value == "cross-check"]
        assert all(c.verdict == Verdict.NOT_APPLICABLE for c in cross)

    def test_fail_outranks_needs_review(self):
        bad = self._complete_label()
        bad.government_warning = None  # FAIL
        extraction = Extraction(
            form=FormFields(brand_name="Different Name"),  # NEEDS_REVIEW
            labels=[bad],
        )
        assert verify(extraction).verdict == Verdict.FAIL

    def test_needs_review_outranks_pass(self):
        extraction = Extraction(
            form=FormFields(brand_name="Different Name"),
            labels=[self._complete_label()],
        )
        assert verify(extraction).verdict == Verdict.NEEDS_REVIEW
