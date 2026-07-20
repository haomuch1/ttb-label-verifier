"""Deterministic rules engine. The model extracts; this module judges.

Every verdict in the system originates here, in plain auditable Python.
The health-warning comparison happens against the canonical statutory
string below — never inside the model.
"""

from difflib import SequenceMatcher

from app.models import (
    CFR_PART,
    CheckResult,
    CheckSource,
    Extraction,
    FormFields,
    LabelImage,
    PRODUCT_TYPE_DISPLAY,
    Verdict,
    VerificationReport,
)
from app.textnorm import (
    normalize_loose,
    normalize_warning,
    parse_abv,
    parse_net_contents,
    parse_proof,
)

# 27 CFR 16.21 — verbatim statutory text.
CANONICAL_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should "
    "not drink alcoholic beverages during pregnancy because of the risk of "
    "birth defects. (2) Consumption of alcoholic beverages impairs your "
    "ability to drive a car or operate machinery, and may cause health "
    "problems."
)

# 27 CFR 16.22 requires the words "GOVERNMENT WARNING" in capital letters;
# it does not forbid printing the whole statement in capitals, and approved
# labels routinely do (Lenz Moser's does). The strict comparison therefore
# accepts exactly two casings: the statutory mixed case, or the entire
# statement uppercased. Anything else — including a title-case
# "Government Warning:" — fails.
CANONICAL_WARNING_ALL_CAPS = CANONICAL_WARNING.upper()

ABV_MATCH_TOLERANCE = 0.05   # form vs. label, in percentage points
PROOF_TOLERANCE = 0.1        # proof vs. 2 × ABV


def verify(extraction: Extraction) -> VerificationReport:
    form = extraction.form
    labels = extraction.labels

    checks = [
        # Cross-checks: form vs. label artwork. Each runs only if its form
        # field is present; a missing form field is NOT_APPLICABLE, never a
        # failure.
        check_brand_name(form, labels),
        check_product_type(form, labels),
        check_abv_cross(form, labels),
        check_net_contents_cross(form, labels),
        # Standalone compliance: the combined label set vs. the CFR.
        check_health_warning(labels),
        check_abv_present(labels),
        check_proof_consistency(labels),
        check_net_contents_present(labels),
        check_class_type_present(labels),
        check_bottler_present(labels),
    ]

    return VerificationReport(
        verdict=_aggregate(checks),
        cfr_part=_governing_cfr_part(form, labels),
        checks=checks,
    )


def _aggregate(checks: list[CheckResult]) -> Verdict:
    verdicts = {c.verdict for c in checks}
    if Verdict.FAIL in verdicts:
        return Verdict.FAIL
    if Verdict.NEEDS_REVIEW in verdicts:
        return Verdict.NEEDS_REVIEW
    return Verdict.PASS


def _governing_cfr_part(form: FormFields | None, labels: list[LabelImage]) -> str | None:
    if form and form.product_type:
        return CFR_PART[form.product_type]
    for label in labels:
        if label.apparent_product_type:
            return CFR_PART[label.apparent_product_type]
    return None


# --------------------------------------------------------------------------
# Cross-checks (form vs. label artwork)
# --------------------------------------------------------------------------

def _not_applicable(check_id: str, name: str, detail: str) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        name=name,
        source=CheckSource.CROSS_CHECK,
        verdict=Verdict.NOT_APPLICABLE,
        detail=detail,
    )


_NO_FORM = "No form fields available (standalone label input); cross-check skipped."


