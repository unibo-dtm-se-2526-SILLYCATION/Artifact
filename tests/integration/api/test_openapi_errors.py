"""Per-operation OpenAPI audit and agreement with existing HTTP error handlers.

Routers are mounted only here. The matrix records use-case failures, not every
possible exception caused by a broken repository or server configuration.
"""

from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from sillycation.adapters.api.app import create_app
from sillycation.adapters.api import dependencies as deps
from sillycation.adapters.api.routes.episodes import router as episodes_router
from sillycation.adapters.api.routes.trip_reads import router as reads_router
from sillycation.adapters.api.routes.trips import router as trips_router
from sillycation.adapters.api.schemas.errors import (
    ApplicationErrorResponse,
    ProtectedAPIUnavailableResponse,
    RegistrationValidationErrorResponse,
    RequestValidationErrorResponse,
)
from sillycation.domain.errors import (
    Duplicate,
    InvalidData,
    InvalidState,
    NotAuthorized,
    NotFound,
)
from sillycation.domain.identifiers import UserId

# method, OpenAPI path, success status, use-case provider, application codes.
OPERATIONS = [
    ("get", "/api/v1/trips", 200, deps.get_list_my_trips, ()),
    (
        "get",
        "/api/v1/trips/{trip_id}/invitation-code",
        200,
        deps.get_trip_invitation_code,
        ("not_authorized", "not_found"),
    ),
    (
        "get",
        "/api/v1/trips/{trip_id}/join-requests",
        200,
        deps.get_pending_join_requests,
        ("not_authorized", "not_found"),
    ),
    (
        "get",
        "/api/v1/trips/{trip_id}/participants",
        200,
        deps.get_trip_participants,
        ("not_authorized", "not_found"),
    ),
    (
        "get",
        "/api/v1/trips/{trip_id}/episodes",
        200,
        deps.get_trip_episodes,
        ("not_authorized", "not_found"),
    ),
    # Ranking can report InvalidData for inconsistent completed episode data.
    (
        "get",
        "/api/v1/trips/{trip_id}/ranking",
        200,
        deps.get_participant_ranking,
        ("not_authorized", "not_found", "invalid_data"),
    ),
    (
        "get",
        "/api/v1/trips/{trip_id}/dashboard",
        200,
        deps.get_trip_dashboard,
        ("not_authorized", "not_found", "invalid_data"),
    ),
    (
        "post",
        "/api/v1/trips",
        201,
        deps.get_transactional_commands,
        ("not_found", "invalid_state", "duplicate", "invalid_data"),
    ),
    (
        "post",
        "/api/v1/join-requests",
        201,
        deps.get_transactional_commands,
        ("not_found", "invalid_state", "duplicate"),
    ),
    (
        "post",
        "/api/v1/trips/{trip_id}/join-requests/{request_id}/approve",
        200,
        deps.get_transactional_commands,
        ("not_authorized", "not_found", "invalid_state"),
    ),
    (
        "post",
        "/api/v1/trips/{trip_id}/join-requests/{request_id}/reject",
        200,
        deps.get_transactional_commands,
        ("not_authorized", "not_found", "invalid_state"),
    ),
    (
        "post",
        "/api/v1/trips/{trip_id}/activate",
        200,
        deps.get_transactional_commands,
        ("not_authorized", "not_found", "invalid_state"),
    ),
    (
        "post",
        "/api/v1/trips/{trip_id}/complete",
        200,
        deps.get_transactional_commands,
        ("not_authorized", "not_found", "invalid_state"),
    ),
    (
        "post",
        "/api/v1/trips/{trip_id}/archive",
        200,
        deps.get_transactional_commands,
        ("not_authorized", "not_found", "invalid_state"),
    ),
    (
        "post",
        "/api/v1/trips/{trip_id}/episodes",
        201,
        deps.get_create_episode,
        ("not_authorized", "not_found", "invalid_state", "duplicate", "invalid_data"),
    ),
    (
        "put",
        "/api/v1/episodes/{episode_id}",
        200,
        deps.get_edit_episode,
        ("not_authorized", "not_found", "invalid_state", "invalid_data"),
    ),
    (
        "delete",
        "/api/v1/episodes/{episode_id}",
        204,
        deps.get_delete_episode,
        ("not_authorized", "not_found", "invalid_state"),
    ),
    (
        "post",
        "/api/v1/episodes/{episode_id}/submit",
        200,
        deps.get_submit_episode,
        ("not_authorized", "not_found", "invalid_state"),
    ),
    (
        "post",
        "/api/v1/episodes/{episode_id}/votes",
        201,
        deps.get_cast_vote,
        ("not_authorized", "not_found", "invalid_state", "duplicate", "invalid_data"),
    ),
    (
        "post",
        "/api/v1/users",
        201,
        deps.get_transactional_commands,
        ("duplicate", "invalid_data"),
    ),
]
ERRORS = {
    "not_authorized": (NotAuthorized, 403),
    "not_found": (NotFound, 404),
    "invalid_state": (InvalidState, 409),
    "duplicate": (Duplicate, 409),
    "invalid_data": (InvalidData, 422),
}


