"""Run the live extraction call on the real COLA fixtures and report.

Usage:  python scripts/validate_fixtures.py [fixture-name ...]

Prints, per fixture: wall-clock latency of the single vision call, the raw
Extraction JSON, and the rules-engine verdict. Requires ANTHROPIC_API_KEY
(env or .env).
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.extraction import MODEL, extract  # noqa: E402
from app.rules import verify  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def fixture_images(name: str) -> list[tuple[bytes, str]]:
    folder = FIXTURES_DIR / name
    pngs = sorted(folder.glob("*.png"))
    if not pngs:
        raise SystemExit(f"No PNGs found in {folder}")
    return [(p.read_bytes(), "image/png") for p in pngs]


async def run(name: str) -> None:
    print(f"\n{'=' * 70}\n{name}  (model: {MODEL})\n{'=' * 70}")
    images = fixture_images(name)
    start = time.perf_counter()
    extraction = await extract(images)
    elapsed = time.perf_counter() - start
    print(f"--- extraction call: {elapsed:.2f}s ---")
    print(extraction.model_dump_json(indent=2))
    report = verify(extraction)
    print(f"\n--- rules engine verdict: {report.verdict.value}"
          f"  (governing: {report.cfr_part}) ---")
    for c in report.checks:
        print(f"  [{c.verdict.value:>14}] {c.name}: {c.detail}")


async def main() -> None:
    names = sys.argv[1:] or ["barenjager", "carlo-giacosa", "lenz-moser"]
    for name in names:
        await run(name)


if __name__ == "__main__":
    asyncio.run(main())
