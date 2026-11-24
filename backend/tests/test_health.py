import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))
from main import app


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_local_web_app_can_check_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": "http://localhost:3000"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_unlisted_origin_is_not_allowed() -> None:
    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": "https://example.com"})

    assert "access-control-allow-origin" not in response.headers