def check_brand_name(form: FormFields | None, labels: list[LabelImage]) -> CheckResult:
    check_id, name = "brand_name_match", "Brand name (form vs. label)"
    if form is None:
        return _not_applicable(check_id, name, _NO_FORM)
    if not form.brand_name:
        return _not_applicable(
            check_id, name, "Form has no brand name field on this revision; cross-check skipped."
        )

    label_brands = [l.brand_name for l in labels if l.brand_name]
    if not label_brands:
        return CheckResult(
            check_id=check_id, name=name, source=CheckSource.CROSS_CHECK,
            verdict=Verdict.NEEDS_REVIEW,
            detail=f"Form brand name is '{form.brand_name}' but no brand name was found on any label image.",
        )

    form_norm = normalize_loose(form.brand_name)
    for brand in label_brands:
        if brand == form.brand_name:
            return CheckResult(
                check_id=check_id, name=name, source=CheckSource.CROSS_CHECK,
                verdict=Verdict.PASS,
                detail=f"Exact match: '{form.brand_name}'.",
            )
    for brand in label_brands:
        if normalize_loose(brand) == form_norm:
            return CheckResult(
                check_id=check_id, name=name, source=CheckSource.CROSS_CHECK,
                verdict=Verdict.PASS,
                detail=(
                    f"Match (differs only in case/punctuation/diacritics): "
                    f"form '{form.brand_name}' vs. label '{brand}'."
                ),
            )
    return CheckResult(
        check_id=check_id, name=name, source=CheckSource.CROSS_CHECK,
        verdict=Verdict.NEEDS_REVIEW,
        detail=(
            f"Form brand name '{form.brand_name}' does not match label brand name(s): "
            + ", ".join(f"'{b}'" for b in label_brands) + "."
        ),
    )


def check_product_type(form: FormFields | None, labels: list[LabelImage]) -> CheckResult:
    check_id, name = "product_type_match", "Product type (form checkbox vs. label)"
    if form is None:
        return _not_applicable(check_id, name, _NO_FORM)
    if not form.product_type:
        return _not_applicable(
            check_id, name, "No product type checkbox read from the form; cross-check skipped."
        )

    form_display = PRODUCT_TYPE_DISPLAY[form.product_type]
    cfr = CFR_PART[form.product_type]
    label_types = {l.apparent_product_type for l in labels if l.apparent_product_type}

    if not label_types:
        return CheckResult(
            check_id=check_id, name=name, source=CheckSource.CROSS_CHECK,
            verdict=Verdict.NEEDS_REVIEW,
            detail=(
                f"Form is marked {form_display} ({cfr}) but the product category could not "
                "be determined from the label images."
            ),
        )
    if form.product_type in label_types:
        return CheckResult(
            check_id=check_id, name=name, source=CheckSource.CROSS_CHECK,
            verdict=Verdict.PASS,
            detail=f"Form and label agree: {form_display} — governed by {cfr}.",
        )
    observed = ", ".join(PRODUCT_TYPE_DISPLAY[t] for t in sorted(label_types))
    return CheckResult(
        check_id=check_id, name=name, source=CheckSource.CROSS_CHECK,
        verdict=Verdict.NEEDS_REVIEW,
        detail=f"Form is marked {form_display} but the label presents as: {observed}.",
    )


def check_abv_cross(form: FormFields | None, labels: list[LabelImage]) -> CheckResult:
    check_id, name = "abv_form_match", "Alcohol content (form vs. label)"
    if form is None:
        return _not_applicable(check_id, name, _NO_FORM)
    if not form.alcohol_content_raw:
        return _not_applicable(
            check_id, name,
            "Form has no alcohol content field on this revision; standalone ABV check still applies.",
        )

    form_abv = parse_abv(form.alcohol_content_raw)
    if form_abv is None:
        return CheckResult(
            check_id=check_id, name=name, source=CheckSource.CROSS_CHECK,
            verdict=Verdict.NEEDS_REVIEW,
            detail=f"Could not parse form alcohol content '{form.alcohol_content_raw}'.",
        )

    label_values = [(l.abv_raw, parse_abv(l.abv_raw)) for l in labels if l.abv_raw]
    parsed = [(raw, v) for raw, v in label_values if v is not None]
    if not parsed:
        return _not_applicable(
            check_id, name,
            "No alcohol content found on the labels to compare against; "
            "the standalone ABV check reports that separately.",
        )

    for raw, value in parsed:
        if abs(value - form_abv) <= ABV_MATCH_TOLERANCE:
            return CheckResult(
                check_id=check_id, name=name, source=CheckSource.CROSS_CHECK,
                verdict=Verdict.PASS,
                detail=f"Form states '{form.alcohol_content_raw}' and label states '{raw}' — consistent at {value:g}%.",
            )
    label_desc = ", ".join(f"'{raw}' ({v:g}%)" for raw, v in parsed)
    return CheckResult(
        check_id=check_id, name=name, source=CheckSource.CROSS_CHECK,
        verdict=Verdict.NEEDS_REVIEW,
        detail=(
            f"Discrepancy: form states '{form.alcohol_content_raw}' ({form_abv:g}%) "
            f"but label states {label_desc}. Flagged for agent review."
        ),
    )


