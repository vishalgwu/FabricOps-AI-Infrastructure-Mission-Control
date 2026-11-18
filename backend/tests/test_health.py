from fastapi.testclient import TestClient

from app.core.logging import redact
from app.main import app

client = TestClient(app)


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_cors_allows_local_frontend():
    r = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_blocks_unknown_origin():
    r = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_redaction():
    out = redact("api_key=abc123 Authorization: Bearer xyz.789 user=bob")
    assert "abc123" not in out and "xyz.789" not in out
    assert "user=bob" in out
