"""End-to-end API tests against the MockExtractor — zero network."""

import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.audit import audit_log
from app.main import app
from app.ratelimit import limiter


@pytest.fixture(autouse=True)
def mock_extractor(monkeypatch):
    monkeypatch.setenv("EXTRACTOR", "mock")
    # fresh rate-limit and audit state per test
    limiter._per_ip.clear()
    limiter._day_count = 0
    audit_log.clear()
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
            "/api/verify", files={"file": ("label.png", png_bytes(), "image/png")},
            data={"processor": "Test Agent"},
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
            data={"processor": "Test Agent"},
        )
        assert resp.status_code == 200

    def test_garbage_rejected_as_unsupported(self, client):
        resp = client.post(
            "/api/verify", files={"file": ("x.txt", b"hello world", "text/plain")},
            data={"processor": "Test Agent"},
        )
        assert resp.status_code == 415

    def test_empty_file_rejected(self, client):
        resp = client.post("/api/verify", files={"file": ("x.png", b"", "image/png")},
                           data={"processor": "Test Agent"})
        assert resp.status_code == 400


class TestBatch:
    def test_streams_one_ndjson_line_per_file(self, client):
        files = [("files", (f"doc{i}.png", png_bytes(i), "image/png")) for i in range(5)]
        resp = client.post("/api/verify/batch", files=files, data={"processor": "Test Agent"})
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
        resp = client.post("/api/verify/batch", files=files, data={"processor": "Test Agent"})
        assert resp.status_code == 200
        lines = [json.loads(l) for l in resp.text.strip().splitlines()]
        by_name = {l["filename"]: l for l in lines}
        assert "verdict" in by_name["good.png"]
        assert "error" in by_name["bad.txt"]

    def test_batch_size_cap(self, client):
        files = [("files", (f"d{i}.png", png_bytes(i), "image/png")) for i in range(21)]
        resp = client.post("/api/verify/batch", files=files, data={"processor": "Test Agent"})
        assert resp.status_code == 413


class TestRateLimiting:
    def test_per_ip_limit_returns_429(self, client, monkeypatch):
        monkeypatch.setattr(limiter, "per_ip_per_minute", 2)
        ok1 = client.post("/api/verify", files={"file": ("a.png", png_bytes(), "image/png")}, data={"processor": "Test Agent"})
        ok2 = client.post("/api/verify", files={"file": ("b.png", png_bytes(), "image/png")}, data={"processor": "Test Agent"})
        blocked = client.post("/api/verify", files={"file": ("c.png", png_bytes(), "image/png")}, data={"processor": "Test Agent"})
        assert ok1.status_code == ok2.status_code == 200
        assert blocked.status_code == 429

    def test_daily_cap_returns_429(self, client, monkeypatch):
        monkeypatch.setattr(limiter, "daily_cap", 1)
        ok = client.post("/api/verify", files={"file": ("a.png", png_bytes(), "image/png")}, data={"processor": "Test Agent"})
        blocked = client.post("/api/verify", files={"file": ("b.png", png_bytes(), "image/png")}, data={"processor": "Test Agent"})
        assert ok.status_code == 200
        assert blocked.status_code == 429
        assert "Daily" in blocked.json()["detail"]

    def test_batch_charges_per_file_against_daily_cap(self, client, monkeypatch):
        monkeypatch.setattr(limiter, "daily_cap", 3)
        files = [("files", (f"d{i}.png", png_bytes(i), "image/png")) for i in range(4)]
        resp = client.post("/api/verify/batch", files=files, data={"processor": "Test Agent"})
        assert resp.status_code == 429


