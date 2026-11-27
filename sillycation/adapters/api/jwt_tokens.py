"""Issue and verify this API's short-lived access tokens."""

import base64
from binascii import Error as Base64Error
import os
import re
from typing import Callable

import jwt
from jwt.exceptions import InvalidTokenError

from sillycation.domain.identifiers import UserId


_ALGORITHM = "HS256"
_ISSUER = "sillycation"
_AUDIENCE = "sillycation-api"
_CLAIMS = ("iss", "aud", "sub", "iat", "nbf", "exp")
_COMPACT_JWT = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


class JwtTokens:
    def __init__(self, key: bytes, lifetime: int, clock: Callable[[], float]) -> None:
        self._key = key
        self._clock = clock
        self.lifetime = lifetime

    @classmethod
    def from_environment(cls, clock: Callable[[], float]) -> "JwtTokens":
        encoded_key = os.environ.get("SILLYCATION_AUTH_SECRET", "")
        try:
            key = base64.b64decode(encoded_key + "=", altchars=b"-_", validate=True)
        except (Base64Error, ValueError):
            key = b""
        if (
            len(key) != 32
            or len(set(key)) < 16
            or base64.urlsafe_b64encode(key).decode().rstrip("=") != encoded_key
        ):
            raise ValueError(
                "SILLYCATION_AUTH_SECRET must be a random 32-byte base64url key"
            )

        try:
            lifetime = int(os.environ.get("SILLYCATION_AUTH_TTL_SECONDS", "900"))
        except ValueError:
            lifetime = 0
        if not 1 <= lifetime <= 3600:
            raise ValueError("SILLYCATION_AUTH_TTL_SECONDS must be between 1 and 3600")
        return cls(key, lifetime, clock)

    def issue(self, user: UserId) -> str:
        now = int(self._clock())
        return jwt.encode(
            {
                "iss": _ISSUER,
                "aud": _AUDIENCE,
                "sub": user.value,
                "iat": now,
                "nbf": now,
                "exp": now + self.lifetime,
            },
            self._key,
            algorithm=_ALGORITHM,
        )

    def verify(self, value: str) -> UserId:
        if len(value) > 4096 or _COMPACT_JWT.fullmatch(value) is None:
            raise InvalidTokenError("Invalid access token format")
        claims = jwt.decode(
            value,
            self._key,
            algorithms=[_ALGORITHM],
            issuer=_ISSUER,
            audience=_AUDIENCE,
            options={
                "require": list(_CLAIMS),
                "strict_aud": True,
                "enforce_minimum_key_length": True,
                # Validate times below against the same clock used for issuance.
                "verify_iat": False,
                "verify_nbf": False,
                "verify_exp": False,
            },
        )
        subject = claims["sub"]
        issued, starts, expires = (claims[name] for name in ("iat", "nbf", "exp"))
        if (
            not isinstance(subject, str)
            or not subject.strip()
            or any(type(value) is not int for value in (issued, starts, expires))
            or not 0 <= issued <= starts <= self._clock() < expires
            or expires - issued > self.lifetime
        ):
            raise InvalidTokenError("Invalid access token claims")
        return UserId(subject)
