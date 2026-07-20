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

_WINDOW_SECONDS = 60


class RateLimiter:
    def __init__(self, per_ip_per_minute: int, daily_cap: int) -> None:
        self.per_ip_per_minute = per_ip_per_minute
        self.daily_cap = daily_cap
        self._per_ip: dict[str, deque[float]] = defaultdict(deque)
        self._day = date.today()
        self._day_count = 0

    def check(self, ip: str, cost: int = 1) -> None:
        """Charge `cost` verifications (a batch of N files costs N)."""
        now = time.monotonic()
        today = date.today()
        if today != self._day:
            self._day = today
            self._day_count = 0

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
    # Render terminates TLS at a proxy; the client lands in X-Forwarded-For.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