class TestAudit:
    def _process(self, client, name="doc.png", processor="Alice"):
        return client.post(
            "/api/verify", files={"file": (name, png_bytes(), "image/png")},
            data={"processor": processor},
        ).json()

    def test_processing_requires_a_name(self, client):
        resp = client.post(
            "/api/verify", files={"file": ("a.png", png_bytes(), "image/png")},
            data={"processor": "   "},
        )
        assert resp.status_code == 400
        assert "name" in resp.json()["detail"].lower()

    def test_processing_creates_audit_record(self, client):
        body = self._process(client, processor="Alice")
        assert body["processor"] == "Alice"
        records = client.get("/api/audit").json()["records"]
        assert len(records) == 1
        rec = records[0]
        assert rec["id"] == body["audit_id"]
        assert rec["processor"] == "Alice"
        assert rec["verdict"] == body["verdict"]
        assert rec["reviewer"] is None
        assert rec["name_mismatch"] is None
        # decision record only — no extraction content in the audit trail
        assert "extraction" not in rec and "checks" not in rec

    def test_batch_creates_record_per_file(self, client):
        files = [("files", (f"d{i}.png", png_bytes(i), "image/png")) for i in range(3)]
        client.post("/api/verify/batch", files=files, data={"processor": "Alice"})
        assert len(client.get("/api/audit").json()["records"]) == 3

    def test_review_same_name_no_mismatch(self, client):
        body = self._process(client, processor="Alice")
        rec = client.post(
            f"/api/audit/{body['audit_id']}/review", json={"reviewer": "alice"}
        ).json()
        # case/whitespace differences are the same person, not a mismatch
        assert rec["reviewer"] == "alice"
        assert rec["name_mismatch"] is False
        assert rec["reviewed_at"]

    def test_review_different_name_flags_mismatch_but_records_both(self, client):
        body = self._process(client, processor="Alice")
        resp = client.post(
            f"/api/audit/{body['audit_id']}/review", json={"reviewer": "Bob"}
        )
        assert resp.status_code == 200  # mismatch is information, not an error
        rec = resp.json()
        assert rec["processor"] == "Alice"
        assert rec["reviewer"] == "Bob"
        assert rec["name_mismatch"] is True

    def test_review_blank_name_rejected(self, client):
        body = self._process(client)
        resp = client.post(
            f"/api/audit/{body['audit_id']}/review", json={"reviewer": "  "}
        )
        assert resp.status_code == 400

    def test_review_unknown_record_404(self, client):
        assert client.post("/api/audit/999/review",
                           json={"reviewer": "Alice"}).status_code == 404

    def test_double_review_conflicts(self, client):
        body = self._process(client)
        first = client.post(f"/api/audit/{body['audit_id']}/review",
                            json={"reviewer": "Alice"})
        second = client.post(f"/api/audit/{body['audit_id']}/review",
                             json={"reviewer": "Bob"})
        assert first.status_code == 200
        assert second.status_code == 409


class TestUnreadableOutcome:
    @pytest.fixture
    def unreadable_backend(self, monkeypatch):
        from app.extractors.base import ExtractionResult
        from app.models import Extraction

        async def fake(extractor, images, pdf_info=None):
            return ExtractionResult(
                extraction=Extraction(form=None, labels=[]),
                input_tokens=0, output_tokens=0, model="mock",
            )

        monkeypatch.setattr("app.main.run_extraction", fake)

    def test_unreadable_returns_message_and_no_audit_record(
        self, client, unreadable_backend
    ):
        resp = client.post(
            "/api/verify", files={"file": ("blurry.png", png_bytes(), "image/png")},
            data={"processor": "Jenny Park"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["verdict"] == "UNREADABLE"
        assert "clearer copy" in body["message"]
        assert body["audit_id"] is None
        assert body["checks"] == []
        # like error items: no verdict was rendered, so no decision record
        assert client.get("/api/audit").json()["records"] == []

    def test_readable_upload_still_gets_audit_record(self, client):
        resp = client.post(
            "/api/verify", files={"file": ("ok.png", png_bytes(), "image/png")},
            data={"processor": "Jenny Park"},
        )
        assert resp.json()["audit_id"] is not None
        assert len(client.get("/api/audit").json()["records"]) == 1


class TestStatic:
    def test_root_serves_ui(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "TTB Label Verifier" in resp.text

    def test_health(self, client):
        assert client.get("/health").json()["status"] == "ok"
