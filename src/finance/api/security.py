"""Localhost-only guards.

- MutationGuardMiddleware: custom header + Origin check on every state-changing request (CSRF/DNS rebinding),
  and Fetch-Metadata check on every /api request (a cross-site <img>/<script> cannot trigger a GET).
- SecurityHeadersMiddleware: anti-framing (clickjacking), CSP, nosniff, CORP on every response.
"""

from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from finance.api.errors import error_response

LOCAL_HOSTS = ("localhost", "127.0.0.1")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CLIENT_HEADER = "x-finance-client"
# Sec-Fetch-Site values a browser sends for the app itself (same-origin) or a typed URL/bookmark (none).
# Absent = not a browser (curl, tests).
ALLOWED_FETCH_SITES = {"same-origin", "none"}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
       "frame-ancestors 'none'")
SECURITY_HEADERS = [
    (b"content-security-policy", CSP.encode()),
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"cross-origin-opener-policy", b"same-origin"),
]


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                names = {k.lower() for k, _v in message.get("headers", [])}
                message["headers"] = list(message.get("headers", [])) + [
                    (k, v) for k, v in SECURITY_HEADERS if k not in names]
            await send(message)

        await self.app(scope, receive, send_with_headers)


class MutationGuardMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        fetch_site = request.headers.get("sec-fetch-site")
        if scope["path"].startswith("/api/") and fetch_site is not None and fetch_site not in ALLOWED_FETCH_SITES:
            await error_response(403)(scope, receive, send)
            return
        if scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        origin = request.headers.get("origin")
        if request.headers.get(CLIENT_HEADER) != "web" or (origin and urlsplit(origin).hostname not in LOCAL_HOSTS):
            response = error_response(403)
        elif _has_body(request) and not request.headers.get("content-type", "").split(";")[0].strip() \
                .lower().endswith("json"):
            response = error_response(415)
        else:
            await self.app(scope, receive, send)
            return
        await response(scope, receive, send)


def _has_body(request: Request) -> bool:
    length = request.headers.get("content-length")
    return (length not in (None, "0")) or "transfer-encoding" in request.headers
