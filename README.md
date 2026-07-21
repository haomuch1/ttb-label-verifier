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

**Live demo:** <https://ttb-label-verifier-nnqf.onrender.com> — always-on
(Render Starter plan, no spin-down), so requests are served warm. Per-document
processing runs ~7 seconds on the demo instance. See
[Deployment](#deployment-render).

## Two ways to use it — your choice, both work

- **Just open the live URL** above. Nothing to install, no key, no setup — it
  already runs the hosted Anthropic backend. This is the easiest way to try
  it and is all a reviewer needs.
- **Run it locally with Ollama**, if you'd rather keep everything on your own
  machine and it's capable enough (one consumer GPU). This is the fully
  local, no-key, no-cost path — see [Setup and run](#setup-and-run) below.

Both give the same tool and the same checks. The live URL is the fast path;
local is there if you want to see the self-hosted, nothing-leaves-your-machine
posture the production design is built around.

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
document: the page is split into a form region and a label region so each is
read at full resolution — a fast fixed-fraction cut by default (a proportion
of page height, no OCR), falling back to OCR-based anchor detection only when
that cut looks wrong, and to a single whole-page call if both fail.

## Setup and run

You only need this if you want to run the tool **locally** — to try it at all,
just open the [live URL](#two-ways-to-use-it--your-choice-both-work). Running
locally uses the Ollama backend so everything stays on your machine (no key,
no account, no cost).

Requires Python 3.11+. Clone, then:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

### Run locally with Ollama (no key, no cost)

```bash
# 1. Install Ollama: https://ollama.com/download  (Windows/macOS/Linux)
# 2. Pull the vision model (~6 GB download):
ollama pull qwen2.5vl:7b
# 3. Run:
EXTRACTOR=ollama uvicorn app.main:app --reload
#    (PowerShell:  $env:EXTRACTOR="ollama"; uvicorn app.main:app --reload)
```

Then open **http://127.0.0.1:8000** (your local instance; health check at
`/health`).

Recommended model: **`qwen2.5vl:7b`** — the Qwen VL family is the strongest
open-weight line for document OCR at a size that runs on one consumer GPU,
and the 2.5 generation is a *non-thinking* model, which matters here: we
first tried `qwen3-vl:8b`, but its thinking mode ruminates for thousands of
tokens on this task and cannot be disabled under Ollama 0.32 (`think:
false` silently returns empty output — a live bug we hit). Measured on an
RTX 3080: **6–10 seconds per COLA warm**, ~26s one-time model load. See
APPROACH.md for measured accuracy and its limits on fine label print.

### Backends, for reference

Inference is chosen by the `EXTRACTOR` environment variable — you don't need
to set this to use the tool (the live URL already runs `anthropic`, local runs
`ollama`), but for completeness:

| `EXTRACTOR` | Needs | Character |
|---|---|---|
| `ollama` (default) | A local [Ollama](https://ollama.com) server | No API key, no account, no cost, nothing leaves your machine — the local path above |
| `anthropic` | `ANTHROPIC_API_KEY` in `.env` | The hosted backend the live demo runs; self-hostable with your own key |
| `mock` | Nothing | Canned fixture data — UI/dev/testing with zero inference |

### Optional system dependencies

- **PDF uploads** need [poppler](https://poppler.freedesktop.org/)
  (`pdftoppm`) for page rendering. Preinstalled in the Docker image; on
  Windows point `POPPLER_PATH` at poppler's `bin` folder.
- **Anchor-fallback on image uploads** uses
  [tesseract](https://github.com/tesseract-ocr/tesseract) to locate the
  form/label boundary when the fast fixed-fraction split looks wrong
  (`TESSERACT_CMD` on Windows if not on PATH). Without it the app still
  works — the fraction split is the default and a failed split falls back to
  whole-page extraction.

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

You can test with real COLAs two ways: pull your own fresh ones from TTB's
public registry, or use the five already included in this repo. Either works.

### Pull your own from the TTB Public COLA Registry

Every real approved COLA is public record. To capture one as a PNG the tool
can read:

1. Go to TTB COLAs Online public search:
   <https://ttbonline.gov/colasonline/publicPageBasicCola.do?action=page>
2. Enter a **completed-date range** and search — for example,
   `07/01/2025` to `07/20/2026`.
3. Click a **TTB ID** link in the results.
4. Click the **printable version** link.
5. **Screenshot the printable view** — capture the entire application, keeping
   even margins — and save it as a PNG. That screenshot is your test image.

(This is a manual screenshot of one public printable page, not an automated
or bulk download — capture the rendered view as an image.)

### Or use the five included fixtures

Five real approved applications, captured this way from the Public COLA
Registry, are included as PNG fixtures. Three are set up for single-file
testing in their own folders under `tests/fixtures/`:

- `tests/fixtures/barenjager/` — five label images with mandatory info
  scattered across them: the combined-set case, where the app must read
  all the images as one set rather than per-image.
- `tests/fixtures/carlo-giacosa/` — an older (6/2006) form revision with
  shifted field numbering.
- `tests/fixtures/lenz-moser/` — a health warning printed in all capitals
  and hyphenated across a line break.

**Batch test.** `tests/fixtures/Batch Test/` holds five COLAs — the three
above plus two more, so you can run a mixed batch and watch the triage
summary render:

- **Eaglemount** — included as an honest edge case. Its warning reads
  correctly, but the extraction still duplicates that warning across both
  of its label entries — the one residual known issue (see APPROACH.md,
  two-region findings).
- **3 Steves Winery** — an additional public-registry sample for extra
  batch coverage.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

145 tests, all offline (the mock backend): normalization edge cases
(wrapped/hyphenated warning text, case preservation, diacritics, net-content
quantities), the rules engine, hand-transcribed scenarios of the real COLAs
above, PDF page classification and the page cap, the split pipeline
(fixed-fraction default, mis-split detection, anchor fallback, whole-page
fallback), the API surface, rate limiting (including spoofed
X-Forwarded-For and the request-body cap), and the audit trail.

## Rate limits

Public deployments are protected by an in-memory per-IP limit
(`RATE_LIMIT_PER_IP_PER_MIN`, default 12/min) and a daily instance cap
(`RATE_LIMIT_DAILY_CAP`, default 300 verifications/day). Counters reset on
restart; nothing is persisted.

## Deployment (Render)

Deployed from this repo via `render.yaml` (Docker; poppler and tesseract
included in the image). The public demo runs `EXTRACTOR=anthropic` on the
pinned `claude-haiku-4-5-20251001` model (`EXTRACTION_MODEL` in
`render.yaml`) — set `ANTHROPIC_API_KEY` in the Render dashboard; it lives
server-side only. Per-document processing runs ~7 seconds on the demo's
Starter instance.

> **Always-on:** the demo runs on Render's Starter plan, so it does not
> spin down and there is no first-request cold start — requests are served
> warm.
