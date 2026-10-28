from dataclasses import FrozenInstanceError

import pytest

from sillycation.domain.identifiers import UserId
from sillycation.domain.user import User


@pytest.fixture
def data():
    return dict(
        id=UserId("user-1"),
        username="Alice",
        email="alice@example.org",
        password_hash="opaque-hash",
    )


def test_valid_creation_preserves_documented_attributes(data):
    user = User(**data)
    assert user.id == UserId("user-1")
    assert user.username == data["username"]
    assert user.email == data["email"]
    assert user.password_hash == data["password_hash"]


@pytest.mark.parametrize("field", ["username", "email", "password_hash"])
@pytest.mark.parametrize("value", ["", "   ", "\t\n", None])
def test_required_text_cannot_be_missing_or_blank(data, field, value):
    data[field] = value
    with pytest.raises(ValueError, match=field):
        User(**data)


def test_identity_is_required(data):
    data["id"] = None
    with pytest.raises(ValueError, match="identity"):
        User(**data)


@pytest.mark.parametrize("field", ["username", "email", "password_hash"])
def test_text_is_preserved_without_normalization_or_extra_constraints(data, field):
    data[field] = "  Unrestricted text " * 1000 + "\n"
    assert getattr(User(**data), field) == data[field]


def test_identity_depends_on_user_id_not_profile_or_credentials(data):
    user = User(**data)
    same_identity = User(UserId("user-1"), "Bob", "bob@example.org", "other-hash")
    different_identity = User(**{**data, "id": UserId("user-2")})

    assert user == same_identity
    assert user != different_identity


@pytest.mark.parametrize("field", ["id", "username", "email", "password_hash"])
def test_properties_cannot_be_reassigned(data, field):
    user = User(**data)
    with pytest.raises(FrozenInstanceError):
        setattr(user, field, data[field])
