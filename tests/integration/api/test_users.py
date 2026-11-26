"""Internal registration contracts, with repository/hasher doubles only in tests."""

from unittest.mock import MagicMock, Mock
from uuid import UUID

from fastapi import Request
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.exc import IntegrityError

from sillycation.adapters.api.app import create_app
from sillycation.adapters.api.dependencies import (
    get_new_user_id,
    get_password_hasher,
    get_transactional_commands,
    get_unit_of_work_factory,
)
from sillycation.application.ports.passwords import PasswordHasher
from sillycation.application.ports.repositories import UserRepository
from sillycation.application.ports.unit_of_work import UnitOfWork
from sillycation.application.transactional import TransactionalCommands
from sillycation.domain.identifiers import UserId
from sillycation.domain.user import User

USER_ID = UserId("generated-user")
PASSWORD = " Private-registration-password "
HASH = "HASH_TEST_DOUBLE_ONLY"
BODY = {"username": "Chiara", "email": "chiara@example.org", "password": PASSWORD}
PATH = "/api/v1/users"


@pytest.fixture
def dependencies():
    users = Mock(spec=UserRepository)
    users.get_by_id.return_value = None
    users.exists_by_username.return_value = False
    users.exists_by_email.return_value = False
    users.save.side_effect = lambda user: user
    passwords = Mock(spec=PasswordHasher)
    passwords.hash.return_value = HASH
    return users, passwords


def internal_app(dependencies):
    users, passwords = dependencies
    app = create_app()
    unit = MagicMock(spec=UnitOfWork)
    unit.__enter__.return_value = unit
    unit.users = users
    app.dependency_overrides.update(
        {
            get_unit_of_work_factory: lambda: lambda: unit,
            get_password_hasher: lambda: passwords,
            get_new_user_id: lambda: USER_ID,
        }
    )
    return app


def test_real_use_case_delegates_hashing_and_returns_only_server_identity(
    dependencies,
) -> None:
    users, passwords = dependencies
    with TestClient(internal_app(dependencies)) as client:
        response = client.post(PATH, json=BODY, params={"user_id": "client-selected"})
    assert response.status_code == 201
    assert response.json() == {"id": USER_ID.value}
    assert PASSWORD not in response.text
    assert HASH not in response.text
    passwords.hash.assert_called_once_with(PASSWORD)
    passwords.verify.assert_not_called()
    users.get_by_id.assert_called_once_with(USER_ID)
    users.exists_by_username.assert_called_once_with("Chiara")
    users.exists_by_email.assert_called_once_with("chiara@example.org")
    user = users.save.call_args.args[0]
    assert isinstance(user, User)
    assert user.id == USER_ID
    assert user.username == BODY["username"]
    assert user.email == BODY["email"]
    assert user.password_hash == HASH
    assert user.password_hash != PASSWORD
    assert not hasattr(user, "password")


def test_commands_can_be_overridden_without_resolving_unit_of_work_or_hasher() -> None:
    commands = Mock(spec=TransactionalCommands)
    commands.register_user.return_value = USER_ID
    app = create_app()
    app.dependency_overrides[get_transactional_commands] = lambda: commands
    app.dependency_overrides[get_new_user_id] = lambda: USER_ID
    with TestClient(app) as client:
        response = client.post(PATH, json=BODY)
    assert response.status_code == 201
    assert response.json() == {"id": USER_ID.value}
    commands.register_user.assert_called_once_with(
        user_id=USER_ID,
        username=BODY["username"],
        email=BODY["email"],
        password=PASSWORD,
    )


@pytest.mark.parametrize("field", ["username", "email", "password"])
def test_missing_required_field_returns_validation_error_without_persistence(
    dependencies, field
) -> None:
    users, passwords = dependencies
    body = {key: value for key, value in BODY.items() if key != field}
    with TestClient(internal_app(dependencies)) as client:
        response = client.post(PATH, json=body)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", field]
    assert "input" not in response.json()["detail"][0]
    assert PASSWORD not in response.text
    users.save.assert_not_called()
    passwords.hash.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"username": ""},
        {"username": " "},
        {"username": None},
        {"username": 123},
        {"email": ""},
        {"email": " "},
        {"email": None},
        {"email": 123},
        {"password": ""},
        {"password": None},
        {"password": 123},
        {"id": "chosen"},
        {"user_id": "chosen"},
        {"role": "admin"},
    ],
)
def test_invalid_and_server_owned_input_never_reaches_hashing_or_save(
    dependencies, changes
) -> None:
    users, passwords = dependencies
    with TestClient(internal_app(dependencies)) as client:
        response = client.post(PATH, json={**BODY, **changes})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert PASSWORD not in response.text
    assert HASH not in response.text
    users.save.assert_not_called()
    passwords.hash.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"password": {"raw": "SENSITIVE_PASSWORD"}},
        {"password": ["SENSITIVE_PASSWORD"]},
        {"password_hash": "SENSITIVE_HASH"},
        {"credentials": {"password": "SENSITIVE_PASSWORD", "hash": "SENSITIVE_HASH"}},
    ],
)
def test_rejected_credential_values_are_not_echoed_by_validation(
    dependencies, changes
) -> None:
    users, passwords = dependencies
    with TestClient(internal_app(dependencies)) as client:
        response = client.post(PATH, json={**BODY, **changes})
    assert response.status_code == 422
    assert "SENSITIVE_PASSWORD" not in response.text
    assert "SENSITIVE_HASH" not in response.text
    assert PASSWORD not in response.text
    for detail in response.json()["detail"]:
        assert set(detail) == {"type", "loc", "msg"}
    users.save.assert_not_called()
    passwords.hash.assert_not_called()


