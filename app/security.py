"""Small security helpers: rate limiting, CSRF, security headers."""
from __future__ import annotations

import hmac
import threading
import time
from collections import defaultdict, deque

from fastapi import Form, HTTPException, Request

CSRF_COOKIE = "tm_csrf"


class RateLimiter:
    """Sliding-window limiter kept in memory (fine for a single free-tier instance)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, per_seconds: int) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - per_seconds:
                q.popleft()
            if len(q) >= limit:
                raise HTTPException(429, "Too many attempts. Wait a minute and try again.")
            q.append(now)
            if len(self._hits) > 5000:  # keep memory bounded
                for stale in [k for k, v in self._hits.items() if not v or v[-1] <= now - per_seconds]:
                    self._hits.pop(stale, None)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def csrf_protect(request: Request, csrf_token: str = Form("")) -> None:
    cookie = request.cookies.get(CSRF_COOKIE, "")
    if not cookie or not hmac.compare_digest(cookie, csrf_token):
        raise HTTPException(403, "This form expired. Go back, reload the page and try again.")


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; font-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'"
    ),
}
