"""HTTP error contracts using test-only routes; production routes stay closed."""

from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.exceptions import ResponseValidationError
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from sillycation.adapters.api.app import create_app
from sillycation.adapters.api.schemas.requests import CastVoteRequest
from sillycation.adapters.api.schemas.responses import RegisteredUserResponse
from sillycation.domain.errors import (
    Duplicate,
    InvalidData,
    InvalidState,
    NotAuthorized,
    NotFound,
    SillycationError,
)

MAPPINGS = [
    (NotAuthorized, 403, "not_authorized", "Operation not permitted."),
    (NotFound, 404, "not_found", "Resource not found."),
    (InvalidState, 409, "invalid_state", "Operation not allowed in the current state."),
    (Duplicate, 409, "duplicate", "Resource or action already exists."),
    (InvalidData, 422, "invalid_data", "Invalid application data."),
]


@pytest.mark.parametrize("error_type,status_code,code,message", MAPPINGS)
@pytest.mark.parametrize(
    "internal_message", ["", "password=PRIVATE; SELECT confidential FROM users"]
)
def test_typed_errors_have_fixed_public_json(
    error_type, status_code, code, message, internal_message
) -> None:
    app = create_app()

    @app.get("/probe")
    def probe() -> None:
        raise error_type(internal_message) from RuntimeError("PRIVATE database details")

    with TestClient(app) as client:
        response = client.get(
            "/probe?password=PRIVATE", headers={"Authorization": "Bearer PRIVATE"}
        )

    assert response.status_code == status_code
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"error": {"code": code, "message": message}}
    assert "PRIVATE" not in response.text
    assert "Traceback" not in response.text


@pytest.mark.parametrize("error_type,status_code,code,message", MAPPINGS)
def test_subclasses_use_the_typed_parent_mapping(
    error_type, status_code, code, message
) -> None:
    subclass = type("SpecificFailure", (error_type,), {})
    app = create_app()

    @app.get("/probe")
    def probe() -> None:
        raise subclass("PRIVATE")

    with TestClient(app) as client:
        response = client.get("/probe")
    assert response.status_code == status_code
    assert response.json() == {"error": {"code": code, "message": message}}


@pytest.mark.parametrize("error_type,status_code,code,message", MAPPINGS)
def test_dependency_failures_use_the_same_contract(
    error_type, status_code, code, message
) -> None:
    app = create_app()

    def failing_dependency() -> None:
        raise error_type("PRIVATE")

    @app.get("/probe")
    def probe(value: Annotated[None, Depends(failing_dependency)]) -> None:
        pytest.fail("A failed dependency must prevent endpoint execution")

    with TestClient(app) as client:
        response = client.get("/probe")
    assert response.status_code == status_code
    assert response.json() == {"error": {"code": code, "message": message}}


@pytest.mark.parametrize(
    "error",
    [
        Exception("PRIVATE"),
        RuntimeError("PRIVATE"),
        ValueError("PRIVATE"),
        LookupError("PRIVATE"),
        PermissionError("PRIVATE"),
        SillycationError("PRIVATE"),
        SQLAlchemyError("PRIVATE"),
        IntegrityError(
            "SELECT PRIVATE", {"password": "PRIVATE"}, RuntimeError("PRIVATE")
        ),
        OperationalError(
            "SELECT PRIVATE", {"password": "PRIVATE"}, RuntimeError("PRIVATE")
        ),
    ],
)
def test_unexpected_failures_are_not_misclassified_as_application_errors(error) -> None:
    app = create_app()

    @app.get("/probe")
    def probe() -> None:
        raise error

    # In tests, uncaught server exceptions still propagate by default.
    with TestClient(app) as client:
        with pytest.raises(type(error)):
            client.get("/probe")
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/probe")
    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert "PRIVATE" not in response.text


@pytest.mark.parametrize(
    "body",
    [{}, {"value": True}, {"value": "3"}, {"value": 3.0}, {"value": 0}, {"value": 6}],
)
def test_standard_fastapi_request_validation_remains_422(body) -> None:
    app = create_app()

    @app.post("/probe")
    def probe(request: CastVoteRequest) -> dict[str, int]:
        return {"value": request.value}

    with TestClient(app) as client:
        response = client.post("/probe", json=body)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert response.json()["detail"][0]["loc"][0] == "body"
    assert "error" not in response.json()


def test_response_validation_is_a_server_error_not_invalid_input() -> None:
    app = create_app()

    @app.get("/probe", response_model=RegisteredUserResponse)
    def probe() -> dict[str, list[str]]:
        return {"id": ["PRIVATE"]}

    with TestClient(app) as client:
        with pytest.raises(ResponseValidationError):
            client.get("/probe")
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/probe")
    assert response.status_code == 500
    assert response.text == "Internal Server Error"


def test_http_exception_handler_and_headers_are_not_overridden() -> None:
    app = create_app()

    @app.get("/probe")
    def probe() -> None:
        raise HTTPException(
            401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    with TestClient(app) as client:
        response = client.get("/probe")
        assert client.get("/missing").json() == {"detail": "Not Found"}
    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_error_test_routes_do_not_leak_into_public_factory() -> None:
    assert set(create_app().openapi()["paths"]) == {"/api/v1/users"}
    with TestClient(create_app()) as client:
        assert client.get("/probe").status_code == 404
        assert client.get("/api/v1/trips").status_code == 404