def test_malformed_json_preserves_safe_422_shape(dependencies) -> None:
    with TestClient(internal_app(dependencies)) as client:
        response = client.post(
            PATH,
            content='{"password":"SENSITIVE_PASSWORD",',
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "json_invalid"
    assert "SENSITIVE_PASSWORD" not in response.text


def test_blank_password_is_rejected_by_existing_use_case(dependencies) -> None:
    users, passwords = dependencies
    with TestClient(internal_app(dependencies)) as client:
        response = client.post(PATH, json={**BODY, "password": "  "})
    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "invalid_data", "message": "Invalid application data."}
    }
    passwords.hash.assert_not_called()
    users.save.assert_not_called()


@pytest.mark.parametrize("duplicate", ["id", "username", "email"])
def test_duplicates_are_rejected_before_hashing_and_save(
    dependencies, duplicate
) -> None:
    users, passwords = dependencies
    if duplicate == "id":
        users.get_by_id.return_value = User(
            USER_ID, "Existing", "existing@example.org", HASH
        )
    elif duplicate == "username":
        users.exists_by_username.return_value = True
    else:
        users.exists_by_email.return_value = True
    with TestClient(internal_app(dependencies)) as client:
        response = client.post(PATH, json=BODY)
    assert response.status_code == 409
    assert response.json() == {
        "error": {"code": "duplicate", "message": "Resource or action already exists."}
    }
    assert PASSWORD not in response.text
    assert HASH not in response.text
    passwords.hash.assert_not_called()
    users.save.assert_not_called()


def test_hasher_is_explicitly_unconfigured_and_has_no_fallback() -> None:
    with pytest.raises(
        RuntimeError, match="PasswordHasher provider has not been configured"
    ):
        get_password_hasher(Request({"type": "http", "app": create_app()}))


@pytest.mark.parametrize("failure", ["hasher", "database"])
def test_technical_failures_are_not_misclassified_or_exposed(
    dependencies, failure
) -> None:
    users, passwords = dependencies
    if failure == "hasher":
        passwords.hash.side_effect = RuntimeError("SENSITIVE_PASSWORD SENSITIVE_HASH")
    else:
        users.save.side_effect = IntegrityError(
            "SELECT SENSITIVE_HASH",
            {"password": "SENSITIVE_PASSWORD"},
            RuntimeError("database"),
        )
    with TestClient(
        internal_app(dependencies), raise_server_exceptions=False
    ) as client:
        response = client.post(PATH, json=BODY)
    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert "SENSITIVE" not in response.text
    if failure == "hasher":
        users.save.assert_not_called()


def test_server_user_id_provider_returns_uuid4() -> None:
    identity = get_new_user_id()
    assert isinstance(identity, UserId)
    assert UUID(identity.value).version == 4


def test_public_openapi_has_only_registration_without_auth_or_sensitive_response_fields() -> (
    None
):
    app = create_app()
    schema = app.openapi()
    assert set(schema["paths"]) == {PATH}
    assert set(schema["paths"][PATH]) == {"post"}
    operation = schema["paths"][PATH]["post"]
    assert "201" in operation["responses"]
    assert "422" in operation["responses"]
    assert not operation.get("parameters")
    assert not operation.get("security")
    response_schema = schema["components"]["schemas"]["RegisteredUserResponse"]
    assert set(response_schema["properties"]) == {"id"}
    password_schema = schema["components"]["schemas"]["RegisterUserRequest"][
        "properties"
    ]["password"]
    assert password_schema["writeOnly"] is True
    assert create_app().dependency_overrides == {}


def test_no_login_or_token_endpoint_is_added(dependencies) -> None:
    with TestClient(internal_app(dependencies)) as client:
        for path in ("/api/v1/auth/login", "/api/v1/token", "/api/v1/users/me"):
            assert client.post(path, json=BODY).status_code == 404
