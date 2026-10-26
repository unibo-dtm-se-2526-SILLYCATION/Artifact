"""Registered user identity and required account data."""

from dataclasses import dataclass, field

from sillycation.domain.identifiers import UserId


@dataclass(frozen=True)
class User:
    """An entity identified by UserId, with no credential modification operations.

    The caller supplies an already computed password hash. Hashing,
    authentication and uniqueness checks across users are external concerns.
    Text is validated for presence and stored unchanged.
    """

    id: UserId
    username: str = field(compare=False)
    email: str = field(compare=False)
    password_hash: str = field(compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.id is None:
            raise ValueError("User identity is required")
        for name in ("username", "email", "password_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"User {name} is required")