def check_net_contents_cross(form: FormFields | None, labels: list[LabelImage]) -> CheckResult:
    check_id, name = "net_contents_form_match", "Net contents (form vs. label)"
    if form is None:
        return _not_applicable(check_id, name, _NO_FORM)
    if not form.net_contents_raw:
        return _not_applicable(
            check_id, name,
            "Form has no net contents field on this revision; standalone check still applies.",
        )

    label_values = [l.net_contents for l in labels if l.net_contents]
    if not label_values:
        return _not_applicable(
            check_id, name,
            "No net contents found on the labels to compare against; "
            "the standalone check reports that separately.",
        )

    # Compare quantities, not unit spellings: "750 MILLILITERS", "750 ML",
    # and "0.75 L" are the same amount.
    form_qty = parse_net_contents(form.net_contents_raw)
    parsed = [(value, parse_net_contents(value)) for value in label_values]
    if form_qty is not None:
        form_amount, form_system = form_qty
        unit_word = "mL" if form_system == "metric" else "fl oz"
        for raw, qty in parsed:
            if qty and qty[1] == form_system and abs(qty[0] - form_amount) < 0.01:
                note = (
                    "" if raw == form.net_contents_raw
                    else f" — same quantity ({form_amount:g} {unit_word}), different notation"
                )
                return CheckResult(
                    check_id=check_id, name=name, source=CheckSource.CROSS_CHECK,
                    verdict=Verdict.PASS,
                    detail=f"Form '{form.net_contents_raw}' matches label '{raw}'{note}.",
                )
        # No same-system match. If the label uses a different measurement
        # system (metric vs US fluid ounces), do NOT convert across
        # systems — that's a standards-of-fill question for a human.
        other_system = [
            (raw, qty) for raw, qty in parsed if qty and qty[1] != form_system
        ]
        if other_system and not any(qty and qty[1] == form_system for _, qty in parsed):
            raws = ", ".join(f"'{raw}'" for raw, _ in other_system)
            return CheckResult(
                check_id=check_id, name=name, source=CheckSource.CROSS_CHECK,
                verdict=Verdict.NEEDS_REVIEW,
                detail=(
                    f"Form states '{form.net_contents_raw}' but the label uses a "
                    f"different measurement system: {raws}. Not converted "
                    "automatically — standards of fill should be checked by a person."
                ),
            )

    # Fallback for unparseable statements: loose string comparison.
    form_key = normalize_loose(form.net_contents_raw).replace(" ", "")
    for value in label_values:
        if normalize_loose(value).replace(" ", "") == form_key:
            return CheckResult(
                check_id=check_id, name=name, source=CheckSource.CROSS_CHECK,
                verdict=Verdict.PASS,
                detail=f"Form '{form.net_contents_raw}' matches label '{value}'.",
            )
    return CheckResult(
        check_id=check_id, name=name, source=CheckSource.CROSS_CHECK,
        verdict=Verdict.NEEDS_REVIEW,
        detail=(
            f"Form states '{form.net_contents_raw}' but label states: "
            + ", ".join(f"'{v}'" for v in label_values) + "."
        ),
    )


# --------------------------------------------------------------------------
# Standalone compliance (combined label set vs. the CFR)
# --------------------------------------------------------------------------

# Below this similarity to the statutory text, a mismatched warning is a
# confident FAIL; at or above it (but not exact) the mismatch is within
# plausible transcription error and goes to a human instead. Uncertainty
# becomes triage, not a wrong answer.
NEAR_MISS_RATIO = 0.90

_VERDICT_RANK = {Verdict.PASS: 0, Verdict.NEEDS_REVIEW: 1, Verdict.FAIL: 2}


def _warning_span(norm: str) -> str:
    """Cut the transcription down to the warning statement itself.

    Extraction sometimes returns the warning embedded in surrounding label
    text (marketing copy before, bottler line after). The statement starts
    at 'GOVERNMENT WARNING' when that heading exists; comparisons then use
    a statute-length window so trailing unrelated text doesn't count
    against a verbatim statement.
    """
    idx = norm.casefold().find("government warning")
    return norm[idx:] if idx >= 0 else norm


