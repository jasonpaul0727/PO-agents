import os
import secrets
import time
from collections import defaultdict

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

_basic = HTTPBasic(auto_error=False)


def require_demo_auth(credentials: HTTPBasicCredentials | None = Depends(_basic)) -> None:
    """Gate the app behind a shared login when DEMO_USERNAME/DEMO_PASSWORD are set
    (public deploy). Both unset (local dev, tests) -> no-op, so nothing else changes."""
    user = os.getenv("DEMO_USERNAME")
    pw = os.getenv("DEMO_PASSWORD")
    if not user or not pw:
        return

    ok = credentials is not None and secrets.compare_digest(
        credentials.username, user
    ) and secrets.compare_digest(credentials.password, pw)
    if not ok:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )


class RateLimiter:
    """Fixed-window limiter per key (here: client IP). In-memory, so it only holds
    across a single process — fine for a one-instance demo box, not for multiple
    replicas (state isn't shared between them)."""

    def __init__(self, max_calls: int, window_seconds: int):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> None:
        now = time.monotonic()
        hits = self._hits[key]
        cutoff = now - self.window_seconds
        while hits and hits[0] < cutoff:
            hits.pop(0)
        if len(hits) >= self.max_calls:
            raise HTTPException(
                status_code=429, detail="Too many requests — try again in a minute."
            )
        hits.append(now)


# Guards the one endpoint that spends real money (LLM extraction call).
process_limiter = RateLimiter(
    max_calls=int(os.getenv("PROCESS_RATE_LIMIT_PER_MINUTE", "5")),
    window_seconds=60,
)


def enforce_process_rate_limit(request: Request) -> None:
    key = request.client.host if request.client else "unknown"
    process_limiter.check(key)
