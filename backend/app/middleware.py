"""Request rate limiting (abuse protection for the paid Groq/Tavily endpoints) and secure response headers."""
import ipaddress
import threading
import time
from collections import deque

from fastapi import Request
from fastapi.responses import JSONResponse

from . import config

WINDOW_SECONDS = 60.0
_PRUNE_AT = 10_000


class RateLimiter:
    """Sliding-window limiter, per (bucket, client IP), kept in this process's memory.
    With several backend workers each keeps its own count, so the effective limit is workers x limit; use a shared
    store (e.g. Redis) at the proxy if you need exact global limits."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, bucket: str, ip: str, limit: int, now: float | None = None) -> float | None:
        """Record a request. Returns None if allowed, else the seconds to wait."""
        now = time.monotonic() if now is None else now
        with self._lock:
            if len(self._hits) > _PRUNE_AT:
                self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < WINDOW_SECONDS}
            q = self._hits.setdefault((bucket, ip), deque())
            while q and now - q[0] >= WINDOW_SECONDS:
                q.popleft()
            if len(q) >= limit:
                return max(1.0, WINDOW_SECONDS - (now - q[0]))
            q.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def bucket_for(method: str, path: str) -> str:
    if method == "POST":
        if path == "/api/upload":
            return "upload"
        if path == "/api/claims/extract" or (path.startswith("/api/reports/") and path.endswith("/summary")):
            return "extract"
        if path == "/api/claims/search":
            return "search"
        if path == "/api/claims/verify":
            return "verify"
    return "default"


def client_ip(request: Request) -> str:
    n = config.trusted_proxy_count()
    if n:
        header = config.client_ip_header()
        if header:  # a header the trusted proxy overwrites: preferred over counting X-Forwarded-For entries
            try:
                return str(ipaddress.ip_address(request.headers.get(header, "").strip()))
            except ValueError:
                pass  # missing or not an IP address: fall back to X-Forwarded-For
        parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if parts:  # the entry added by our outermost trusted proxy; anything left of it is client-controlled
            return parts[-n] if len(parts) >= n else parts[0]
    return request.client.host if request.client else "unknown"


def _is_https(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    return bool(config.trusted_proxy_count()) and request.headers.get("x-forwarded-proto", "").lower() == "https"


async def rate_limit_and_headers(request: Request, call_next):
    path = request.url.path
    if config.rate_limit_enabled() and request.method != "OPTIONS" and path.startswith("/api/"):
        bucket = bucket_for(request.method, path)
        wait = limiter.check(bucket, client_ip(request), config.rate_limits()[bucket])
        if wait is not None:
            secs = int(wait) + 1
            return _secure(
                JSONResponse(
                    status_code=429,
                    content={"detail": {"code": "rate_limited", "message": f"Too many requests. Please wait {secs} seconds and try again."}},
                    headers={"Retry-After": str(secs)},
                ),
                request,
            )
    return _secure(await call_next(request), request)


def _secure(response, request: Request):
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "no-referrer")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if not request.url.path.startswith(("/docs", "/redoc", "/openapi")):
        h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    if request.url.path.startswith("/api/"):
        h.setdefault("Cache-Control", "no-store")
    if _is_https(request) or config.app_env() == "production":
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response
