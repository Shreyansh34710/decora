from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_endpoint():
    assert client.get("/health").json() == {"status": "healthy"}


def test_extract_rejects_too_short_discussion():
    response = client.post("/api/extract", json={"text": "short"})
    assert response.status_code == 422
    assert "at least 20 characters" in response.json()["detail"][0]["msg"]


def test_cors_allows_vite_dev_server():
    response = client.options(
        "/api/extract",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