def _evaluate_warning(norm: str) -> tuple[Verdict, str]:
    span = _warning_span(norm)
    window = span[: len(CANONICAL_WARNING)]
    if window == CANONICAL_WARNING:
        return Verdict.PASS, "Warning text matches 27 CFR 16.21 verbatim."
    if window == CANONICAL_WARNING_ALL_CAPS:
        return Verdict.PASS, (
            "Warning text matches 27 CFR 16.21, printed entirely in capitals "
            "('GOVERNMENT WARNING' heading correctly capitalized; all-caps body "
            "is accepted practice under 27 CFR 16.22)."
        )
    if window.casefold() == CANONICAL_WARNING.casefold():
        return Verdict.FAIL, (
            "Warning wording is correct but capitalization violates "
            "27 CFR 16.21/16.22 — 'GOVERNMENT WARNING:' must appear in capital "
            f"letters (label prints: '{window[:30]}...')."
        )
    loose_window = span[: int(len(CANONICAL_WARNING) * 1.15)]
    ratio = SequenceMatcher(
        None, loose_window.casefold(), CANONICAL_WARNING.casefold()
    ).ratio()
    if ratio >= NEAR_MISS_RATIO:
        a, b = _first_divergence(loose_window, CANONICAL_WARNING)
        return Verdict.NEEDS_REVIEW, (
            f"Warning text is {ratio:.0%} similar to the statutory text but not "
            f"exact — label reads '...{a}...' where the statute reads '...{b}...'. "
            "This is within plausible transcription error; a person should "
            "verify the warning on the label directly."
        )
    return Verdict.FAIL, _diagnose_warning(span)


def check_health_warning(labels: list[LabelImage]) -> CheckResult:
    check_id, name = "health_warning", "Government health warning (27 CFR 16.21)"
    candidates = [l.government_warning for l in labels if l.government_warning]
    if not candidates:
        return CheckResult(
            check_id=check_id, name=name, source=CheckSource.STANDALONE,
            verdict=Verdict.FAIL,
            detail="No government health warning found on any label image.",
        )

    outcomes = [_evaluate_warning(normalize_warning(c)) for c in candidates]
    verdict, detail = min(outcomes, key=lambda o: _VERDICT_RANK[o[0]])
    if verdict == Verdict.PASS:
        exact_raw = any(
            c in (CANONICAL_WARNING, CANONICAL_WARNING_ALL_CAPS) for c in candidates
        )
        if not exact_raw and detail.endswith("verbatim."):
            detail = detail[:-1] + " (matched after rejoining line-wrapped/hyphenated text)."
    return CheckResult(
        check_id=check_id, name=name, source=CheckSource.STANDALONE,
        verdict=verdict, detail=detail,
    )


def _diagnose_warning(norm: str) -> str:
    if norm.casefold() == CANONICAL_WARNING.casefold():
        return (
            "Warning wording is correct but capitalization violates 27 CFR 16.21/16.22 — "
            "'GOVERNMENT WARNING:' must appear in capital letters "
            f"(label prints: '{norm[:30]}...')."
        )
    reasons = []
    if not norm.startswith("GOVERNMENT WARNING:"):
        if norm.casefold().startswith("government warning"):
            reasons.append("the 'GOVERNMENT WARNING:' heading is not in all capitals")
        else:
            reasons.append("the 'GOVERNMENT WARNING:' heading is missing")
    if "(1)" not in norm:
        reasons.append("numbered clause (1) is missing")
    if "(2)" not in norm:
        reasons.append("numbered clause (2) is missing")
    if reasons:
        return "Warning does not comply with 27 CFR 16.21: " + "; ".join(reasons) + "."
    a, b = _first_divergence(norm, CANONICAL_WARNING)
    return (
        "Warning text deviates from the statutory text of 27 CFR 16.21. "
        f"Label reads '...{a}...' where the statute reads '...{b}...'."
    )


