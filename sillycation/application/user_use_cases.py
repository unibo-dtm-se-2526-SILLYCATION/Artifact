"""Registration and credential verification, independent of authentication transport."""

from sillycation.application.ports.passwords import PasswordHasher
from sillycation.application.ports.repositories import UserRepository
from sillycation.domain.identifiers import UserId
from sillycation.domain.user import User


class DuplicateUserError(Exception):
    """A registration identity, username or email is already in use."""


class InvalidCredentialsError(Exception):
    """The supplied credentials do not authenticate a user."""


class RegisterUser:
    def __init__(self, users: UserRepository, passwords: PasswordHasher) -> None:
        self._users = users
        self._passwords = passwords

    def execute(
        self, *, user_id: UserId, username: str, email: str, password: str
    ) -> UserId:
        """Register using a caller-allocated identity and return only UserId.

        Uniqueness checks are preliminary; atomic uniqueness under concurrency
        requires support from the persistence adapter. Domain validation and
        technical dependency errors propagate without conversion.
        """
        if not isinstance(password, str) or not password.strip():
            raise ValueError("Password is required")
        if self._users.get_by_id(user_id) is not None:
            raise DuplicateUserError("User identity already exists")
        if self._users.exists_by_username(username):
            raise DuplicateUserError("Username already exists")
        if self._users.exists_by_email(email):
            raise DuplicateUserError("Email already exists")
        password_hash = self._passwords.hash(password)
        user = User(user_id, username, email, password_hash)
        return self._users.save(user).id


class AuthenticateUser:
    def __init__(self, users: UserRepository, passwords: PasswordHasher) -> None:
        self._users = users
        self._passwords = passwords

    def execute(self, *, username: str, password: str) -> UserId:
        """Verify credentials without mutation; UserId is not a session credential."""
        user = self._users.get_by_username(username)
        if user is None or not self._passwords.verify(password, user.password_hash):
            raise InvalidCredentialsError("Invalid credentials")
        return user.id
