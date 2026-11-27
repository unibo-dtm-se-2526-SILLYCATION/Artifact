"""HTTP login orchestration and credential-safe failures."""

from ipaddress import IPv6Address, IPv6Network, ip_address
from secrets import token_urlsafe
from threading import BoundedSemaphore
from typing import Optional

from fastapi import HTTPException, status

from sillycation.adapters.api.jwt_tokens import JwtTokens
from sillycation.adapters.persistence.login_attempts import SqliteLoginAttempts
from sillycation.application.ports.passwords import PasswordHasher
from sillycation.application.ports.repositories import UserRepository
from sillycation.application.user_use_cases import AuthenticateUser
from sillycation.domain.errors import NotAuthorized
from sillycation.domain.identifiers import UserId


def authentication_required() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _rate_limited(seconds: int) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Too many login attempts",
        headers={"Retry-After": str(seconds)},
    )


def _peer_key(host: Optional[str]) -> str:
    try:
        address = ip_address(host or "")
    except ValueError:
        return "unknown"
    if isinstance(address, IPv6Address):
        return str(address.ipv4_mapped or IPv6Network((int(address), 64), strict=False))
    return str(address)


class _LoginPasswords:
    """Track whether AuthenticateUser performed the expensive verification."""

    def __init__(self, passwords: PasswordHasher) -> None:
        self._passwords = passwords
        self.checked = False

    def hash(self, password: str) -> str:
        return self._passwords.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        self.checked = True
        return self._passwords.verify(password, password_hash)


class HttpAuthentication:
    def __init__(
        self,
        tokens: JwtTokens,
        attempts: SqliteLoginAttempts,
        passwords: PasswordHasher,
    ) -> None:
        self.tokens = tokens
        self._attempts = attempts
        self._passwords = passwords
        self._dummy_hash = passwords.hash(token_urlsafe(32))
        self._slots = BoundedSemaphore(2)

    def authenticate(
        self, users: UserRepository, username: str, password: str, peer: Optional[str]
    ) -> UserId:
        retry_after = self._attempts.consume(_peer_key(peer))
        if retry_after is not None:
            raise _rate_limited(retry_after)
        if not self._slots.acquire(blocking=False):
            raise _rate_limited(1)
        try:
            passwords = _LoginPasswords(self._passwords)
            return AuthenticateUser(users, passwords).execute(
                username=username, password=password
            )
        except NotAuthorized:
            if not passwords.checked:
                self._passwords.verify(password, self._dummy_hash)
            raise authentication_required() from None
        finally:
            self._slots.release()
