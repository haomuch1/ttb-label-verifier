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

Form 5100.31 has **no fields** for ABV, class/type, or net contents — only
brand name and product type can be cross-checked against the form. Everything
else is standalone. The app does not invent form fields.

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
