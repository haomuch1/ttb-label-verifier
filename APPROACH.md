# Approach

## How this was built

This prototype was built by directing **Claude Code** (Anthropic's agentic
coding CLI) — stated openly, since agentic AI development is the skill under
test for this position. The commit history is the development history: each
feature was specified, generated, reviewed, and committed iteratively.

## Attention to requirements — decisions traced to stakeholder input

The requirements were not a spec. They were embedded in four interview
transcripts, and identifying them was part of the task. Each decision below
traces to a specific person.

**Five-second response.** Sarah Chen described a prior vendor pilot that
took 30–40 seconds per label and died because agents abandoned it: "If we
can't get results back in about 5 seconds, nobody's going to use it." This
drove a single round trip per document. (Splitting the page into two regions
later made this two concurrent calls — wall-clock stays near the slower of
the two, preserving the intent.)

**Simple interface.** Sarah set the bar at "something my mother could
figure out — she's 73," with half her team over 50. This drove the large
one-word verdict band, plain-language check descriptions, and no hunting
for buttons.

**Batch processing.** Sarah noted peak-season importers dump 200–300
applications at once, processed one at a time today. This drove batch mode
with a triage summary.

**Fuzzy identity matching.** Dave Morrison's example: "STONE'S THROW" on
the label vs "Stone's Throw" in the application is "obviously the same
thing. You need judgment." This drove case-, punctuation-, and (after real
data surfaced "Bärenjäger" vs "BARENJAGER") diacritic-insensitive matching
on brand name — reported as a match with a note, never a failure.

**Strict warning matching.** Jenny Park described the opposite rule for the
health warning: exact, word-for-word, "GOVERNMENT WARNING:" in caps; she
rejected a label using title case. This drove the deterministic strict
comparison against canonical 27 CFR 16.21 text, case preserved. The
coexistence of these two contradictory rules — forgiving for identity,
strict for the warning — is the central design tension.

**Imperfect images.** Jenny flagged labels shot at angles or with glare.
This drove the explicit unreadable-outcome path rather than a crash.

**No COLA integration, nothing sensitive stored.** Marcus Williams was
explicit: standalone proof-of-concept, nothing sensitive persisted. This
drove a design with no database and no retained label content. (The later
audit log stores decision records only — no images, no application
content — preserving the spirit of this.)

**Local inference.** Marcus noted the network blocks outbound ML
endpoints — half the prior vendor's features failed on the firewall. This
made self-hosted inference not merely cheaper but necessary for any real
internal deployment, and drove the local-first architecture.

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

1. **Cross-check** — form vs. label artwork (both live in the same COLA
   document): brand name, product type checkbox, and — on form revisions
   that carry them — alcohol content and net contents. (Fields are located
   by adjacent label text, never by item number; see finding 1 below.) The
   product type also selects the governing CFR part: Part 4 (wine), Part 5
   (distilled spirits), Part 7 (malt beverages).
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

