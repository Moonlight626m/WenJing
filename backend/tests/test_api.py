import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_session(client):
    resp = client.post("/api/sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"]
    assert body["stage"] == "init"


def test_websocket_echo(client):
    with client.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "system"
        ws.send_json({"ping": "pong"})
        data = ws.receive_json()
        assert data["type"] == "echo"
        assert data["content"] == {"ping": "pong"}
