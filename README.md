# TTB Label Verifier

Prototype compliance checker for alcohol beverage labels. A TTB compliance agent
uploads a COLA application (TTB Form 5100.31) as a PDF — or a photo of a label
taken on a phone — and gets back one of three verdicts: **PASS**, **NEEDS REVIEW**,
or **FAIL**, with per-field detail.

Built as a take-home assessment prototype for a U.S. Treasury IT Specialist (AI)
position. See [APPROACH.md](APPROACH.md) for design decisions, assumptions, and
limitations.

## What it checks

**Cross-checks** (form vs. label artwork within the same PDF — each runs only
if the field is present on the form; a missing form field never fails):
- Brand name vs. the brand name on the pasted label (fuzzy — case and
  punctuation differences pass with a note)
- Product type checkbox (Wine / Distilled Spirits / Malt Beverages) vs. the
  label, which also selects the governing CFR part (Part 4 / 5 / 7)
- Alcohol content and net contents, when the form revision carries those
  fields (real filings do; the blank 04/2023 form does not)

**Standalone compliance** (label alone against the CFR):
- Government health warning — strict verbatim match against 27 CFR 16.21
- ABV present and format-valid; proof internally consistent (proof = 2 × ABV)
- Net contents present
- Class/type designation present
- Bottler name and address present

## Architecture in one line

**The model extracts, code judges.** One Claude vision call returns structured
JSON (verbatim text and observations — no verdicts); deterministic Python
applies the rules.

## Running locally

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 — health check at http://127.0.0.1:8000/health.

### Choosing an inference backend

Extraction runs behind a pluggable interface. Pick with `EXTRACTOR`:

| `EXTRACTOR` | Needs | Use for |
|---|---|---|
| `ollama` (default) | A local [Ollama](https://ollama.com) server | No key, no account, no cost, no network egress |
| `anthropic` | `ANTHROPIC_API_KEY` (put it in `.env`) | Fastest/most accurate; used by the cloud demo |
| `mock` | Nothing | UI/dev/testing with zero API calls |

**Ollama setup (fully local, free):**

```bash
# 1. Install Ollama: https://ollama.com/download (Windows/macOS/Linux)
# 2. Pull a vision model:
ollama pull qwen3-vl:8b
# 3. Run the app against it:
EXTRACTOR=ollama OLLAMA_MODEL=qwen3-vl:8b uvicorn app.main:app --reload
```

Recommended model: **`qwen3-vl:8b`** — the Qwen VL family is the strongest
open-weight line for document OCR and dense text transcription at a size
that runs on a single consumer GPU (or CPU, slowly), which is exactly this
workload: reading small print on forms and labels. If it's too heavy for
your machine, `qwen2.5vl:7b` or `qwen3-vl:4b` are the fallbacks; expect
transcription quality to drop with size.

**PDF uploads** additionally require [poppler](https://poppler.freedesktop.org/)
(`pdftoppm`) on PATH for page rendering — preinstalled in the Docker image;
on Windows/macOS dev boxes install it separately or test with image uploads.

### Rate limits

Public deployments are protected by an in-memory per-IP limit
(`RATE_LIMIT_PER_IP_PER_MIN`, default 12/min) and a daily instance cap
(`RATE_LIMIT_DAILY_CAP`, default 300 verifications/day). Counters reset on
restart; nothing is persisted.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite covers the text-normalization edge cases (line-wrapped and
hyphenated warning text, case preservation) and scenario reconstructions of
three real approved COLAs from TTB's Public COLA Registry — including
Bärenjäger's genuine form-to-label ABV discrepancy. Image fixtures go in
`tests/fixtures/` (see the README there).

## Deployment (Render)

Deployed from this repo via `render.yaml` (Docker). Set `ANTHROPIC_API_KEY` in
the Render dashboard — the key lives server-side only and is never exposed to
the browser.

> **Note on cold starts:** Render free-tier instances sleep after inactivity and
> take ~30 seconds to wake. The under-5-second requirement applies to warm
> request processing, not cold start.