The design was corrected against approved COLAs pulled from TTB's Public
COLA Registry (Bärenjäger, Carlo Giacosa, Lenz Moser, Eaglemount, 3 Steves
Winery — fixtures in `tests/fixtures/`, hand-transcribed scenarios in
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
   check accepts two casings of the complete verbatim statement — the
   statutory mixed case, or the whole statement uppercased — while a
   title-case rendering (Jenny Park's rejected case) FAILs. Deviations that
   are not pure casing follow the near-miss tiering described below.
5. **Mandatory information is scattered across images, so the check is on
   the combined set.** Bärenjäger's alcohol content and net contents sit on
   image 2, its warning on image 3, while images 4–5 carry no regulated
   text; form and labels agree (both 35% ALC/VOL). The design consequence is
   that a cross-check asks "does this appear anywhere across the images,"
   never per-image — per-image checking would fail this document. (An
   earlier draft treated Bärenjäger as a form-vs-label ABV discrepancy on a
   misreading of the low-resolution "35" as "39"; ground truth is 35
   everywhere, and the fixtures/tests reflect that.)

## Pluggable inference backends — a first-class design decision

Extraction sits behind a small interface (`app/extractors/`): every backend
takes document images and returns the same validated `Extraction` schema
under the same transcribe-don't-judge prompt. The backend is chosen by one
environment variable (`EXTRACTOR=anthropic|ollama|mock`, default `ollama`).

This is not a convenience abstraction — it answers two hard constraints:

1. **The Treasury network blocks most outbound ML endpoints.** A cloud-API
   prototype that can't run inside the network is a dead end. The Ollama
   backend runs inference entirely on localhost — no key, no account, no
   egress — so the production posture is self-hosted inference (or an
   allow-listed endpoint) with zero changes to the rules engine, endpoints,
   or UI.
2. **Per-application cost at ~150K applications/year.** A hosted API at even
   ~$0.01/document is ~$1.5K/year and requires a procurement relationship;
   self-hosted inference is a fixed hardware cost with zero marginal cost
   per document. The interface makes that a deployment decision, not a
   rewrite.

The third backend, `mock`, returns fixture-derived extractions with no
network at all — it is how the entire downstream stack (endpoints, PDF
handling, batch mode, rate limiting, UI) was built and is tested end-to-end
with zero API calls.

## NEEDS REVIEW is the product working, not failing

The verdict tiers encode a triage model. Standalone CFR violations (bad or
missing health warning, proof arithmetic that doesn't reconcile, missing
mandatory information) FAIL. Cross-check discrepancies and anything the
system is unsure of go to NEEDS REVIEW — a human agent makes the call. This
is a deliberate design principle: a form-to-label mismatch is not by itself
a violation. It can be a legitimate filing nuance — a revised label, a
formatting or transcription difference, a field the form records differently
from the artwork — so the tool routes it to a person rather than
auto-failing an application over it. FAIL is reserved for the label itself
breaking a CFR rule, which the tool can judge deterministically. The win is
an agent reviewing a small percentage of applications instead of all of
them.

This framing also absorbs model quality differences cleanly: a smaller local
model that is less certain than a frontier model produces a **higher triage
rate**, not wrong answers — uncertainty routes to a human rather than into a
verdict. The batch UI surfaces that rate directly ("N of M cleared
automatically") so labor saved is a measured claim, not a promise.

## Error handling: degrade toward a human, never toward a false PASS

Every failure path is a deliberate choice about where degradation lands:

- **Unsupported file type** → a plain-language message ("Upload a PDF or an
  image (PNG/JPEG/WebP)"), never a stack trace. Empty files are rejected
  the same way.
- **Unreadable PDF** (corrupt, or rendering unavailable) → a graceful
  message with guidance: "If this is a photo, upload it as an image
  instead."
- **An unreadable image gets its own outcome, not a false verdict.** When
  extraction returns too little legible label content to judge (fewer than
  two distinct kinds of label text readable), the result is a dedicated
  outcome — "Not enough readable label content to verify — check that a
  clear, complete label is attached." — matching how agents actually work:
  the application isn't rejected, a usable image is requested. (The
  wording covers both causes honestly: a blurry photo and a filing with no
  label attached at all.) No audit record is written,
  because no compliance verdict was rendered. A readable label with real
  problems still FAILs, and ambiguous-but-readable text still routes to
  NEEDS REVIEW; this path exists only below the readability floor.
- **Malformed or unparseable input degrades stepwise, never fatally:**
  unparseable net-contents statements fall back to loose string comparison;
  JSON truncated mid-generation by the local model is repaired at the last
  complete field; a failed region split (fraction cut looks wrong, anchor
  not found, tesseract absent, OCR error) falls back to whole-page
  extraction, as does a failed region call — the enhancement can never
  leave the app worse than its baseline.
- **Missing form fields are NOT_APPLICABLE, never failures** — real form
  revisions differ, and the app does not punish a document for its
  revision.
- **In a batch, one bad file cannot sink the rest**: its error is reported
  inline on its own row while every other file completes.
- **Rate-limit rejections** state plainly what happened and what to do
  ("Wait a minute and retry" / "Try again tomorrow").

## Accountability & sign-off design

The assessment did not ask for this; it was added because compliance
decisions require attribution, and a tool that processes them without a
record of who decided what is incomplete.

**Lightweight identity, not real auth.** The agent enters a name before
processing. No passwords or accounts — this is a deliberately minimal
stand-in that stamps the audit trail; production would use Treasury SSO.
Consistent with this "stamps, not authentication" stance, the audit view
(`GET /api/audit`) and the attestation endpoint (`POST /api/audit/{id}/review`)
are themselves unauthenticated in this prototype — a production deployment
would gate both behind Treasury SSO. The in-memory store holds only names,
filenames, and verdicts: no PII and no application content.

**Two-name attestation.** Sign-off requires re-entering a name — a
conscious "I reviewed this" act, not a passive click. The button reads
"Confirm review complete," never "Approve": it records the agent's review
decision and does not issue a COLA approval or touch the real TTB system.
The start-name and sign-off-name are always both recorded, and a mismatch
is flagged as information, not an error — a genuine two-person review is
legitimate (separation of duties), while a typo in one's own name gets
caught.

**Two deliberate boundaries.** Error items ("could not be checked") get no
audit record, because no verdict was rendered — there is no decision to
attest to; an audit log records decisions. And single-form and batch
sign-off differ on purpose: processing a single form is a deliberate act
where the agent is already examining that document, so every verdict
offers sign-off; batch is triage at volume, where PASS items auto-clear
untouched, FAIL items are group-acknowledged as going back to the
applicant, and only NEEDS REVIEW items require individual sign-off.
Forcing attestation on auto-cleared items would destroy the labor savings
that are the entire point.

## Local inference: measured findings (documented, not hidden)

Validated against the real COLA fixtures with `qwen2.5vl:7b` under
Ollama 0.32 on an RTX 3080 (10GB), pages upscaled 2× before inference:

- **Latency:** 5.8–9.7s per document warm; ~26s one-time model load. This
  misses the 5-second target on consumer hardware — the target assumes
  production GPU serving (e.g. vLLM on a datacenter card) or the hosted
  API backend; both are the same one-call architecture.
- **Printed form fields read reliably.** Brand name, product type
  checkbox, alcohol content, and net contents were extracted correctly on
  all three filings, including the 6/2006 Carlo Giacosa revision with
  shifted item numbers.
- **Label artwork transcription is the weak spot.** The affixed label
  images in registry printouts are small and low-resolution, and the 7B
  model makes transcription errors there that a frontier model does not:
  the government warning came back with dropped headings or one-word
  misreads ("BIRTH EFFECTS" for "birth defects"), line-break/hyphenation
  detail was not preserved verbatim, and Bärenjäger's five images were
  merged into four with text bleeding across per-image entries. This
  form-vs-artwork quality split is a documented property of the local
  backend, not a hidden weakness. (The hosted backends were later measured
  on the same fixtures — see "Model tier trade-offs" below.)
- **Consequence for verdict design:** the rules engine treats a warning
  transcription that is ≥90% similar to the statutory text but not exact
  as NEEDS REVIEW rather than FAIL — plausible transcription error routes
  to a human instead of becoming a wrong answer. Title case, dropped
  numbered clauses, and garbled/altered (low-similarity) text still FAIL;
  an otherwise-verbatim statement missing only the "GOVERNMENT WARNING:"
  heading stays above the similarity floor and routes to NEEDS REVIEW for
  human verification, consistent with the near-miss philosophy. Net effect:
  the weaker the model, the higher the triage rate — never silently wrong
  PASSes from the warning check. The batch UI
  reports the auto-clear rate so the labor-saving claim is measured.

## Splitting the page: from anchor OCR to a fast fraction cut with fallback

The diagnosis came first. When real approved COLAs failed their warning
checks under the whole-page path, the cause was a resolution-budget
mechanism: the whole tall page was squeezed into a fixed image-token budget,
downsampling the fine warning print below legibility. The same pixels,
cropped, were trivially readable. The fix is to split each COLA into a form
region and a label region so each is extracted at full effective
resolution — the two regions run as concurrent calls, so wall-clock stays
near the slower one rather than the sum.

**The split point evolved through three measured stages:**

1. **Anchor OCR (first version).** Every Form 5100.31 prints "AFFIX COMPLETE
   SET OF LABELS BELOW" between the form and the affixed artwork. The first
   implementation located that line — PDFs via pypdf text coordinates, images
   via tesseract OCR of the whole page — and split there. It fixed the
   warning-reading failures, but on the deployed Starter instance (0.5 vCPU)
   the full-page tesseract OCR was the dominant cost: ~750ms locally,
   ballooning to ~10–15s in production and pushing per-document time to
   ~22–33s.

2. **Cheap band OCR.** Rather than OCR the whole page, OCR only the vertical
   band where the anchor sits, at full resolution — the split crop stays
   byte-identical to full-page detection (verified by SHA-256), but the OCR
   is ~25–40% cheaper. An improvement, not a cure: the OCR still dominates on
   the constrained instance.

3. **Fixed-fraction cut with a warning-aware fallback (deployed).** Measured
   across five real COLAs, the boilerplate that ends the form region
   terminates at the same *relative* vertical position — the anchor sits at
   0.49–0.61 of page height across the fixtures. So the fast default now
   cuts at a fixed **fraction** of page height (`SPLIT_FRACTION`, default
   0.5), computed as a proportion of each page's pixel height — DPI- and
   resolution-independent, no OCR at all (~30ms vs ~750ms, ~20× cheaper).
   Both regions are cropped from the full-resolution page, so extraction
   reads are unchanged. A cut at 0.5 lands at or above every observed anchor,
   preserving the labels intact.

   The fraction cut is a geometric assumption, so it is **guarded, not
   trusted**: after the cut, a sanity check verifies the form region carries
   form fields and the label region carries the government warning and enough
   signal. If the cut looks wrong (e.g. a form with more content pushing the
   labels below 0.5), that document falls back to the anchor-OCR split; if
   the anchor also fails, to a single whole-page call. The fast path handles
   the common case in ~30ms; the OCR only runs on the exception. This is the
   split that ships.

**Deployed latency result.** On the public Starter instance, replacing
full-page anchor OCR with the fixed-fraction default dropped per-document
processing from **~22–33s to ~7s** — roughly 3–4× — while preserving the
government-warning read (the flagship compliance check). ~7s still misses
the literal <5s target on the constrained 0.5-vCPU demo instance; <5s
assumes production GPU serving or a larger instance. The bottleneck removed
was the OCR, not the model call.

**Honest trade-off from the split itself.** Removing the form region ended
form-to-label field bleed, which had been masking genuinely hard label
print — some earlier "passes" were passing on bled data. Eaglemount's tiny
front-label ABV line is now missed rather than back-filled from the form,
and the bleed also ran form-ward: the whole-page path returned "BÄRENJÄGER"
for a form that literally types "BARENJAGER" (umlauts imported from the
label artwork), so the split's plain-ASCII read is the *more* faithful one —
that real diacritic-only form/label difference is now absorbed by the brand
fuzzy matcher (case/punctuation/diacritics fold), which never applies to the
warning check. Residual cross-image duplication remains on one fixture
(Eaglemount's warning is stamped onto both of its label entries).

**Two Ollama-specific engineering notes** encoded in
`app/extractors/ollama_extractor.py`: pydantic's `anyOf`-style JSON
schemas silently produce empty output from Ollama's grammar engine (the
schema is rewritten to inline nullable type unions), and `think: false`
on thinking models (qwen3-vl) silently returns empty content under
Ollama 0.32, which is why the non-thinking `qwen2.5vl:7b` is the
recommended local model.

## Model tier trade-offs

The same three fixtures were measured end-to-end across four extraction
tiers — the local 7B model and three hosted models — to choose the deployed
model on data rather than assumption. The flagship compliance check is the
government health warning, so its read quality is the primary axis, with
latency as the tie-breaker.

| Tier | Warm latency / doc | Warning reads (all 3 fixtures) | Bärenjäger ABV (truth = 35) | Bärenjäger images (truth = 5) |
|---|---|---|---|---|
| Ollama qwen2.5vl:7b (local) | ~6–9s (RTX 3080) | 2 spurious FAILs + 1 near-miss — garbled | 35 (bled from form) | 4 (merged, bleed) |
| **claude-haiku-4-5** | **~6–8s** | **3/3 clean PASS — zero near-misses** | not read (→ ABV-present FAIL) | 5 |
| claude-sonnet-5 | ~8–15s | 1 spurious near-miss (Bärenjäger) | 35 | 5 |
| claude-opus-4-8 | ~9–12s | 1 near-miss (Lenz Moser) | 35 | 5 |

Notes on the numbers, stated honestly:

- **Latency:** the figures are warm single-document wall-clock for the
  extraction call. First-run measurements of the five-image Bärenjäger
  document showed 80–120s on *every* hosted tier (near-identical across
  Haiku/Sonnet/Opus) — an Anthropic API retry/overload transient, not model
  compute; a re-measure put Haiku's Bärenjäger at **8.1s**. The local model
  is GPU-bound on an RTX 3080; hosted latency is network + model. These are
  extraction-call figures; end-to-end per-document time on the deployed
  Starter instance is ~7s once the fixed-fraction split removed the OCR cost
  (see split section above).
- **Warning reads are what decided it.** Haiku returned all three warnings
  verbatim (clean PASS, zero spurious near-misses) — cleaner than Sonnet-5
  and Opus, which each dropped a single period ("...BIRTH DEFECTS  (2)...")
  and so routed one fixture to NEEDS REVIEW. The local 7B model is worst
  here, garbling two warnings into spurious FAILs.
- **Where the hosted models still err** (conservatively — always toward a
  human, never a false PASS): Haiku did not read Bärenjäger's tiny label
  ABV at all (→ ABV-present FAIL); Haiku and Sonnet both garbled the Lenz
  Moser brand name into a NEEDS REVIEW. These are real accuracy gaps, but
  they surface as FAIL/NEEDS REVIEW routed to an agent, not as wrong
  approvals.
- **No 35-vs-39 discrepancy exists** (corrected premise): the Bärenjäger
  form and labels both read 35% ALC/VOL. Every model that read the ABV read
  35; the earlier "39" was a human misreading of a very-low-resolution
  printed digit, since corrected in the fixtures, tests, and this document.

**Deployed model: `claude-haiku-4-5-20251001`.** It is the fastest tier
(~6–8s warm) *and* has the cleanest reads of the compliance-critical
government warning (3/3 verbatim, zero spurious near-misses — better than
both larger models), so it best avoids reproducing the slow prior-vendor
experience without degrading the flagship check. `EXTRACTION_MODEL` in
`render.yaml` selects it (pinned to the dated snapshot); a reviewer wanting
maximum transcription accuracy on tiny label print can override to Sonnet-5
or Opus at a latency cost.

## Creative problem-solving

**The model reads; the code judges.** Extraction and verification are
strictly separated, and enforced structurally: the extraction response
validates against a schema with no field for a verdict, so the model
cannot render one. Exactness is code's job; reading is the model's.

**Diagnosis before fixes.** When real approved COLAs failed their warning
checks, the failures were diagnosed rather than patched over. Three
distinct local-model failure modes were identified — wrong text block
grabbed (Eaglemount), paraphrased confabulation (Carlo Giacosa's invented
"SURVEY GENERAL HEALTH AGENCY"), and dropped heading/clause numbers
(Bärenjäger) — and traced to a resolution-budget mechanism: the whole tall
page was squeezed into a fixed image-token budget, downsampling the fine
warning print below legibility. The same pixels, cropped, were trivially
readable.

**Splitting the page, then making the split cheap.** The fix was to split
each COLA into a form region and a label region so each gets the full token
budget at higher effective resolution. That fixed the warning-reading
failures (Eaglemount's warning went from absent to verbatim; Carlo's
confabulation vanished; Bärenjäger's five images separated correctly for the
first time) and eliminated cross-region field-bleed — which, in turn,
revealed that some earlier "passes" had been passing on bled data. The split
mechanism was then optimized under measurement: OCR-based anchor detection
was the correct first cut but too slow on the constrained deployment
instance, so it was replaced by a fixed-fraction cut (a proportion of page
height, DPI-independent, no OCR) as the fast default, with the anchor OCR
kept as a warning-aware fallback for the case the fraction cut mishandles.
The result cut deployed per-document time ~3–4× (~22–33s → ~7s) without
touching a single read (see split section). Measuring before deciding — the
fraction cut was validated on all fixtures, and shipped only after the
warning read held — is the through-line.

**Triage as the philosophy, not error handling.** NEEDS REVIEW is the
product working, not failing. Against ~150,000 applications a year and 47
agents, the value is letting an agent review a fraction with confidence
rather than every one by eye. Model uncertainty surfaces as a
routed-for-review item, not a wrong answer, and the batch summary states
the auto-clear rate as a measurable claim about labor saved.

**Cost and firewall as design inputs.** Because a production system at
Treasury's volume makes per-call cost material, and because the internal
network blocks outbound ML endpoints, inference sits behind a swappable
interface with a local self-hosted implementation carrying zero marginal
cost. The public demo additionally applies rate limiting and a spend cap.

**Severity split by what the tool can actually adjudicate.** A form-to-label
discrepancy on a cross-checked field returns NEEDS REVIEW; a genuine CFR
violation of the label returns FAIL. The line reflects a principle about
authority: whether a form/label mismatch is disqualifying is a judgment
that belongs to a TTB specialist — such a mismatch can be a legitimate
filing nuance rather than a violation — so the tool surfaces it for a human
instead of rejecting the application itself. A CFR rule the label breaks on
its face (a non-compliant warning, proof arithmetic that doesn't reconcile,
a missing mandatory element) is something the tool can judge
deterministically, so that FAILs.

## Performance constraint

Hard requirement: **under 5 seconds** for a single label (warm). A prior vendor
pilot failed at 30–40 seconds and that is the stated reason it died. Hence: one
extraction round trip per document — two *concurrent* region calls when the
page splits into a form region and a label region (wall-clock ≈ the slower of
the two), a single whole-page call otherwise; never sequential chaining. The
split point is a fast fixed-fraction cut by default (no OCR), so the split
itself adds ~30ms rather than the ~750ms of full-page anchor OCR — the change
that brought deployed per-document time to ~7s on the Starter instance. Batch
mode fans out concurrently with `asyncio.gather` under a semaphore.

## Tools used

- Claude Code (agentic development)
- Python / FastAPI, plain static HTML frontend (no build step)
- Pluggable vision extraction: Ollama + qwen2.5vl:7b (local, default) or
  the Anthropic API (claude-haiku-4-5-20251001), both schema-constrained
- pdf2image / poppler for PDF rendering; pypdf for page classification and
  PDF anchor coordinates; tesseract OCR for the anchor-fallback split on
  image uploads
- Render (Starter plan, always-on) for deployment

## Assumptions

- Inputs are a COLA Form 5100.31 PDF (with label artwork pasted in) or a
  standalone label photo/image.
- The static instruction pages of a 5100.31 PDF (pages 2–5 on the 04/2023
  revision) are skipped by matching their boilerplate text, not by page
  number; pages with no text layer are kept rather than guessed at.
- The fixed-fraction split assumes a standard 5100.31 layout at standard
  aspect ratio; a non-standard page that mis-splits is caught by the
  sanity check and routed to the anchor-OCR or whole-page fallback.
- No persistence beyond the in-memory audit log of decision records
  (which itself resets on restart); label images and application content
  are never stored.

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
- **The fixed-fraction split is tuned to observed 5100.31 layouts.** Across
  the fixtures the form/label boundary sits at 0.49–0.61 of page height, and
  the 0.5 default cuts safely above the lowest anchor. A form revision whose
  boundary sits below 0.5 would mis-split on the fast path — which is exactly
  why the mis-split sanity check and the anchor-OCR fallback exist. The fast
  path is an optimization guarded by the slower-but-robust one, never a
  replacement for it.
- **Residual cross-image duplication on one fixture.** Eaglemount's warning
  is currently stamped onto both of its label entries — read correctly, but
  duplicated. It is included in the batch fixtures as an honest edge case.
- Verdicts are advisory: NEEDS REVIEW exists precisely because a human agent
  makes the final call.

## Safety validation: the failure mode is conservative

The central safety question for a compliance tool is not "is it always
right" — no reader of low-resolution label print is — but "when it is wrong,
which way does it fail." A tool that occasionally over-flags a compliant
label wastes an agent's minute; a tool that occasionally clears a
non-compliant one defeats its purpose. This tool is designed, and was
validated, to fail only in the first direction.

**Validated empirically.** The three real fixtures were each run five times
against the deployed model (`claude-haiku-4-5-20251001`) — fifteen runs on
identical input — to observe run-to-run variation directly. In all fifteen,
the government warning was read (never lost). Every PASS that occurred landed
on a genuinely compliant warning — a correct PASS, not a false one. The
run-to-run variation moved only between a correct PASS and a conservative
over-flag (NEEDS REVIEW or FAIL); it never moved toward a false clear. When
the model erred on the tiny print, it erred by *degrading* compliant text
into a near-miss or mismatch — routing to a human — not by manufacturing a
clean warning.

**Guaranteed structurally.** The empirical result follows from the
architecture rather than luck. The warning check is deterministic: code
compares the extracted text against the stored canonical 27 CFR 16.21 string
and returns PASS only on an exact match (statutory mixed case or all-caps);
near-miss → NEEDS REVIEW; title case, dropped clauses, or low similarity →
FAIL. The judging layer cannot pass a non-compliant warning it is given,
because it is code applying a fixed rule, not a model exercising discretion.
The independent review (below) reached the same conclusion by reading the
logic: no false PASS on a violating label is reachable.

**The one residual, stated honestly.** The deterministic check protects the
*judging* step, not the *reading* step. The only theoretical path to an
unsafe false-clear is upstream: the vision model hallucinating the exact
compliant statutory text where a label actually printed a non-compliant
warning — silently "correcting" a title-case or truncated warning into the
canonical string before the code ever sees it. This was **not observed** in
any run (every error ran the opposite direction, toward over-flagging), and
it is mitigated by design (the extraction prompt instructs verbatim
transcription, never correction or completion). It cannot be called
impossible — only unobserved here and structurally discouraged. These
fixtures cannot exercise it, because all three warnings are genuinely
compliant; a deliberately non-compliant fixture would be the natural next
test. Naming this limit is the point: it is exactly where the tool's
controls end, and where a human still owns the risk.

## Independent review

After the build was complete, the codebase was audited by a separate model
(Claude Opus 4.8) in a fresh session with no knowledge of the build
history — a cold read, to surface what the builder had become blind to. The
audit was scoped to three things only: correctness bugs that could produce a
wrong verdict, security issues relevant to public deployment, and
inconsistencies between the documentation and the code.

The review found no critical issues and confirmed the core compliance engine
is sound — it could not produce a false PASS on a violating label; the strict
government-warning comparison correctly FAILs title-case and dropped-clause
violations and does not pass garbled text; the fuzzy brand and net-contents
matching does not pass genuinely different values; and the region split
degrades safely to whole-page extraction on any failure. Secrets posture,
input handling, and the frontend (no XSS surface) were confirmed clean.

The actionable findings were deployment-hardening items and
documentation-accuracy corrections, all since addressed: the rate limiter was
hardened against spoofed `X-Forwarded-For` headers and unbounded key growth;
upload body size and PDF page count were capped to prevent memory exhaustion
on the public instance; and three documentation sentences that overstated the
missing-heading warning behavior as a hard FAIL were corrected to describe the
actual behavior (a missing heading on otherwise-verbatim text routes to NEEDS
REVIEW). The unauthenticated audit view is documented as an intentional
prototype simplification that production would gate behind Treasury SSO.
