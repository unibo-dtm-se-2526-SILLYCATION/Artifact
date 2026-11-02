from typing import Optional

import pytest

from sillycation.application.ports.passwords import PasswordHasher
from sillycation.application.ports.repositories import UserRepository
from sillycation.application.user_use_cases import (
    AuthenticateUser,
    DuplicateUserError,
    InvalidCredentialsError,
    RegisterUser,
)
from sillycation.domain.identifiers import UserId
from sillycation.domain.user import User


PASSWORD = "  exact password\t"
HASH = "opaque-test-hash"


class MemoryUsers:
    def __init__(self) -> None:
        self.users: dict[UserId, User] = {}
        self.saved: list[User] = []

    def save(self, user: User) -> User:
        self.users[user.id] = user
        self.saved.append(user)
        return user

    def get_by_id(self, user_id: UserId) -> Optional[User]:
        return self.users.get(user_id)

    def get_by_username(self, username: str) -> Optional[User]:
        return next((u for u in self.users.values() if u.username == username), None)

    def get_by_email(self, email: str) -> Optional[User]:
        return next((u for u in self.users.values() if u.email == email), None)

    def exists_by_username(self, username: str) -> bool:
        return self.get_by_username(username) is not None

    def exists_by_email(self, email: str) -> bool:
        return self.get_by_email(email) is not None


class FakeHasher:
    """Fixed test credential pair; no cryptography or production authentication."""

    def __init__(self) -> None:
        self.hash_calls: list[str] = []
        self.verify_calls: list[tuple[str, str]] = []

    def hash(self, password: str) -> str:
        self.hash_calls.append(password)
        return HASH

    def verify(self, password: str, password_hash: str) -> bool:
        self.verify_calls.append((password, password_hash))
        return password == PASSWORD and password_hash == HASH


@pytest.fixture
def users():
    return MemoryUsers()


@pytest.fixture
def hasher():
    return FakeHasher()


@pytest.fixture
def data():
    return dict(
        user_id=UserId("new"),
        username="Alice",
        email="alice@example.org",
        password=PASSWORD,
    )


@pytest.fixture
def registered(users):
    user = User(UserId("existing"), "Alice", "alice@example.org", HASH)
    users.users[user.id] = user
    return user


def test_register_saves_only_hash_and_returns_identity(data) -> None:
    users = MemoryUsers()
    hasher = FakeHasher()
    user_port: UserRepository = users
    password_port: PasswordHasher = hasher
    result = RegisterUser(user_port, password_port).execute(**data)
    assert result == data["user_id"]
    assert isinstance(result, UserId)
    assert len(users.saved) == 1
    stored = users.users[result]
    assert vars(stored) == dict(
        id=result, username=data["username"], email=data["email"], password_hash=HASH
    )
    assert PASSWORD not in vars(stored).values()
    assert hasher.hash_calls == [PASSWORD]
    assert hasher.verify_calls == []
    assert PASSWORD not in repr(result)
    assert HASH not in repr(result)


@pytest.mark.parametrize("field", ["user_id", "username", "email"])
def test_duplicates_are_rejected_before_hashing_or_saving(users, hasher, data, field):
    existing = User(UserId("existing"), "Other", "other@example.org", HASH)
    users.users[existing.id] = existing
    data[field] = existing.id if field == "user_id" else getattr(existing, field)
    before = dict(users.users)
    with pytest.raises(DuplicateUserError) as error:
        RegisterUser(users, hasher).execute(**data)
    assert users.users == before
    assert users.saved == []
    assert hasher.hash_calls == []
    assert PASSWORD not in str(error.value)
    assert HASH not in str(error.value)


@pytest.mark.parametrize("password", ["", "   ", "\t\n", None])
def test_registration_rejects_missing_or_blank_password(users, hasher, data, password):
    data["password"] = password
    with pytest.raises(ValueError, match="Password"):
        RegisterUser(users, hasher).execute(**data)
    assert users.saved == []
    assert hasher.hash_calls == []


