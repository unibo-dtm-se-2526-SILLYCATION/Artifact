"""Public trip workflows through real JWT authentication and SQLite."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import Engine, event

from sillycation.adapters.api.app import create_app
from tests.integration.api.test_http_authentication import (
    TRIPS,
    bearer,
    clock as clock,
    login,
    register,
)


JOIN = "/api/v1/join-requests"
TRIP_DAY = "2000-01-01"


def credentials(client, username):
    user_id = register(client, username)
    response = login(client, username)
    assert response.status_code == 200
    return user_id, bearer(response.json()["access_token"])


def create_trip(client, headers):
    response = client.post(
        TRIPS,
        headers=headers,
        json={"name": "Roma", "start_date": TRIP_DAY, "end_date": TRIP_DAY},
    )
    assert response.status_code == 201
    body = response.json()
    assert UUID(body["id"]).version == 4
    assert body["status"] == "PLANNED"
    assert "invitation_code" not in body
    path = f"{TRIPS}/{body['id']}"
    invitation = client.get(f"{path}/invitation-code", headers=headers)
    assert invitation.status_code == 200
    return body, path, invitation.json()["invitation_code"]


def request_join(client, headers, code):
    response = client.post(JOIN, json={"invitation_code": code}, headers=headers)
    assert response.status_code == 201
    request = response.json()
    assert UUID(request["id"]).version == 4
    assert request["status"] == "PENDING"
    return request


def test_trip_lifecycle_permissions_and_persistence(clock) -> None:
    with TestClient(create_app(auth_clock=clock)) as client:
        owner_id, owner = credentials(client, "owner")
        member_id, member = credentials(client, "member")
        outsider_id, outsider = credentials(client, "outsider")
        trip, path, code = create_trip(client, owner)
        assert trip["creator_id"] == owner_id
        assert client.get(TRIPS).status_code == 401
        assert client.get(TRIPS, headers=member).json() == []
        for suffix in ("invitation-code", "join-requests", "participants"):
            assert client.get(f"{path}/{suffix}", headers=outsider).status_code == 403

        pending = request_join(client, member, code)
        declined = request_join(client, outsider, code)
        assert pending["user_id"] == member_id and declined["user_id"] == outsider_id
        approval = f"{path}/join-requests/{pending['id']}/approve"
        rejection = f"{path}/join-requests/{declined['id']}/reject"
        assert client.post(approval).status_code == 401
        queue = client.get(f"{path}/join-requests", headers=owner)
        assert queue.status_code == 200
        assert {item["id"] for item in queue.json()} == {pending["id"], declined["id"]}
        assert (
            client.post(approval, headers={**member, "X-User-ID": owner_id}).status_code
            == 403
        )
        assert client.post(rejection, headers=outsider).status_code == 403
        assert client.post(approval, headers=owner).json()["status"] == "APPROVED"
        assert client.post(rejection, headers=owner).json()["status"] == "REJECTED"
        assert client.get(f"{path}/join-requests", headers=owner).json() == []
        assert client.get(f"{path}/invitation-code", headers=member).status_code == 403
        assert client.get(f"{path}/join-requests", headers=member).status_code == 403
        participants = client.get(f"{path}/participants", headers=member)
        assert participants.status_code == 200
        assert {item["user_id"] for item in participants.json()} == {
            owner_id,
            member_id,
        }
        assert [item["id"] for item in client.get(TRIPS, headers=member).json()] == [
            trip["id"]
        ]
        assert client.get(TRIPS, headers=outsider).json() == []

        for operation, expected in (
            ("activate", "ACTIVE"),
            ("complete", "COMPLETED"),
            ("archive", "ARCHIVED"),
        ):
            assert client.post(f"{path}/{operation}", headers=member).status_code == 403
            response = client.post(f"{path}/{operation}", headers=owner)
            assert response.status_code == 200
            assert response.json()["status"] == expected

    with TestClient(create_app(auth_clock=clock)) as client:
        assert client.get(TRIPS, headers=member).json() == []
        archived = client.get(TRIPS, headers=member, params={"archived": True})
        assert [(item["id"], item["status"]) for item in archived.json()] == [
            (trip["id"], "ARCHIVED")
        ]
        assert (
            client.get(TRIPS, headers=outsider, params={"archived": True}).json() == []
        )
        assert client.get(f"{path}/invitation-code", headers=owner).json() == {
            "invitation_code": code
        }


def test_trip_write_commit_failure_rolls_back(clock, tmp_path) -> None:
    with TestClient(
        create_app(auth_clock=clock), raise_server_exceptions=False
    ) as client:
        _, owner = credentials(client, "owner")
        _, member = credentials(client, "member")
        _, path, code = create_trip(client, owner)
        pending = request_join(client, member, code)
        approval = f"{path}/join-requests/{pending['id']}/approve"

        def fail_commit(connection):
            if connection.engine.url.database == str(tmp_path / "api.db"):
                raise RuntimeError("Injected commit failure")

        event.listen(Engine, "commit", fail_commit)
        try:
            failed = client.post(approval, headers=owner)
        finally:
            event.remove(Engine, "commit", fail_commit)
        assert failed.status_code == 500
        assert failed.text == "Internal Server Error"
        assert client.get(f"{path}/join-requests", headers=owner).json() == [pending]
        assert client.get(TRIPS, headers=member).json() == []
        assert client.post(approval, headers=owner).json()["status"] == "APPROVED"


def test_concurrent_join_requests_both_survive(clock, tmp_path) -> None:
    with TestClient(create_app(auth_clock=clock)) as client:
        _, owner = credentials(client, "owner")
        first_id, first = credentials(client, "first")
        second_id, second = credentials(client, "second")
        _, path, code = create_trip(client, owner)
        writing, second_begin, release = Event(), Event(), Event()

        def observe(connection, cursor, statement, parameters, context, executemany):
            if connection.engine.url.database != str(tmp_path / "api.db"):
                return
            if statement.startswith("UPDATE trips") and not writing.is_set():
                writing.set()
                assert release.wait(10), "First writer was not released"
            elif statement == "BEGIN IMMEDIATE" and writing.is_set():
                second_begin.set()

        event.listen(Engine, "before_cursor_execute", observe)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                one = pool.submit(request_join, client, first, code)
                try:
                    assert writing.wait(10)
                    two = pool.submit(request_join, client, second, code)
                    assert second_begin.wait(10)
                finally:
                    release.set()
                assert one.result(15)["user_id"] == first_id
                assert two.result(15)["user_id"] == second_id
        finally:
            event.remove(Engine, "before_cursor_execute", observe)

        stored = client.get(f"{path}/join-requests", headers=owner)
        assert stored.status_code == 200
        assert {item["user_id"] for item in stored.json()} == {first_id, second_id}


def test_public_openapi_exposes_only_trip_operations_and_authentication(clock) -> None:
    paths = create_app(auth_clock=clock).openapi()["paths"]
    expected = {
        "/api/v1/users": {"post"},
        "/api/v1/auth/login": {"post"},
        TRIPS: {"get", "post"},
        JOIN: {"post"},
        f"{TRIPS}/{{trip_id}}/invitation-code": {"get"},
        f"{TRIPS}/{{trip_id}}/join-requests": {"get"},
        f"{TRIPS}/{{trip_id}}/participants": {"get"},
        f"{TRIPS}/{{trip_id}}/join-requests/{{request_id}}/approve": {"post"},
        f"{TRIPS}/{{trip_id}}/join-requests/{{request_id}}/reject": {"post"},
        **{
            f"{TRIPS}/{{trip_id}}/{action}": {"post"}
            for action in ("activate", "complete", "archive")
        },
    }
    assert {path: set(operations) for path, operations in paths.items()} == expected
    for path, methods in paths.items():
        if path in ("/api/v1/users", "/api/v1/auth/login"):
            continue
        for operation in methods.values():
            assert operation["security"] == [{"HTTPBearer": []}]
            assert "WWW-Authenticate" in operation["responses"]["401"]["headers"]
