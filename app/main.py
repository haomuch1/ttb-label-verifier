"""TTB Label Verifier — FastAPI application.

Upload a COLA application PDF or a label photo; get PASS / NEEDS REVIEW /
FAIL with per-check detail. The model extracts, code judges; nothing is
persisted.
"""

import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.audit import audit_log
from app.extractors import get_extractor
from app.pdf import render_pdf
from app.ratelimit import client_ip, limiter
from app.rules import verify

app = FastAPI(
    title="TTB Label Verifier",
    description=(
        "Prototype compliance checker for COLA applications (TTB Form 5100.31) "
        "and alcohol beverage label images."
    ),
    version="0.3.0",
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_BATCH_FILES = 20
BATCH_CONCURRENCY = 4

IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "ttb-label-verifier"}


def _sniff_media_type(data: bytes, declared: str | None) -> str:
    """Trust magic bytes over the declared content type."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if declared in IMAGE_TYPES or declared == "application/pdf":
        return declared
    raise HTTPException(
        status_code=415,
        detail="Unsupported file type. Upload a PDF or an image (PNG/JPEG/WebP).",
    )


def _document_images(data: bytes, media_type: str) -> list[tuple[bytes, str]]:
    if media_type == "application/pdf":
        try:
            return render_pdf(data)
        except Exception as exc:  # poppler missing / corrupt PDF
            raise HTTPException(
                status_code=422,
                detail=f"Could not read the PDF ({type(exc).__name__}). "
                       "If this is a photo, upload it as an image instead.",
            ) from exc
    return [(data, media_type)]


def _require_name(value: str, field: str) -> str:
    name = " ".join((value or "").split())
    if not name:
        raise HTTPException(status_code=400, detail=f"Enter your name or ID ({field}).")
    if len(name) > 120:
        raise HTTPException(status_code=400, detail=f"{field} name is too long.")
    return name


async def _verify_one(filename: str, data: bytes, processor: str) -> dict:
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 25 MB limit.")

    media_type = _sniff_media_type(data, None)
    images = _document_images(data, media_type)
    extractor = get_extractor()

    start = time.perf_counter()
    try:
        result = await extractor.extract(images)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                f"The extraction backend ({extractor.name}) is unavailable: "
                f"{type(exc).__name__}. Check the backend and retry."
            ),
        ) from exc
    elapsed = time.perf_counter() - start

    report = verify(result.extraction)
    record = audit_log.record(filename, processor, report.verdict.value)
    return {
        "filename": filename,
        "audit_id": record.id,
        "processor": record.processor,
        "processed_at": record.processed_at,
        "verdict": report.verdict.value,
        "cfr_part": report.cfr_part,
        "checks": [c.model_dump() for c in report.checks],
        "extraction": result.extraction.model_dump(),
        "seconds": round(elapsed, 2),
        "model": result.model,
        "tokens": {"input": result.input_tokens, "output": result.output_tokens},
    }


@app.post("/api/verify")
async def verify_endpoint(
    request: Request, file: UploadFile, processor: str = Form("")
) -> dict:
    processor = _require_name(processor, "processor")
    limiter.check(client_ip(request), cost=1)
    data = await file.read()
    return await _verify_one(file.filename or "upload", data, processor)


@app.post("/api/verify/batch")
async def verify_batch(
    request: Request, files: list[UploadFile], processor: str = Form("")
) -> StreamingResponse:
    processor = _require_name(processor, "processor")
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(
            status_code=413, detail=f"At most {MAX_BATCH_FILES} files per batch."
        )
    limiter.check(client_ip(request), cost=len(files))

    # Read uploads before streaming begins — the files are part of the
    # request body and unavailable once the response starts.
    payloads = [(f.filename or f"file-{i}", await f.read())
                for i, f in enumerate(files, start=1)]

    semaphore = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def one(name: str, data: bytes) -> dict:
        async with semaphore:
            try:
                return await _verify_one(name, data, processor)
            except HTTPException as exc:
                return {"filename": name, "error": exc.detail}
            except Exception as exc:
                return {"filename": name, "error": type(exc).__name__}

    async def stream():
        tasks = [asyncio.create_task(one(name, data)) for name, data in payloads]
        for finished in asyncio.as_completed(tasks):
            result = await finished
            yield json.dumps(result, ensure_ascii=False) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


class ReviewRequest(BaseModel):
    reviewer: str


@app.get("/api/audit")
def audit_list() -> dict:
    return {"records": [r.to_dict() for r in audit_log.list_records()]}


@app.post("/api/audit/{audit_id}/review")
def audit_review(audit_id: int, body: ReviewRequest) -> dict:
    reviewer = _require_name(body.reviewer, "reviewer")
    try:
        record = audit_log.review(audit_id, reviewer)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown audit record.")
    except ValueError:
        raise HTTPException(status_code=409, detail="This item was already reviewed.")
    return record.to_dict()


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