def internal_app():
    app = create_app()
    for router in (reads_router, trips_router, episodes_router):
        app.include_router(router, prefix="/api/v1")
    return app


@pytest.fixture(scope="module")
def schema():
    return internal_app().openapi()


def schema_refs(value) -> set[str]:
    if "$ref" in value:
        return {value["$ref"].rsplit("/", 1)[-1]}
    return {ref for branch in value.get("anyOf", []) for ref in schema_refs(branch)}


def request_body(path: str):
    if path.endswith("/votes"):
        return {"value": 3}
    if path == "/api/v1/users":
        return {
            "username": "Chiara",
            "email": "chiara@example.org",
            "password": "PRIVATE_PASSWORD",
        }
    if path == "/api/v1/trips":
        return {"name": "Roma", "start_date": "2026-11-10", "end_date": "2026-11-10"}
    if path == "/api/v1/join-requests":
        return {"invitation_code": "CODE"}
    return {
        "title": "Title",
        "description": "Details",
        "date": "2026-11-10",
        "protagonist_id": "member",
    }


def concrete_path(path: str) -> str:
    return (
        path.replace("{trip_id}", "trip")
        .replace("{request_id}", "request")
        .replace("{episode_id}", "episode")
    )


@pytest.mark.parametrize("method,path,success,provider,codes", OPERATIONS)
def test_only_pertinent_statuses_and_application_examples_are_documented(
    schema, method, path, success, provider, codes
) -> None:
    responses = schema["paths"][path][method]["responses"]
    expected = {str(success), "422"} | {str(ERRORS[code][1]) for code in codes}
    if path != "/api/v1/users":
        expected.add("503")
    if (
        method == "get"
        and path
        in {
            "/api/v1/trips",
            "/api/v1/trips/{trip_id}/invitation-code",
            "/api/v1/trips/{trip_id}/join-requests",
            "/api/v1/trips/{trip_id}/participants",
        }
    ) or (
        method == "post"
        and provider is deps.get_transactional_commands
        and path != "/api/v1/users"
    ):
        expected.add("401")
    assert set(responses) == expected
    documented_codes = set()
    for status_code, response in responses.items():
        if int(status_code) < 400 or status_code in ("401", "503"):
            continue
        content = response["content"]["application/json"]
        assert response["description"]
        assert content["schema"]
        for name, example in content.get("examples", {}).items():
            body = example["value"]
            if "error" in body:
                ApplicationErrorResponse.model_validate(body)
                code = body["error"]["code"]
                assert name == code
                assert ERRORS[code][1] == int(status_code)
                documented_codes.add(code)
            else:
                assert status_code == "422"
                assert name == "request_validation"
                model = (
                    RegistrationValidationErrorResponse
                    if path == "/api/v1/users"
                    else RequestValidationErrorResponse
                )
                model.model_validate(body)
    assert documented_codes == set(codes)
    refs = schema_refs(responses["422"]["content"]["application/json"]["schema"])
    expected_validation = (
        "RegistrationValidationErrorResponse"
        if path == "/api/v1/users"
        else "RequestValidationErrorResponse"
    )
    assert refs == (
        {expected_validation, "ApplicationErrorResponse"}
        if "invalid_data" in codes
        else {expected_validation}
    )


def transactional_method(path: str) -> str:
    return {
        "/api/v1/users": "register_user",
        "/api/v1/trips": "create_trip",
        "/api/v1/join-requests": "request_join_trip",
        "/api/v1/trips/{trip_id}/join-requests/{request_id}/approve": "approve_join_request",
        "/api/v1/trips/{trip_id}/join-requests/{request_id}/reject": "reject_join_request",
        "/api/v1/trips/{trip_id}/activate": "activate_trip",
        "/api/v1/trips/{trip_id}/complete": "complete_trip",
        "/api/v1/trips/{trip_id}/archive": "archive_trip",
    }[path]


ERROR_CASES = [
    (method, path, provider, code)
    for method, path, _, provider, codes in OPERATIONS
    for code in codes
]


