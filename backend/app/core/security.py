"""HTTP hardening: request size limit, safe error responses, and security headers.

Both pieces are plain ASGI middleware so they apply to every route, including ones added later.
"""
import json
import logging
import sqlite3

log = logging.getLogger("fabricops.http")

SECURITY_HEADERS = {
    b"x-content-type-options": b"nosniff",
    b"cache-control": b"no-store",
    b"x-frame-options": b"DENY",
    b"referrer-policy": b"no-referrer",
}


def _envelope(code: str, message: str) -> bytes:
    return json.dumps({"error": {"code": code, "message": message, "details": []}}).encode()


async def _respond(send, status: int, code: str, message: str) -> None:
    body = _envelope(code, message)
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
               *SECURITY_HEADERS.items()]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class _TooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """Refuse request bodies over `max_bytes` (413) before the application reads them into memory.

    Checks Content-Length up front, and counts bytes as they stream in for chunked uploads.
    """

    def __init__(self, app, max_bytes: int = 65536):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await _respond(send, 413, "request_too_large", f"The request body may be at most {self.max_bytes} bytes.")
            return

        seen = 0
        too_large = False
        started = False
        done = False

        async def limited_receive():
            nonlocal seen, too_large
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    too_large = True
                    raise _TooLarge  # stop reading; the framework may turn this into its own error response
            return message

        async def tracking_send(message):
            """If the body was too large, whatever the application answered (FastAPI turns a failed
            body read into a 400) is replaced by one clean 413."""
            nonlocal started, done
            if not too_large:
                started = started or message["type"] == "http.response.start"
                await send(message)
                return
            if done:
                return
            done = started = True
            await _respond(send, 413, "request_too_large", f"The request body may be at most {self.max_bytes} bytes.")

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLarge:
            pass
        if too_large and not done:
            await _respond(send, 413, "request_too_large", f"The request body may be at most {self.max_bytes} bytes.")


class SafeResponseMiddleware:
    """Add security headers to every response, and turn an unexpected exception into a safe JSON error.

    The exception is logged here (through the redacting formatter) and NOT re-raised, so the server's
    own unredacted traceback logging never sees it. The client gets no detail about what went wrong.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def send_with_headers(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                present = {k.lower() for k, _ in message.get("headers", [])}
                message = {**message, "headers": [*message.get("headers", []),
                                                  *((k, v) for k, v in SECURITY_HEADERS.items() if k not in present)]}
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except _TooLarge:
            raise  # handled by BodySizeLimitMiddleware, which sits outside this one
        except sqlite3.OperationalError:
            log.exception("database error while handling %s %s", scope.get("method"), scope.get("path"))
            if not started:
                await _respond(send, 503, "database_unavailable", "The database is busy or unavailable. Try again shortly.")
        except Exception:  # noqa: BLE001 - the last line of defence for HTTP requests
            log.exception("unhandled error while handling %s %s", scope.get("method"), scope.get("path"))
            if not started:
                await _respond(send, 500, "internal_error", "An unexpected error occurred.")
