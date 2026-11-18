"""Logging setup with secret redaction."""
import logging
import re

# Redacts values of key=value / key: value pairs whose key looks secret, and bearer tokens.
_SECRET_KV = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|authorization)\b(\s*[=:]\s*)([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")


def redact(text: str) -> str:
    text = _BEARER.sub("Bearer [REDACTED]", text)
    return _SECRET_KV.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