@pytest.mark.parametrize("field", ["username", "email"])
@pytest.mark.parametrize("value", [None, "", " \t\n"])
def test_registration_delegates_required_fields_to_user(
    users, hasher, data, field, value
):
    data[field] = value
    with pytest.raises(ValueError, match=field):
        RegisterUser(users, hasher).execute(**data)
    assert users.saved == []


def test_registration_requires_identity(users, hasher, data):
    data["user_id"] = None
    with pytest.raises(ValueError, match="identity"):
        RegisterUser(users, hasher).execute(**data)
    assert users.saved == []


@pytest.mark.parametrize("value", ["", "   "])
def test_invalid_hash_is_not_persisted(users, hasher, data, monkeypatch, value):
    monkeypatch.setattr(hasher, "hash", lambda password: value)
    with pytest.raises(ValueError, match="password_hash"):
        RegisterUser(users, hasher).execute(**data)
    assert users.saved == []


def test_registration_preserves_profile_text(users, hasher, data):
    data["username"] = " Alice "
    data["email"] = " Alice@Example.org "
    result = RegisterUser(users, hasher).execute(**data)
    assert users.users[result].username == data["username"]
    assert users.users[result].email == data["email"]


def test_login_returns_identity_without_mutation_or_save(users, hasher, registered):
    before = vars(registered).copy()
    result = AuthenticateUser(users, hasher).execute(
        username="Alice", password=PASSWORD
    )
    assert result == registered.id
    assert isinstance(result, UserId)
    assert hasher.verify_calls == [(PASSWORD, HASH)]
    assert hasher.hash_calls == []
    assert users.saved == []
    assert users.users[registered.id] is registered
    assert vars(registered) == before
    assert PASSWORD not in repr(result)
    assert HASH not in repr(result)


def test_unknown_username_and_wrong_password_have_same_error(users, hasher, registered):
    before = vars(registered).copy()
    errors = []
    for username, password in [("missing", PASSWORD), ("Alice", "wrong")]:
        with pytest.raises(InvalidCredentialsError) as error:
            AuthenticateUser(users, hasher).execute(
                username=username, password=password
            )
        errors.append(str(error.value))
    assert errors[0] == errors[1]
    assert PASSWORD not in errors[0]
    assert HASH not in errors[0]
    assert hasher.verify_calls == [("wrong", HASH)]
    assert hasher.hash_calls == []
    assert users.saved == []
    assert vars(registered) == before


def test_login_does_not_normalize_username(users, hasher, registered):
    with pytest.raises(InvalidCredentialsError):
        AuthenticateUser(users, hasher).execute(username=" Alice ", password=PASSWORD)
    assert hasher.verify_calls == []
    assert users.saved == []


@pytest.mark.parametrize(
    "operation", ["get_by_id", "exists_by_username", "exists_by_email", "hash", "save"]
)
def test_registration_propagates_technical_errors(
    users, hasher, data, monkeypatch, operation
):
    failure = RuntimeError("Dependency unavailable")

    def fail(*args):
        raise failure

    target = hasher if operation == "hash" else users
    monkeypatch.setattr(target, operation, fail)
    with pytest.raises(RuntimeError) as error:
        RegisterUser(users, hasher).execute(**data)
    assert error.value is failure
    assert users.saved == []


@pytest.mark.parametrize("operation", ["get_by_username", "verify"])
def test_login_propagates_technical_errors(
    users, hasher, registered, monkeypatch, operation
):
    failure = RuntimeError("Dependency unavailable")

    def fail(*args):
        raise failure

    target = hasher if operation == "verify" else users
    monkeypatch.setattr(target, operation, fail)
    with pytest.raises(RuntimeError) as error:
        AuthenticateUser(users, hasher).execute(username="Alice", password=PASSWORD)
    assert error.value is failure
    assert users.saved == []
