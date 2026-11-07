from fastapi.testclient import TestClient

from slam.api import app


def test_health_and_initial_status():
    client = TestClient(app)
    assert client.get("/api/health").json() == {"status": "ok"}
    status = client.get("/api/status").json()
    assert status["state"] == "idle"
    assert status["runId"] is None