@pytest.mark.parametrize("method,path,provider,code", ERROR_CASES)
def test_documented_example_matches_actual_handler_response(
    schema, method, path, provider, code
) -> None:
    # Inject a typed failure to check HTTP/schema agreement, not business rules.
    error_type, status_code = ERRORS[code]
    use_case = Mock()
    operation = (
        getattr(use_case, transactional_method(path))
        if provider is deps.get_transactional_commands
        else use_case.execute
    )
    operation.side_effect = error_type("PRIVATE_PASSWORD PRIVATE_HASH")
    app = internal_app()
    app.dependency_overrides[deps.get_authenticated_user_id] = lambda: UserId("actor")
    app.dependency_overrides[provider] = lambda: use_case
    with TestClient(app) as client:
        response = client.request(method, concrete_path(path), json=request_body(path))
    assert response.status_code == status_code
    documented = schema["paths"][path][method]["responses"][str(status_code)][
        "content"
    ]["application/json"]["examples"][code]["value"]
    assert response.json() == documented
    assert "PRIVATE_PASSWORD" not in response.text
    assert "PRIVATE_HASH" not in response.text


PROTECTED_OPERATIONS = [item for item in OPERATIONS if item[1] != "/api/v1/users"]


@pytest.mark.parametrize("method,path,success,provider,codes", PROTECTED_OPERATIONS)
def test_current_gate_503_is_documented_without_resolving_repositories(
    schema, method, path, success, provider, codes
) -> None:
    with TestClient(internal_app()) as client:
        response = client.request(method, concrete_path(path), json=request_body(path))
    assert response.status_code == 503
    documented = schema["paths"][path][method]["responses"]["503"]["content"][
        "application/json"
    ]["example"]
    assert response.json() == documented
    ProtectedAPIUnavailableResponse.model_validate(response.json())


@pytest.mark.parametrize(
    "path,body,provider",
    [
        ("/api/v1/trips", {"name": 7}, deps.get_transactional_commands),
        (
            "/api/v1/join-requests",
            {"invitation_code": 7},
            deps.get_transactional_commands,
        ),
        ("/api/v1/trips/trip/episodes", {"title": 7}, deps.get_create_episode),
        ("/api/v1/episodes/episode/votes", {"value": True}, deps.get_cast_vote),
    ],
)
def test_standard_validation_body_matches_documented_detail_format(
    path, body, provider
) -> None:
    app = internal_app()
    use_case = Mock()
    app.dependency_overrides[deps.get_authenticated_user_id] = lambda: UserId("actor")
    app.dependency_overrides[provider] = lambda: use_case
    with TestClient(app) as client:
        response = client.post(path, json=body)
    assert response.status_code == 422
    assert "error" not in response.json()
    parsed = RequestValidationErrorResponse.model_validate(response.json())
    assert parsed.model_dump() == response.json()
    use_case.assert_not_called()
    assert use_case.mock_calls == []


def test_registration_validation_schema_and_runtime_exclude_credential_values(
    schema,
) -> None:
    detail = schema["components"]["schemas"]["RegistrationValidationErrorDetail"]
    assert detail["additionalProperties"] is False
    assert set(detail["properties"]) == {"type", "loc", "msg"}
    standard = schema["components"]["schemas"]["RequestValidationErrorDetail"]
    assert standard["additionalProperties"] is True
    app = internal_app()
    app.dependency_overrides[deps.get_transactional_commands] = lambda: Mock()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/users",
            json={
                "username": "Chiara",
                "email": "chiara@example.org",
                "password": {"value": "PRIVATE_PASSWORD"},
                "password_hash": "PRIVATE_HASH",
            },
        )
    assert response.status_code == 422
    parsed = RegistrationValidationErrorResponse.model_validate(response.json())
    assert parsed.model_dump() == response.json()
    assert "PRIVATE_PASSWORD" not in response.text
    assert "PRIVATE_HASH" not in response.text
    assert "input" not in response.json()["detail"][0]
    registration_docs = str(schema["paths"]["/api/v1/users"]["post"]["responses"])
    assert "PRIVATE_PASSWORD" not in registration_docs
    assert "PRIVATE_HASH" not in registration_docs


def test_documentation_adds_neither_operations_nor_public_routes(schema) -> None:
    documented = {
        (method, path)
        for path, methods in schema["paths"].items()
        for method in methods
    }
    assert documented == {(method, path) for method, path, _, _, _ in OPERATIONS}
    assert (
        "content"
        not in schema["paths"]["/api/v1/episodes/{episode_id}"]["delete"]["responses"][
            "204"
        ]
    )
    assert set(create_app().openapi()["paths"]) == {"/api/v1/users"}
    with TestClient(create_app()) as client:
        for method, path, _, _, _ in PROTECTED_OPERATIONS:
            assert (
                client.request(
                    method, concrete_path(path), json=request_body(path)
                ).status_code
                == 404
            )
