from base64 import urlsafe_b64encode
from dataclasses import dataclass
from datetime import date
from secrets import token_urlsafe

from fastapi.testclient import TestClient
import jwt
import pytest
from sqlalchemy import update

from sillycation.adapters.api.app import create_app
from sillycation.adapters.persistence.database import create_database
from sillycation.adapters.persistence.tables import users
from sillycation.adapters.persistence.trip_repository import SqlAlchemyTripRepository
from sillycation.adapters.persistence.user_repository import SqlAlchemyUserRepository
from sillycation.application.trip_use_cases import CreateTrip
from sillycation.domain.identifiers import TripId, UserId
from sillycation.domain.value_objects import InvitationCode


LOGIN = "/api/v1/auth/login"
TRIPS = "/api/v1/trips"
USERS = "/api/v1/users"
PASSWORD = "  caffè 🔑  "
KEY = bytes(range(32))
ENCODED_KEY = urlsafe_b64encode(KEY).decode().rstrip("=")
START_TIME = 1_800_000_000
AUTH_ERROR = {"detail": "Authentication required"}


@dataclass
class Clock:
    now: int = START_TIME

    def __call__(self) -> float:
        return float(self.now)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    monkeypatch.setenv("SILLYCATION_AUTH_ENABLED", "1")
    monkeypatch.setenv("SILLYCATION_AUTH_SECRET", ENCODED_KEY)
    monkeypatch.delenv("SILLYCATION_AUTH_TTL_SECONDS", raising=False)
    return Clock()


