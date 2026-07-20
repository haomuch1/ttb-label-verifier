"""End-to-end API tests against the MockExtractor — zero network."""

import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.ratelimit import limiter


@pytest.fixture(autouse=True)
def mock_extractor(monkeypatch):
    monkeypatch.setenv("EXTRACTOR", "mock")
    # fresh rate-limit state per test
    limiter._per_ip.clear()
    limiter._day_count = 0
    yield


@pytest.fixture
def client():
    return TestClient(app)


def png_bytes(seed: int = 0) -> bytes:
    img = Image.new("RGB", (40, 40), color=(seed * 40 % 255, 100, 150))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestSingleVerify:
    def test_image_upload_returns_full_report(self, client):
        resp = client.post(
            "/api/verify", files={"file": ("label.png", png_bytes(), "image/png")}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["verdict"] in {"PASS", "NEEDS_REVIEW", "FAIL"}
        assert body["filename"] == "label.png"
        assert body["model"] == "mock"
        check_ids = {c["check_id"] for c in body["checks"]}
        assert "health_warning" in check_ids
        assert "abv_form_match" in check_ids
        assert body["extraction"]["labels"]

    def test_content_type_sniffed_from_magic_bytes(self, client):
        # Declared type is wrong; magic bytes say PNG — accepted anyway.
        resp = client.post(
            "/api/verify",
            files={"file": ("odd.bin", png_bytes(), "application/octet-stream")},
        )
        assert resp.status_code == 200

    def test_garbage_rejected_as_unsupported(self, client):
        resp = client.post(
            "/api/verify", files={"file": ("x.txt", b"hello world", "text/plain")}
        )
        assert resp.status_code == 415

    def test_empty_file_rejected(self, client):
        resp = client.post("/api/verify", files={"file": ("x.png", b"", "image/png")})
        assert resp.status_code == 400


class TestBatch:
    def test_streams_one_ndjson_line_per_file(self, client):
        files = [("files", (f"doc{i}.png", png_bytes(i), "image/png")) for i in range(5)]
        resp = client.post("/api/verify/batch", files=files)
        assert resp.status_code == 200
        lines = [json.loads(l) for l in resp.text.strip().splitlines()]
        assert len(lines) == 5
        assert {l["filename"] for l in lines} == {f"doc{i}.png" for i in range(5)}
        for line in lines:
            assert line["verdict"] in {"PASS", "NEEDS_REVIEW", "FAIL"}

    def test_bad_file_in_batch_reports_error_not_500(self, client):
        files = [
            ("files", ("good.png", png_bytes(), "image/png")),
            ("files", ("bad.txt", b"not an image", "text/plain")),
        ]
        resp = client.post("/api/verify/batch", files=files)
        assert resp.status_code == 200
        lines = [json.loads(l) for l in resp.text.strip().splitlines()]
        by_name = {l["filename"]: l for l in lines}
        assert "verdict" in by_name["good.png"]
        assert "error" in by_name["bad.txt"]

    def test_batch_size_cap(self, client):
        files = [("files", (f"d{i}.png", png_bytes(i), "image/png")) for i in range(21)]
        resp = client.post("/api/verify/batch", files=files)
        assert resp.status_code == 413


class TestRateLimiting:
    def test_per_ip_limit_returns_429(self, client, monkeypatch):
        monkeypatch.setattr(limiter, "per_ip_per_minute", 2)
        ok1 = client.post("/api/verify", files={"file": ("a.png", png_bytes(), "image/png")})
        ok2 = client.post("/api/verify", files={"file": ("b.png", png_bytes(), "image/png")})
        blocked = client.post("/api/verify", files={"file": ("c.png", png_bytes(), "image/png")})
        assert ok1.status_code == ok2.status_code == 200
        assert blocked.status_code == 429

    def test_daily_cap_returns_429(self, client, monkeypatch):
        monkeypatch.setattr(limiter, "daily_cap", 1)
        ok = client.post("/api/verify", files={"file": ("a.png", png_bytes(), "image/png")})
        blocked = client.post("/api/verify", files={"file": ("b.png", png_bytes(), "image/png")})
        assert ok.status_code == 200
        assert blocked.status_code == 429
        assert "Daily" in blocked.json()["detail"]

    def test_batch_charges_per_file_against_daily_cap(self, client, monkeypatch):
        monkeypatch.setattr(limiter, "daily_cap", 3)
        files = [("files", (f"d{i}.png", png_bytes(i), "image/png")) for i in range(4)]
        resp = client.post("/api/verify/batch", files=files)
        assert resp.status_code == 429


class TestStatic:
    def test_root_serves_ui(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "TTB Label Verifier" in resp.text

    def test_health(self, client):
        assert client.get("/health").json()["status"] == "ok"
