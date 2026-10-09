"""
Tests for backend health check and root endpoints.
"""

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_health_check_returns_ok():
    """
    Ensure GET /health returns 200 OK and expected status payload.
    """
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "AI Resume Screening System"
    assert "version" in payload


def test_root_endpoint_metadata():
    """
    Ensure GET / returns 200 OK with valid documentation links.
    """
    response = client.get("/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "AI Resume Screening System"
    assert payload["health_url"] == "/health"
    assert payload["docs_url"] == "/docs"


def test_not_found_endpoint():
    """
    Ensure non-existent endpoints return standard 404 response.
    """
    response = client.get("/non-existent-endpoint")
    assert response.status_code == 404
