"""HTTP checks for the API skeleton, without business routes or persistence."""

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from sillycation.adapters.api.app import create_app
from sillycation.adapters.api.router import router


def test_factory_creates_independent_applications() -> None:
    first = create_app()
    second = create_app()

    assert isinstance(first, FastAPI)
    assert first is not second
    assert first.state is not second.state


def test_openapi_is_available_without_business_endpoints() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Sillycation API"
    assert schema["openapi"].startswith("3.")
    assert set(schema["paths"]) == {"/api/v1/users"}


def test_swagger_documentation_uses_application_openapi() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/docs")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "/openapi.json" in response.text


def test_factory_mounts_the_versioned_router(monkeypatch) -> None:
    # Patch only the factory's router: never mutate the shared production router.
    test_router = APIRouter(prefix=router.prefix)

    @test_router.get("/probe")
    def probe() -> dict[str, str]:
        return {"status": "ok"}

    monkeypatch.setattr("sillycation.adapters.api.app.router", test_router)
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/probe").json() == {"status": "ok"}
        assert client.get("/probe").status_code == 404
        assert "/api/v1/probe" in client.get("/openapi.json").json()["paths"]
