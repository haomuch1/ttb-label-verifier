# Approach

## How this was built

This prototype was built by directing **Claude Code** (Anthropic's agentic
coding CLI) — stated openly, since agentic AI development is the skill under
test for this position. The commit history is the development history: each
feature was specified, generated, reviewed, and committed iteratively.

## Core design: the model extracts, code judges

The single most important architectural decision. One Claude vision call reads
the uploaded document and returns **structured JSON containing only verbatim
text and observations** — what the label says, which checkbox is marked, what
the warning text literally reads. The model renders **no verdicts**.

Deterministic Python then applies the rules: the health-warning comparison
happens in code against a stored canonical string from 27 CFR 16.21, the
proof/ABV consistency check is arithmetic, the brand-name cross-check is a
normalized fuzzy comparison. This keeps the compliance judgment auditable,
testable, and immune to model drift.

## Two kinds of checking, kept separate

1. **Cross-check** — form vs. label artwork (both live in the same COLA PDF):
   brand name (Item 6) and product type checkbox (Item 5). The product type
   also selects the governing CFR part: Part 4 (wine), Part 5 (distilled
   spirits), Part 7 (malt beverages).
2. **Standalone compliance** — label alone against the CFR: health warning,
   ABV/proof, net contents, class/type, bottler name and address.

**Every cross-check field is optional.** Which fields a form carries depends
on the revision: the blank 04/2023 Form 5100.31 has no ABV or net contents
fields, but all three real filings examined (below) have both. A cross-check
runs when its field is present on the form and falls back to standalone
compliance when absent — a missing form field is never a failure
(`NOT_APPLICABLE` verdict, ignored by aggregation). The app does not invent
form fields.

## Findings from real approved COLAs

The design was corrected against three approved COLAs pulled from TTB's
Public COLA Registry (Bärenjäger, Carlo Giacosa, Lenz Moser — fixtures in
`tests/fixtures/`, hand-transcribed scenarios in
`tests/test_real_cola_scenarios.py`):

1. **Item numbers are not stable across form revisions.** Carlo Giacosa's
   6/2006 revision has Brand Name at Item 5 and no "Source of Product" field;
   later revisions have Brand Name at Item 6, and every field after a missing
   one shifts. Extraction therefore locates fields by adjacent label text
   ("BRAND NAME", "ALCOHOL CONTENT", "NET CONTENTS", "TYPE OF PRODUCT"),
   never by item number — the most likely source of silent wrong answers.
2. **Multiple labels per application are the norm.** Bärenjäger has five
   affixed images with mandatory information scattered across them (ABV and
   net contents on image 2, the warning on image 3, images 4–5 carrying no
   regulated text). All affixed labels are treated as one combined set: every
   rule asks "does this appear anywhere across the images." Per-image
   checking would fail all three real documents. Each image's "Image Type:"
   caption and printed dimensions are used as extraction signal.
3. **Warning text wraps and hyphenates on real labels.** Lenz Moser breaks
   "ALCOHOLIC BEV- / ERAGES" across a line. Before the strict comparison the
   verbatim text is normalized — whitespace collapsed, hyphenated line breaks
   rejoined — but case is never touched, because case sensitivity is what
   catches a title-case "Government Warning:" violation.
4. **All-caps warnings are approved practice.** Lenz Moser prints the entire
   statement in capitals. 27 CFR 16.22 requires the "GOVERNMENT WARNING"
   heading in capitals and does not forbid an all-caps body, so the strict
   check accepts exactly two casings — the statutory mixed case, or the whole
   statement uppercased — and fails everything else.
5. **A free real-world regression case:** Bärenjäger's form states Alcohol
   Content `35` while both its labels state `39% ALC / VOL` — a genuine
   4-point form-to-label mismatch on an approved COLA. Expected output is a
   flagged discrepancy (NEEDS REVIEW), not FAIL: cross-check mismatches go to
   a human; only standalone CFR violations (bad warning, inconsistent proof
   arithmetic, missing mandatory information) hard-fail.

## Performance constraint

Hard requirement: **under 5 seconds** for a single label (warm). A prior vendor
pilot failed at 30–40 seconds and that is the stated reason it died. Hence: one
model call per document, no chaining, batch mode fans out concurrently with
`asyncio.gather` under a semaphore.

## Tools used

- Claude Code (agentic development)
- Python / FastAPI, plain static HTML frontend (no build step)
- Claude vision API (single structured-extraction call)
- pdf2image / poppler for server-side PDF rendering
- Render free tier for deployment

## Assumptions

- Inputs are a COLA Form 5100.31 PDF (with label artwork pasted in) or a
  standalone label photo/image.
- Pages 2–4 of the standard 5100.31 PDF are static instructions and are
  skipped by matching their boilerplate.
- No persistence: nothing is stored; each request is stateless.

## Known limitations (stated deliberately)

- **Type size, characters-per-inch, and contrasting-background checks are not
  feasible from a photo** — there is no reliable physical scale reference.
  Notably, TTB's own Form 5100.31 states in Condition C that TTB does not
  routinely review for those either.
- **Treasury's internal network blocks many outbound ML endpoints.** A
  production deployment inside the Treasury network would need self-hosted
  inference or an allow-listed endpoint. The architecture isolates the
  inference call behind a single interface, so the backend can be swapped
  without touching the rule engine.
- Verdicts are advisory: NEEDS REVIEW exists precisely because a human agent
  makes the final call.
