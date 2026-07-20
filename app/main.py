"""TTB Label Verifier — FastAPI application entry point.

Verifies COLA applications (TTB Form 5100.31) and standalone label images
against 27 CFR labeling requirements. The model extracts; code judges.
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

app = FastAPI(
    title="TTB Label Verifier",
    description=(
        "Prototype compliance checker for COLA applications (TTB Form 5100.31) "
        "and alcohol beverage label images."
    ),
    version="0.1.0",
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.get("/health")
def health() -> dict:
    """Liveness check for deployment platform and smoke tests."""
    return {"status": "ok", "service": "ttb-label-verifier"}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
