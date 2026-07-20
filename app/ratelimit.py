"""In-memory rate limiting: per-IP sliding window + a daily instance cap.

Protects a public free-tier deployment from being hammered and from
running up inference cost. Nothing is persisted (consistent with the
no-database design), so counters reset on restart — acceptable for a
prototype; a production deployment would back this with Redis or the
platform's own limiter.
"""

import os
import time
from collections import defaultdict, deque
from datetime import date

from fastapi import HTTPException, Request

PER_IP_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_IP_PER_MIN", "12"))
DAILY_INSTANCE_CAP = int(os.environ.get("RATE_LIMIT_DAILY_CAP", "300"))

# How many proxy hops the trusted infrastructure appends to X-Forwarded-For.
# Render's edge terminates TLS and appends the real client address as the
# last (rightmost) entry, so the trusted client IP is 1 hop in from the
# right. Anything to the left is client-supplied and must not be trusted.
TRUSTED_PROXY_HOPS = int(os.environ.get("TRUSTED_PROXY_HOPS", "1"))

# Cap on distinct per-IP buckets held in memory. A stale-key sweep keeps
# this bounded even under a flood of (spoofed or genuine) distinct IPs, so
# the limiter can't be turned into a memory-exhaustion vector.
MAX_TRACKED_IPS = int(os.environ.get("RATE_LIMIT_MAX_TRACKED_IPS", "10000"))

_WINDOW_SECONDS = 60


class RateLimiter:
    def __init__(self, per_ip_per_minute: int, daily_cap: int) -> None:
        self.per_ip_per_minute = per_ip_per_minute
        self.daily_cap = daily_cap
        self._per_ip: dict[str, deque[float]] = defaultdict(deque)
        self._day = date.today()
        self._day_count = 0

    def _evict_stale(self, now: float) -> None:
        """Drop IP buckets whose entire window has expired.

        Called when the tracked-IP count crosses MAX_TRACKED_IPS so a burst
        of distinct IPs (e.g. rotated spoofed addresses) can't grow the dict
        without bound. Keys still inside their window are retained.
        """
        stale = [
            ip for ip, window in self._per_ip.items()
            if not window or now - window[-1] > _WINDOW_SECONDS
        ]
        for ip in stale:
            del self._per_ip[ip]

    def check(self, ip: str, cost: int = 1) -> None:
        """Charge `cost` verifications (a batch of N files costs N)."""
        now = time.monotonic()
        today = date.today()
        if today != self._day:
            self._day = today
            self._day_count = 0

        if len(self._per_ip) > MAX_TRACKED_IPS:
            self._evict_stale(now)

        if self._day_count + cost > self.daily_cap:
            raise HTTPException(
                status_code=429,
                detail=(
                    "Daily verification limit for this instance reached. "
                    "Try again tomorrow."
                ),
            )

        window = self._per_ip[ip]
        while window and now - window[0] > _WINDOW_SECONDS:
            window.popleft()
        if len(window) + cost > self.per_ip_per_minute:
            raise HTTPException(
                status_code=429,
                detail="Too many requests from this address. Wait a minute and retry.",
            )

        for _ in range(cost):
            window.append(now)
        self._day_count += cost


limiter = RateLimiter(PER_IP_PER_MINUTE, DAILY_INSTANCE_CAP)


def client_ip(request: Request) -> str:
    """Derive the client IP from the trusted proxy hop, not client input.

    Render appends the real client address to the RIGHT of any
    client-supplied X-Forwarded-For values, so we count TRUSTED_PROXY_HOPS
    in from the right. Trusting the leftmost value instead would let a
    client spoof its address — and rotate it every request to hand itself a
    fresh per-IP bucket, voiding the limit. Values to the left of the
    trusted hop are attacker-controlled and ignored.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if len(parts) >= TRUSTED_PROXY_HOPS:
            return parts[-TRUSTED_PROXY_HOPS]
    return request.client.host if request.client else "unknown"
