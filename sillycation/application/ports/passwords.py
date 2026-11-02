"""Password operations supplied by an external hashing implementation."""

from typing import Protocol


class PasswordHasher(Protocol):
    """Hash and verify passwords without exposing algorithm details to use cases."""

    def hash(self, password: str) -> str:
        """Return a secure hash of the exact password supplied by the caller."""
        ...

    def verify(self, password: str, password_hash: str) -> bool:
        """Return whether the exact password matches the stored hash.

        Technical failures propagate as exceptions, rather than mismatches.
        """
        ...