def _first_divergence(a: str, b: str, context: int = 25) -> tuple[str, str]:
    limit = min(len(a), len(b))
    i = next((k for k in range(limit) if a[k] != b[k]), limit)
    start = max(0, i - context)
    end = i + context
    return a[start:end], b[start:end]


def check_abv_present(labels: list[LabelImage]) -> CheckResult:
    check_id, name = "abv_present", "Alcohol content on label"
    stated = [(l.abv_raw, parse_abv(l.abv_raw)) for l in labels if l.abv_raw]
    parsed = [(raw, v) for raw, v in stated if v is not None]
    if parsed:
        raw, value = parsed[0]
        return CheckResult(
            check_id=check_id, name=name, source=CheckSource.STANDALONE,
            verdict=Verdict.PASS,
            detail=f"Alcohol content stated: '{raw}' ({value:g}% ABV).",
        )
    if stated:
        raws = ", ".join(f"'{raw}'" for raw, _ in stated)
        return CheckResult(
            check_id=check_id, name=name, source=CheckSource.STANDALONE,
            verdict=Verdict.NEEDS_REVIEW,
            detail=f"An alcohol content statement was found but could not be parsed: {raws}.",
        )
    return CheckResult(
        check_id=check_id, name=name, source=CheckSource.STANDALONE,
        verdict=Verdict.FAIL,
        detail="No alcohol content statement found on any label image.",
    )


def check_proof_consistency(labels: list[LabelImage]) -> CheckResult:
    check_id, name = "proof_consistency", "Proof vs. ABV consistency"
    proofs = [parse_proof(l.proof_raw) for l in labels if l.proof_raw]
    proofs = [p for p in proofs if p is not None]
    if not proofs:
        return CheckResult(
            check_id=check_id, name=name, source=CheckSource.STANDALONE,
            verdict=Verdict.NOT_APPLICABLE,
            detail="No proof statement on the labels; proof is optional.",
        )
    abvs = [parse_abv(l.abv_raw) for l in labels if l.abv_raw]
    abvs = [v for v in abvs if v is not None]
    if not abvs:
        return CheckResult(
            check_id=check_id, name=name, source=CheckSource.STANDALONE,
            verdict=Verdict.NEEDS_REVIEW,
            detail=f"Label states {proofs[0]:g} proof but no ABV was found to check it against.",
        )
    for proof in proofs:
        for abv in abvs:
            if abs(proof - 2 * abv) <= PROOF_TOLERANCE:
                return CheckResult(
                    check_id=check_id, name=name, source=CheckSource.STANDALONE,
                    verdict=Verdict.PASS,
                    detail=f"{proof:g} proof is consistent with {abv:g}% ABV (proof = 2 × ABV).",
                )
    return CheckResult(
        check_id=check_id, name=name, source=CheckSource.STANDALONE,
        verdict=Verdict.FAIL,
        detail=(
            f"Inconsistent: label states {proofs[0]:g} proof but {abvs[0]:g}% ABV "
            f"(expected {2 * abvs[0]:g} proof)."
        ),
    )


def _presence_check(
    check_id: str, name: str, values: list[str], missing_detail: str
) -> CheckResult:
    if values:
        return CheckResult(
            check_id=check_id, name=name, source=CheckSource.STANDALONE,
            verdict=Verdict.PASS,
            detail=f"Present: '{values[0]}'.",
        )
    return CheckResult(
        check_id=check_id, name=name, source=CheckSource.STANDALONE,
        verdict=Verdict.FAIL,
        detail=missing_detail,
    )


def check_net_contents_present(labels: list[LabelImage]) -> CheckResult:
    return _presence_check(
        "net_contents_present", "Net contents on label",
        [l.net_contents for l in labels if l.net_contents],
        "No net contents statement found on any label image.",
    )


def check_class_type_present(labels: list[LabelImage]) -> CheckResult:
    return _presence_check(
        "class_type_present", "Class/type designation on label",
        [l.class_type for l in labels if l.class_type],
        "No class/type designation found on any label image.",
    )


def check_bottler_present(labels: list[LabelImage]) -> CheckResult:
    return _presence_check(
        "bottler_present", "Bottler name and address on label",
        [l.bottler_info for l in labels if l.bottler_info],
        "No bottler/producer name and address found on any label image.",
    )
