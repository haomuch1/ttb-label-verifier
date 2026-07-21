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
drove a single round trip per document. (The two-region split later made
this two concurrent calls — wall-clock stays near the slower of the two,
preserving the intent.)

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
   check accepts two casings of the complete verbatim statement — the
   statutory mixed case, or the whole statement uppercased — while a
   title-case rendering (Jenny Park's rejected case) FAILs. Deviations that
   are not pure casing follow the near-miss tiering described below.
5. **A free real-world regression case:** Bärenjäger's form states Alcohol
   Content `35` while both its labels state `39% ALC / VOL` — a genuine
   4-point form-to-label mismatch on an approved COLA. Expected output is a
   flagged discrepancy (NEEDS REVIEW), not FAIL: cross-check mismatches go to
   a human; only standalone CFR violations (bad warning, inconsistent proof
   arithmetic, missing mandatory information) hard-fail.

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
system is unsure of go to NEEDS REVIEW — a human agent makes the call, which
is exactly what happened historically with Bärenjäger's approved 35-vs-39
discrepancy. The win is an agent reviewing a small percentage of
applications instead of all of them.

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
  complete field; a failed region split (anchor not found, tesseract
  absent, OCR error) falls back to whole-page extraction, as does a failed
  region call — the enhancement can never leave the app worse than its
  baseline.
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

Validated against the three real COLA fixtures with `qwen2.5vl:7b` under
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
  detail was not preserved verbatim, Bärenjäger's five images were merged
  into four with text bleeding across per-image entries, and Bärenjäger's
  label ABV was misread as matching the form — so the known 35-vs-39
  discrepancy was **missed** by the local model. This form-vs-artwork
  quality split is a documented property of the local backend, not a
  hidden weakness. (The frontier backend was later measured on the same
  fixtures — see "Frontier backend (Opus) measured results" below.)
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
- **Two-region extraction (the fix that followed the diagnosis).** Every
  Form 5100.31 prints "AFFIX COMPLETE SET OF LABELS BELOW" between the
  form and the affixed artwork. The page is split at that anchor (PDFs:
  text-layer coordinates via pypdf; images: OCR via tesseract) and the
  two regions are extracted concurrently, each getting the full
  image-token budget at higher effective resolution; results merge into
  the same Extraction schema. If the anchor isn't found or either call
  fails, the app falls back to the single whole-page call — the split is
  an enhancement over the baseline, never a replacement that can break
  it. Measured effect on the three fixtures whose warnings previously
  failed as unreadable: Eaglemount's warning went from absent to
  **verbatim (PASS)**; Carlo Giacosa's and Bärenjäger's went from
  garbled hard-FAILs to 96%-similar NEEDS_REVIEW near-misses;
  Bärenjäger's five label images were separated correctly for the first
  time, with the warning attributed to one label instead of bleeding
  across three. Wall-clock ran 6.7–9.2s per document — roughly the
  slower region, not the sum (concurrent calls measured against
  sequential: 6.7s vs 12.3s summed on Carlo Giacosa). Honest trade-off
  also observed: removing the form region ended form-to-label bleed,
  which had been masking genuinely hard label print — some earlier
  "passes" were passing on bled data. Eaglemount's tiny front-label ABV
  line is now missed rather than back-filled from the form, and a
  follow-up diagnostic showed the bleed also ran form-ward: the
  whole-page path returned "BÄRENJÄGER" for a form that literally types
  "BARENJAGER" (umlauts imported from the label artwork), so the split's
  plain-ASCII read is the *more* faithful one — that real diacritic-only
  form/label difference is now absorbed by the brand fuzzy matcher
  (case/punctuation/diacritics fold), which never applies to the warning
  check. Residual cross-image duplication remains on one fixture
  (Eaglemount's warning is stamped onto both of its label entries).
- **Two Ollama-specific engineering notes** encoded in
  `app/extractors/ollama_extractor.py`: pydantic's `anyOf`-style JSON
  schemas silently produce empty output from Ollama's grammar engine (the
  schema is rewritten to inline nullable type unions), and `think: false`
  on thinking models (qwen3-vl) silently returns empty content under
  Ollama 0.32, which is why the non-thinking `qwen2.5vl:7b` is the
  recommended local model.

## Frontier backend (Opus) measured results

The cloud path was later measured end-to-end on the same three fixtures
with `claude-opus-4-8` (`EXTRACTION_MODEL=claude-opus-4-8`), for a
local-vs-frontier comparison. Honest results, including where the frontier
model did **not** improve on the local one:

- **Label transcription is markedly better.** Opus returned each
  government warning essentially verbatim (Bärenjäger's PASSes cleanly),
  preserved the Lenz Moser hyphenated line break (`BEV-`/`ERAGES`) — which
  normalize-and-rejoin then correctly recombined — and separated
  Bärenjäger's **five** affixed images correctly as one combined set (the
  7B local model collapsed them to four with cross-image bleed). No
  field-bleed was observed.
- **Latency badly misses the 5-second target on Opus.** Measured warm
  wall-clock per document: Carlo Giacosa 11.9s, Lenz Moser 9.0s,
  Bärenjäger 82.9s (its label region carries five images). Opus vision is
  slow; this backend trades latency for transcription accuracy. Meeting the
  <5s target would require the faster hosted model (Haiku, the default
  constant) or production GPU serving — the one-call/concurrent-region
  architecture is unchanged either way.
- **The Bärenjäger 35-vs-39 ABV discrepancy was NOT caught by Opus
  either.** Opus read the label alcohol content as `35% ALC / VOL`
  (matching the form's `35`), so the cross-check passed as consistent and
  the document returned PASS — no discrepancy flagged. This is the same
  miss the local model made, reached differently (the local model bled the
  form value; Opus transcribed `35` directly off the label). Note that this
  puts the fixture's own ground truth in question: the "39%" expected value
  comes from a human reading of a very-low-resolution printed digit, and
  **two independent vision models (local qwen2.5vl and Opus) both read
  `35`**; on direct high-zoom inspection the digit is at the edge of
  legibility. The honest status is that the intended discrepancy is not
  detected by either backend, and the source-COLA digit should be
  re-verified by a human before treating "39%" as settled.
- **Lenz Moser routed to NEEDS REVIEW, not PASS** — Opus dropped the period
  after "BIRTH DEFECTS", leaving the warning ~100% similar but not exact, so
  the near-miss tier correctly sent it to a human rather than passing it.
  The rejoin mechanism worked; the routing reflects a genuine one-character
  omission by the model, which is exactly what NEEDS REVIEW is for.

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

**Two-region extraction as the fix.** Rather than a slow second pass, each
COLA is split at a fixed structural anchor — the boilerplate "AFFIX
COMPLETE SET OF LABELS BELOW" line — into a form region and a label
region, each sent as its own concurrent extraction. Because each region is
a smaller image, each gets the full token budget at higher effective
resolution. This fixed the warning-reading failures (Eaglemount's warning
went from absent to verbatim; Carlo's confabulation vanished; Bärenjäger's
five images separated correctly for the first time) and eliminated
cross-region field-bleed — which, in turn, revealed that some earlier
"passes" had been passing on bled data (the whole-page path was importing
label umlauts into form fields). Removing the bleed made the output more
honest and surfaced the local model's true fine-print ceiling — precisely
the case the cloud tier exists to handle.

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

**Severity grounded in agency behavior.** A form-to-label discrepancy on a
cross-checked field returns NEEDS REVIEW; a genuine CFR violation of the
label returns FAIL. The line is drawn from observed behavior: Bärenjäger
was approved by TTB despite an alcohol-content discrepancy, so the tool
does not treat such a discrepancy as more disqualifying than TTB itself
did.

## Performance constraint

Hard requirement: **under 5 seconds** for a single label (warm). A prior vendor
pilot failed at 30–40 seconds and that is the stated reason it died. Hence: one
extraction round trip per document — two *concurrent* region calls when the
page splits at the form/label anchor (wall-clock ≈ the slower of the two),
a single whole-page call otherwise; never sequential chaining. Batch mode
fans out concurrently with `asyncio.gather` under a semaphore.

## Tools used

- Claude Code (agentic development)
- Python / FastAPI, plain static HTML frontend (no build step)
- Pluggable vision extraction: Ollama + qwen2.5vl:7b (local, default) or
  the Anthropic API (claude-haiku-4-5), both schema-constrained
- pdf2image / poppler for PDF rendering; pypdf for page classification and
  PDF anchor coordinates; tesseract OCR for the image anchor split
- Render free tier for deployment

## Assumptions

- Inputs are a COLA Form 5100.31 PDF (with label artwork pasted in) or a
  standalone label photo/image.
- The static instruction pages of a 5100.31 PDF (pages 2–5 on the 04/2023
  revision) are skipped by matching their boilerplate text, not by page
  number; pages with no text layer are kept rather than guessed at.
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
- Verdicts are advisory: NEEDS REVIEW exists precisely because a human agent
  makes the final call.

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
matching does not pass genuinely different values; and the two-region split
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
