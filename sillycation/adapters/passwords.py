"""Argon2id implementation of the application password hashing port."""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from argon2.profiles import RFC_9106_LOW_MEMORY


class Argon2PasswordHasher:
    def __init__(self) -> None:
        self._hasher = PasswordHasher.from_parameters(RFC_9106_LOW_MEMORY)

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except VerifyMismatchError:
            return False
