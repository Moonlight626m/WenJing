import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_health_live(client):
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_alias(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_ready_reports_postgres_state(client):
    """无 DB 时 ready 503 并带 problems；有 DB 时 200。二者均为合法就绪语义。"""
    resp = client.get("/health/ready")
    if resp.status_code == 200:
        assert resp.json()["checks"]["postgres"] is True
    else:
        body = resp.json()
        assert body["status"] == "unavailable"
        assert any("postgres" in p for p in body["problems"])


def test_request_id_header_and_metrics_increment(client):
    from app.infrastructure.diagnostics.metrics import metrics

    before = metrics.get("wenjing_requests_total")
    resp = client.get("/health/live")
    assert "X-Request-ID" in resp.headers
    assert metrics.get("wenjing_requests_total") >= before + 1


def test_metrics_endpoint_content_type(client):
    resp = client.get("/metrics")
    assert resp.headers["content-type"].startswith("text/plain")
    assert "wenjing_requests_total" in resp.text
