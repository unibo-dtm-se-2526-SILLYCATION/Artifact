from argon2 import extract_parameters
from argon2.exceptions import InvalidHashError
from argon2.profiles import RFC_9106_LOW_MEMORY
import pytest

from sillycation.adapters.passwords import Argon2PasswordHasher
from sillycation.application.ports.passwords import PasswordHasher


def test_hash_uses_argon2id_profile_and_random_salt() -> None:
    hasher: PasswordHasher = Argon2PasswordHasher()
    password = "  caffè 🔑  "
    first = hasher.hash(password)
    second = hasher.hash(password)

    assert first.startswith("$argon2id$")
    assert extract_parameters(first) == RFC_9106_LOW_MEMORY
    assert first.split("$")[-2] != second.split("$")[-2]
    assert hasher.verify(password, first)
    assert hasher.verify(password, second)
    assert not hasher.verify(password.strip(), first)


def test_invalid_hash_is_a_technical_error() -> None:
    with pytest.raises(InvalidHashError):
        Argon2PasswordHasher().verify("password", "malformed")