def register(client: TestClient, username: str) -> str:
    response = client.post(
        USERS,
        json={
            "username": username,
            "email": f"{username}@example.org",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def login(client: TestClient, username: str, password: str = PASSWORD):
    return client.post(LOGIN, json={"username": username, "password": password})


def bearer(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


def test_real_login_reads_only_own_trips_and_survives_restart(
    clock, tmp_path, caplog
) -> None:
    app = create_app(auth_clock=clock)
    with TestClient(app) as client:
        anna = register(client, "Anna")
        luca = register(client, "Luca")

        engine = create_database(f"sqlite:///{tmp_path / 'api.db'}")
        try:
            command = CreateTrip(
                SqlAlchemyTripRepository(engine), SqlAlchemyUserRepository(engine)
            )
            for actor, name in ((anna, "Anna"), (luca, "Luca")):
                command.execute(
                    trip_id=TripId(name),
                    name=name,
                    creator_id=UserId(actor),
                    start_date=date(2026, 11, 27),
                    end_date=date(2026, 11, 28),
                    invitation_code=InvitationCode(f"code-{name}"),
                )
        finally:
            engine.dispose()

        response = login(client, "Anna")
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        token = response.json()["access_token"]
        assert response.json() == {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": 900,
        }
        assert PASSWORD not in response.text
        assert "$argon2id$" not in response.text
        assert ENCODED_KEY not in response.text
        protected = client.get(
            TRIPS,
            params={"user_id": luca, "actor": luca},
            headers={**bearer(token), "X-User-ID": luca},
        )
        assert protected.status_code == 200
        assert [trip["id"] for trip in protected.json()] == ["Anna"]
        assert client.get(TRIPS, headers={"X-User-ID": anna}).status_code == 401
        assert (
            client.get(TRIPS + "/Anna/dashboard", headers=bearer(token)).status_code
            == 404
        )
        assert client.post(TRIPS, headers=bearer(token)).status_code == 405

    with TestClient(create_app(auth_clock=clock)) as client:
        assert [
            trip["id"] for trip in client.get(TRIPS, headers=bearer(token)).json()
        ] == ["Anna"]
        assert login(client, "Anna").status_code == 200
    for secret in (token, PASSWORD, ENCODED_KEY, "$argon2id$"):
        assert secret not in caplog.text


def test_bad_password_and_unknown_user_are_uniform(clock, monkeypatch) -> None:
    from sillycation.adapters.passwords import Argon2PasswordHasher

    real_verify = Argon2PasswordHasher.verify
    verifications = []

    def track(self, password, password_hash):
        verifications.append(password_hash)
        return real_verify(self, password, password_hash)

    monkeypatch.setattr(Argon2PasswordHasher, "verify", track)
    with TestClient(create_app(auth_clock=clock)) as client:
        register(client, "Anna")
        for username in ("Anna", "Unknown"):
            response = login(client, username, PASSWORD.strip())
            assert response.status_code == 401
            assert response.json() == AUTH_ERROR
            assert response.headers["WWW-Authenticate"] == "Bearer"
            assert response.headers["Cache-Control"] == "no-store"
    assert len(verifications) == 2
    assert verifications[0] != verifications[1]


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("sub", None),
        ("sub", 12),
        ("sub", " "),
        ("sub", "missing-user"),
        ("exp", None),
        ("exp", START_TIME),
        ("exp", str(START_TIME + 900)),
        ("exp", START_TIME + 901),
        ("iat", None),
        ("iat", True),
        ("iat", START_TIME + 1),
        ("nbf", None),
        ("nbf", START_TIME + 1),
        ("iss", None),
        ("iss", "other"),
        ("aud", None),
        ("aud", "other"),
        ("aud", ["sillycation-api"]),
    ],
)
def test_signed_token_with_bad_claims_is_rejected(clock, claim, value) -> None:
    with TestClient(create_app(auth_clock=clock)) as client:
        actor = register(client, "Anna")
        claims = {
            "iss": "sillycation",
            "aud": "sillycation-api",
            "sub": actor,
            "iat": START_TIME,
            "nbf": START_TIME,
            "exp": START_TIME + 900,
        }
        if value is None:
            del claims[claim]
        else:
            claims[claim] = value
        token = jwt.encode(claims, KEY, algorithm="HS256")
        response = client.get(TRIPS, headers=bearer(token))
        assert response.status_code == 401
        assert response.json() == AUTH_ERROR
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_signature_algorithm_expiration_and_header(clock, monkeypatch) -> None:
    monkeypatch.setenv("SILLYCATION_AUTH_TTL_SECONDS", "30")
    with TestClient(create_app(auth_clock=clock)) as client:
        register(client, "Anna")
        issued = login(client, "Anna")
        assert issued.json()["expires_in"] == 30
        token = issued.json()["access_token"]
        claims = jwt.decode(
            token,
            KEY,
            algorithms=["HS256"],
            options={
                "verify_aud": False,
                "verify_iat": False,
                "verify_nbf": False,
                "verify_exp": False,
            },
        )
        header, payload, signature = token.split(".")
        changed = ("A" if signature[0] != "A" else "B") + signature[1:]
        unsigned = jwt.encode(claims, "", algorithm="none")
        assert jwt.get_unverified_header(unsigned)["alg"] == "none"
        assert unsigned.split(".")[2] == ""
        for headers in (
            {},
            {"Authorization": f"Basic {token}"},
            bearer(f"{header}.{payload}.{changed}"),
            bearer(jwt.encode(claims, b"z" * 32, algorithm="HS256")),
            bearer(jwt.encode(claims, b"z" * 64, algorithm="HS512")),
            bearer(unsigned),
            bearer("not-a-token"),
        ):
            response = client.get(TRIPS, headers=headers)
            assert response.status_code == 401
            assert response.headers["WWW-Authenticate"] == "Bearer"
            assert response.json() == AUTH_ERROR
        duplicate_headers = [
            ("Authorization", "Bearer invalid"),
            ("Authorization", f"Bearer {token}"),
        ]
        assert client.get(TRIPS, headers=duplicate_headers).status_code == 401
        clock.now += 29
        assert client.get(TRIPS, headers=bearer(token)).status_code == 200
        clock.now += 1
        assert client.get(TRIPS, headers=bearer(token)).status_code == 401


def test_login_budget_is_shared_across_apps_and_ignores_forwarded_headers(
    clock,
) -> None:
    with (
        TestClient(create_app(auth_clock=clock)) as first,
        TestClient(create_app(auth_clock=clock)) as second,
    ):
        register(first, "Anna")
        for index in range(10):
            client = first if index % 2 == 0 else second
            response = client.post(
                LOGIN,
                json={
                    "username": "Anna" if index % 2 else "Unknown",
                    "password": "wrong",
                },
                headers={"X-Forwarded-For": f"198.51.100.{index + 1}"},
            )
            assert response.status_code == 401
        blocked = login(second, "Anna")
        assert blocked.status_code == 429
        assert blocked.headers["Retry-After"] == "60"
        assert blocked.headers["Cache-Control"] == "no-store"

    with TestClient(create_app(auth_clock=clock)) as restarted:
        assert login(restarted, "Anna").status_code == 429
        clock.now += 60
        assert login(restarted, "Anna").status_code == 200


def test_validation_errors_and_broken_hash_do_not_disclose_credentials(
    clock, tmp_path, caplog
) -> None:
    with TestClient(create_app(auth_clock=clock)) as client:
        register(client, "Anna")
        invalid = client.post(
            LOGIN,
            json={
                "username": "Anna",
                "password": {"value": PASSWORD},
                PASSWORD: "secret",
            },
        )
        assert invalid.status_code == 422
        assert invalid.headers["Cache-Control"] == "no-store"
        assert PASSWORD not in invalid.text
        assert all(
            set(item) == {"loc", "msg", "type"} for item in invalid.json()["detail"]
        )
        engine = create_database(f"sqlite:///{tmp_path / 'api.db'}")
        try:
            with engine.begin() as connection:
                connection.execute(
                    update(users).values(password_hash="SECRET-BROKEN-HASH")
                )
        finally:
            engine.dispose()
        response = login(client, "Anna")
        assert response.status_code == 500
        assert response.text == "Internal Server Error"
    assert "SECRET-BROKEN-HASH" not in caplog.text
    assert PASSWORD not in caplog.text
    assert ENCODED_KEY not in caplog.text


@pytest.mark.parametrize("secret", [None, "invalid-secret", "A" * 43])
def test_enabled_auth_requires_strong_secret(clock, monkeypatch, secret) -> None:
    if secret is None:
        monkeypatch.delenv("SILLYCATION_AUTH_SECRET")
    else:
        monkeypatch.setenv("SILLYCATION_AUTH_SECRET", secret)
    with pytest.raises(ValueError, match="SILLYCATION_AUTH_SECRET") as exc:
        with TestClient(create_app(auth_clock=clock)):
            pytest.fail("Invalid configuration passed startup")
    if secret:
        assert secret not in str(exc.value)


def test_invalid_ttl_fails_startup(clock, monkeypatch) -> None:
    monkeypatch.setenv("SILLYCATION_AUTH_SECRET", token_urlsafe(32))
    monkeypatch.setenv("SILLYCATION_AUTH_TTL_SECONDS", "86400")
    with pytest.raises(ValueError, match="SILLYCATION_AUTH_TTL_SECONDS"):
        with TestClient(create_app(auth_clock=clock)):
            pytest.fail("Invalid configuration passed startup")


def test_openapi_public_authentication_contract(clock) -> None:
    schema = create_app(auth_clock=clock).openapi()
    assert set(schema["paths"]) == {USERS, LOGIN, TRIPS}
    assert set(schema["paths"][TRIPS]) == {"get"}
    read = schema["paths"][TRIPS]["get"]
    assert read["security"] == [{"HTTPBearer": []}]
    assert "WWW-Authenticate" in read["responses"]["401"]["headers"]
    login_operation = schema["paths"][LOGIN]["post"]
    assert not login_operation.get("security")
    assert {"200", "401", "422", "429"} <= set(login_operation["responses"])
    assert schema["components"]["securitySchemes"]["HTTPBearer"] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }
