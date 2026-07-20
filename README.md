# TTB Label Verifier

Prototype compliance checker for alcohol beverage labels. A TTB compliance agent
uploads a COLA application (TTB Form 5100.31) as a PDF — or a photo of a label
taken on a phone — and gets back one of three verdicts: **PASS**, **NEEDS REVIEW**,
or **FAIL**, with per-field detail.

Built as a take-home assessment prototype for a U.S. Treasury IT Specialist (AI)
position. See [APPROACH.md](APPROACH.md) for design decisions, assumptions, and
limitations.

## What it checks

**Cross-checks** (form vs. label artwork within the same PDF):
- Item 6 brand name vs. the brand name on the pasted label (fuzzy — case and
  punctuation differences pass with a note)
- Item 5 product type checkbox (Wine / Distilled Spirits / Malt Beverages) vs.
  the label, which also selects the governing CFR part (Part 4 / 5 / 7)

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
cp .env.example .env   # then put your Anthropic API key in .env
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 — health check at http://127.0.0.1:8000/health.

## Deployment (Render)

Deployed from this repo via `render.yaml` (Docker). Set `ANTHROPIC_API_KEY` in
the Render dashboard — the key lives server-side only and is never exposed to
the browser.

> **Note on cold starts:** Render free-tier instances sleep after inactivity and
> take ~30 seconds to wake. The under-5-second requirement applies to warm
> request processing, not cold start.
