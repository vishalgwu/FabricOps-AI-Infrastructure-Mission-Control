"""Logging with secret redaction.

Redaction is applied to the FINAL text of every log line (message, arguments and traceback), not only
to the message, because secrets most often leak through exception text and through dicts of headers.
"""
import logging
import re
from collections.abc import Iterable

_REDACTED = "[REDACTED]"

# key = value, key: value, 'key': 'value' and "key": "value" (as found in dict reprs and JSON) for names
# that look secret. Group 1 is everything up to the value; the value itself is replaced.
_SECRET_KV = re.compile(
    r"""(?ix)
    (\b(?:x-)?(?:api[_-]?key|secret|token|password|passwd|authorization)\b["']?\s*[:=]\s*["']?)
    ([^\s,;"'})\]]+)
    """
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
# Provider-style keys, wherever they appear (for example Anthropic sk-ant-... or generic sk-...).
_KEY_SHAPES = re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{8,}")

_known_secrets: set[str] = set()


def register_secrets(values: Iterable[str | None]) -> None:
    """Also redact these exact values, whatever format they are in. Very short values are ignored so
    that an empty or trivial setting cannot blank out ordinary words."""
    _known_secrets.update(v for v in values if v and len(v) >= 8)


def redact(text: str) -> str:
    for secret in _known_secrets:
        text = text.replace(secret, _REDACTED)
    text = _BEARER.sub(f"Bearer {_REDACTED}", text)
    text = _KEY_SHAPES.sub(_REDACTED, text)
    return _SECRET_KV.sub(lambda m: f"{m.group(1)}{_REDACTED}", text)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure_logging(level: str = "INFO", secrets: Iterable[str | None] = ()) -> None:
    register_secrets(secrets)
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # uvicorn installs its own handlers; send its records through ours so they are redacted too.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
