"""In-memory audit trail: who processed what, the verdict, who reviewed.

Compliance decisions require accountability, so every processed document
gets a decision record: processor name, verdict, timestamp, filename, and
the reviewer's name once signed off. Deliberately minimal:

- Decision records only — no extraction content, no label images, no PII
  beyond the name/ID the agent types.
- In-memory, resets on restart — consistent with the prototype's
  "nothing sensitive persisted" posture. Production would back this with
  an append-only store.
- Names are attestation stamps, not authentication. Production would use
  Treasury SSO; this is a stand-in for the accountability concept.

The processor and reviewer names are always both recorded. A mismatch is
information, not an error: a genuine two-person review is legitimate and
must be captured correctly, while flagging the difference catches the
typo case (separation-of-duties awareness).
"""

import itertools
import threading
from dataclasses import dataclass
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_name(name: str) -> str:
    return " ".join(name.split()).casefold()


@dataclass
class AuditRecord:
    id: int
    filename: str
    processor: str
    verdict: str
    processed_at: str
    reviewer: str | None = None
    reviewed_at: str | None = None

    @property
    def name_mismatch(self) -> bool | None:
        """None until reviewed; then whether reviewer differs from processor."""
        if self.reviewer is None:
            return None
        return normalize_name(self.reviewer) != normalize_name(self.processor)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "processor": self.processor,
            "verdict": self.verdict,
            "processed_at": self.processed_at,
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at,
            "name_mismatch": self.name_mismatch,
        }


class AuditLog:
    def __init__(self) -> None:
        self._records: dict[int, AuditRecord] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def record(self, filename: str, processor: str, verdict: str) -> AuditRecord:
        with self._lock:
            rec = AuditRecord(
                id=next(self._ids),
                filename=filename,
                processor=processor,
                verdict=verdict,
                processed_at=_now(),
            )
            self._records[rec.id] = rec
            return rec

    def review(self, record_id: int, reviewer: str) -> AuditRecord:
        """Attach the reviewer attestation. Raises KeyError on unknown id,
        ValueError if the record was already signed off."""
        with self._lock:
            rec = self._records[record_id]
            if rec.reviewer is not None:
                raise ValueError("already reviewed")
            rec.reviewer = reviewer
            rec.reviewed_at = _now()
            return rec

    def list_records(self) -> list[AuditRecord]:
        """Newest first."""
        return sorted(self._records.values(), key=lambda r: r.id, reverse=True)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


audit_log = AuditLog()
