# TTB Label Verifier

**What this is.** Before an alcoholic beverage can be sold in the U.S., its
label must be approved by the Treasury's Alcohol and Tobacco Tax and Trade
Bureau (TTB) through a **COLA** — a Certificate of Label Approval, filed on
TTB Form 5100.31 with the label artwork attached. TTB compliance agents
review these applications by hand.

This tool does the first pass for them. An agent uploads a COLA (PDF or
image); the tool reads the form and the attached labels, checks them
against the federal labeling rules, and returns one of three answers:

- **PASS** — every check met; no action needed.
- **NEEDS REVIEW** — nothing failed, but something deserves a person's
  judgment (a form/label discrepancy, or text the reader wasn't certain of).
- **FAIL** — a concrete rule violation, with the reason in plain language.

**The point is triage**: instead of an agent reading every application, the
tool clears the clean ones automatically and routes only the uncertain ones
to a human — the batch screen reports exactly how many were cleared versus
flagged, so the labor saved is a measured number, not a promise.

Built as a take-home assessment prototype for a U.S. Treasury IT Specialist
(AI) position, by directing Claude Code. See [APPROACH.md](APPROACH.md) for
design decisions, measured results, and honestly-stated limitations.

**Live demo:** deployed on Render (free tier) — see [Deployment](#deployment-render)
for the cold-start caveat.

## What it checks

**Cross-checks** (form vs. label artwork within the same document — each
runs only if the field is present on the form; a missing form field never
fails):
- Brand name vs. the brand name on the label (fuzzy — case, punctuation,
  and diacritic differences pass with a note)
- Product type checkbox (Wine / Distilled Spirits / Malt Beverages) vs. the
  label, which also selects the governing regulation (27 CFR Part 4 / 5 / 7)
- Alcohol content and net contents, when the form revision carries those
  fields (quantities are compared, so "750 MILLILITERS" matches "750 mL" —
  but metric is never silently converted to fluid ounces)

**Standalone compliance** (label alone against the CFR):
- Government health warning — strict comparison against the statutory text
  of 27 CFR 16.21. Title case, dropped numbered clauses, and garbled/altered
  wording FAIL; a near-miss transcription (≥90% similar to the statute,
  e.g. otherwise-verbatim text with only the "GOVERNMENT WARNING:" heading
  missing) routes to NEEDS REVIEW for human verification.
- Alcohol content present; proof internally consistent (proof = 2 × ABV)
- Net contents present
- Class/type designation present
- Bottler name and address present

## Architecture in one line

**The model extracts, code judges.** A vision model returns structured JSON
of verbatim text and observations — the schema has no field for a verdict —
and deterministic Python applies every rule. One extraction round trip per
document (the page is split at the form/label boundary and the two regions
are read concurrently; if the split fails, the whole page goes as one call).

## Setup and run

Requires Python 3.11+. Clone, then:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Then pick an inference backend via the `EXTRACTOR` environment variable:

| `EXTRACTOR` | Needs | Character |
|---|---|---|
| `ollama` (default) | A local [Ollama](https://ollama.com) server | No API key, no account, no cost, nothing leaves your machine |
| `anthropic` | `ANTHROPIC_API_KEY` | Fastest and most accurate; used by the cloud demo |
| `mock` | Nothing | Canned fixture data — UI/dev/testing with zero inference |

### Option A — fully local with Ollama (no key, no cost)

```bash
# 1. Install Ollama: https://ollama.com/download  (Windows/macOS/Linux)
# 2. Pull the vision model (~6 GB download):
ollama pull qwen2.5vl:7b
# 3. Run:
EXTRACTOR=ollama uvicorn app.main:app --reload
#    (PowerShell:  $env:EXTRACTOR="ollama"; uvicorn app.main:app --reload)
```

Recommended model: **`qwen2.5vl:7b`** — the Qwen VL family is the strongest
open-weight line for document OCR at a size that runs on one consumer GPU,
and the 2.5 generation is a *non-thinking* model, which matters here: we
first tried `qwen3-vl:8b`, but its thinking mode ruminates for thousands of
tokens on this task and cannot be disabled under Ollama 0.32 (`think:
false` silently returns empty output — a live bug we hit). Measured on an
RTX 3080: **6–10 seconds per COLA warm**, ~26s one-time model load. See
APPROACH.md for measured accuracy and its limits on fine label print.

### Option B — Anthropic API

```bash
cp .env.example .env        # put your key in .env: ANTHROPIC_API_KEY=sk-ant-...
EXTRACTOR=anthropic uvicorn app.main:app --reload
```

The key is read server-side only and never reaches the browser.

Open **http://127.0.0.1:8000** (health check at `/health`).

### Optional system dependencies

- **PDF uploads** need [poppler](https://poppler.freedesktop.org/)
  (`pdftoppm`) for page rendering. Preinstalled in the Docker image; on
  Windows point `POPPLER_PATH` at poppler's `bin` folder.
- **Two-region extraction on image uploads** uses
  [tesseract](https://github.com/tesseract-ocr/tesseract) to find the
  form/label boundary (`TESSERACT_CMD` on Windows if not on PATH). Without
  it the app still works — it falls back to whole-page extraction.

## Using it

Enter your **name or ID** on any processing screen — it stamps the audit
trail so every decision is attributable (a deliberate stand-in for real
SSO; see APPROACH.md). Then pick one of the three modes:

- **Process a form** — check one COLA. Drag a PDF/image into the drop zone
  (or click to choose), press **Process**, and read the one-word verdict
  band with per-check detail below it.
- **Batch process** — check up to 20 files at once. Results stream in
  grouped by verdict: the review queue first, then failures, then the
  auto-cleared. The summary line states the triage rate ("N of M cleared
  automatically").
- **Audit** — the processing record: who processed what, the verdict, the
  timestamp, and who reviewed it. Decision records only; no label images
  or application content are stored, and the log resets on restart.

**Sign-off**: after looking at a result, the agent types their name and
presses **"Confirm review complete."** This records *"I reviewed this"* in
the audit trail — it does **not** issue a COLA approval or touch any real
TTB system. Both the processor's and reviewer's names are always recorded;
if they differ, the record is flagged (a second-person review is
legitimate — the flag is information, not an error). In a batch, only
NEEDS REVIEW items require individual sign-off; passed items flow through
untouched, and failed items are acknowledged as a group ("Mark as seen").

## Try it with real COLAs

Three approved applications from TTB's Public COLA Registry are included
as fixtures — upload them from `tests/fixtures/`:

- `tests/fixtures/barenjager/` — five label images, and a genuine
  form-to-label discrepancy on an approved COLA (form says 35, labels say
  39% ABV): the case NEEDS REVIEW exists for.
- `tests/fixtures/carlo-giacosa/` — an older (6/2006) form revision with
  shifted field numbering.
- `tests/fixtures/lenz-moser/` — a health warning printed in all capitals
  and hyphenated across a line break.

Batch all of them at once from `tests/fixtures/Batch Test/` to see the
triage summary render.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

137 tests, all offline (the mock backend): normalization edge cases
(wrapped/hyphenated warning text, case preservation, diacritics, net-content
quantities), the rules engine, hand-transcribed scenarios of the real COLAs
above, PDF page classification and the page cap, the region-split pipeline
with its fallbacks, the API surface, rate limiting (including spoofed
X-Forwarded-For and the request-body cap), and the audit trail.

## Rate limits

Public deployments are protected by an in-memory per-IP limit
(`RATE_LIMIT_PER_IP_PER_MIN`, default 12/min) and a daily instance cap
(`RATE_LIMIT_DAILY_CAP`, default 300 verifications/day). Counters reset on
restart; nothing is persisted.

## Deployment (Render)

Deployed from this repo via `render.yaml` (Docker; poppler and tesseract
included in the image). The public demo runs `EXTRACTOR=anthropic` — set
`ANTHROPIC_API_KEY` in the Render dashboard; it lives server-side only.

> **Note on cold starts:** Render free-tier instances sleep after
> inactivity and take ~30 seconds to wake. The under-5-second requirement
> applies to warm request processing, not cold start.
