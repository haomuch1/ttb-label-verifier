"""Run a live extraction backend on the real COLA fixtures and report.

Usage:  python scripts/validate_fixtures.py [--extractor NAME] [fixture-name ...]

Prints, per fixture: wall-clock latency of the single vision call, the raw
Extraction JSON, and the rules-engine verdict. Backend selected by
--extractor or the EXTRACTOR env var (anthropic needs ANTHROPIC_API_KEY;
ollama needs a local Ollama server; mock needs nothing).
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.extractors import get_extractor  # noqa: E402
from app.pipeline import run_extraction  # noqa: E402
from app.rules import verify  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def fixture_images(name: str) -> list[tuple[bytes, str]]:
    folder = FIXTURES_DIR / name
    pngs = sorted(folder.glob("*.png"))
    if not pngs:
        raise SystemExit(f"No PNGs found in {folder}")
    return [(p.read_bytes(), "image/png") for p in pngs]


async def run(extractor, name: str) -> tuple[int, int]:
    print(f"\n{'=' * 70}\n{name}  (extractor: {extractor.name})\n{'=' * 70}")
    images = fixture_images(name)
    start = time.perf_counter()
    result = await run_extraction(extractor, images)
    elapsed = time.perf_counter() - start
    print(f"--- extraction call: {elapsed:.2f}s | "
          f"tokens in={result.input_tokens} out={result.output_tokens} ---")
    print(result.extraction.model_dump_json(indent=2))
    report = verify(result.extraction)
    print(f"\n--- rules engine verdict: {report.verdict.value}"
          f"  (governing: {report.cfr_part}) ---")
    for c in report.checks:
        print(f"  [{c.verdict.value:>14}] {c.name}: {c.detail}")
    return result.input_tokens, result.output_tokens


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extractor", default=None)
    parser.add_argument("names", nargs="*",
                        default=["barenjager", "carlo-giacosa", "lenz-moser"])
    args = parser.parse_args()
    extractor = get_extractor(args.extractor)
    names = args.names or ["barenjager", "carlo-giacosa", "lenz-moser"]
    total_in = total_out = 0
    for name in names:
        tin, tout = await run(extractor, name)
        total_in += tin
        total_out += tout
    print(f"\n{'=' * 70}\nTOTAL tokens across {len(names)} documents: "
          f"input={total_in} output={total_out}\n{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
