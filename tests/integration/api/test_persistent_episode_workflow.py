"""Exercise the full game through the public ASGI app and a SQLite file."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event

from fastapi.testclient import TestClient
from sqlalchemy import Engine, event

from sillycation.adapters.api.app import create_app
from tests.integration.api.test_http_authentication import TRIPS, bearer, clock as clock
from tests.integration.api.test_persistent_trip_workflow import (
    TRIP_DAY,
    create_trip,
    credentials,
    request_join,
)


def active_trip(client):
    anna_id, anna = credentials(client, "anna")
    luca_id, luca = credentials(client, "luca")
    sara_id, sara = credentials(client, "sara")
    _, trip, code = create_trip(client, anna)
    for actor in (luca, sara):
        request = request_join(client, actor, code)
        approved = client.post(
            f"{trip}/join-requests/{request['id']}/approve", headers=anna
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "APPROVED"
    activated = client.post(f"{trip}/activate", headers=anna)
    assert activated.status_code == 200
    assert activated.json()["status"] == "ACTIVE"
    return trip, (anna_id, anna), (luca_id, luca), (sara_id, sara)


def draft(client, trip, author, protagonist):
    body = {
        "title": "Lost passport",
        "description": "Left at the hotel",
        "date": TRIP_DAY,
        "protagonist_id": protagonist,
    }
    created = client.post(f"{trip}/episodes", headers=author, json=body)
    assert created.status_code == 201
    assert created.json()["status"] == "DRAFT"
    return body, f"/api/v1/episodes/{created.json()['id']}"


def assert_final_results(client, trip, episode, headers, expected_rank):
    episodes = client.get(f"{trip}/episodes", headers=headers)
    assert episodes.status_code == 200
    (stored,) = episodes.json()
    assert episode.endswith("/" + stored["id"])
    assert stored["status"] == "COMPLETED"
    assert Decimal(stored["score"]) == Decimal("4.5")
    ranking = client.get(f"{trip}/ranking", headers=headers)
    assert ranking.status_code == 200
    assert [
        (row["user_id"], Decimal(row["score"]), row["position"])
        for row in ranking.json()
    ] == expected_rank
    trips = client.get(TRIPS, headers=headers)
    assert trips.status_code == 200
    assert [(row["id"], row["status"]) for row in trips.json()] == [
        (trip.rsplit("/", 1)[-1], "COMPLETED")
    ]


def test_complete_public_vertical_slice_survives_restart(clock) -> None:
    with TestClient(create_app(auth_clock=clock)) as client:
        trip, (anna_id, anna), (luca_id, luca), (sara_id, sara) = active_trip(client)
        _, discarded = draft(client, trip, anna, luca_id)
        removed = client.delete(discarded, headers=anna)
        assert removed.status_code == 204 and removed.content == b""
        body, episode = draft(client, trip, anna, luca_id)
        updated = client.put(
            episode, headers=anna, json={**body, "title": "Passport at the hotel"}
        )
        assert updated.status_code == 200
        assert updated.json()["title"] == "Passport at the hotel"
        assert client.get(f"{trip}/episodes", headers=luca).json() == []
        assert len(client.get(f"{trip}/episodes", headers=anna).json()) == 1
        submitted = client.post(f"{episode}/submit", headers=anna)
        assert submitted.status_code == 200 and submitted.json()["status"] == "VOTING"
        for voter, value, status in ((anna, 5, "VOTING"), (sara, 4, "COMPLETED")):
            vote = client.post(f"{episode}/votes", headers=voter, json={"value": value})
            assert vote.status_code == 201 and vote.json()["status"] == status
        completed = client.post(f"{trip}/complete", headers=anna)
        assert (
            completed.status_code == 200 and completed.json()["status"] == "COMPLETED"
        )
        expected_rank = [
            (luca_id, Decimal("4.5"), 1),
            *[(identity, Decimal("0"), 2) for identity in sorted((anna_id, sara_id))],
        ]
        assert_final_results(client, trip, episode, sara, expected_rank)

    with TestClient(create_app(auth_clock=clock)) as restarted:
        assert_final_results(restarted, trip, episode, sara, expected_rank)


def test_public_episode_and_vote_permissions_and_safe_errors(clock) -> None:
    with TestClient(create_app(auth_clock=clock)) as client:
        trip, (_, anna), (luca_id, luca), (_, sara) = active_trip(client)
        _, outsider = credentials(client, "outsider")
        body, episode = draft(client, trip, anna, luca_id)
        votes = f"{episode}/votes"
        for headers in ({}, bearer("INVALID_PRIVATE_TOKEN")):
            for path in (f"{trip}/episodes", f"{trip}/ranking"):
                response = client.get(path, headers=headers)
                assert response.status_code == 401
                assert response.headers["WWW-Authenticate"] == "Bearer"
                assert "INVALID_PRIVATE_TOKEN" not in response.text
            assert (
                client.post(votes, headers=headers, json={"value": 5}).status_code
                == 401
            )
        for path in (f"{trip}/episodes", f"{trip}/ranking"):
            assert client.get(path, headers=outsider).status_code == 403
        assert client.put(episode, headers=luca, json=body).status_code == 403
        assert client.delete(episode, headers=luca).status_code == 403
        assert client.post(f"{episode}/submit", headers=luca).status_code == 403
        assert client.post(votes, headers=anna, json={"value": 5}).status_code == 409
        assert client.post(f"{episode}/submit", headers=anna).status_code == 200
        assert client.post(votes, headers=luca, json={"value": 5}).status_code == 403
        assert (
            client.post(votes, headers=outsider, json={"value": 5}).status_code == 403
        )
        for value in ("SECRET_PASSWORD", anna["Authorization"]):
            response = client.post(votes, headers=sara, json={"value": value})
            assert response.status_code == 422
            assert value not in response.text
        assert client.post(votes, headers=anna, json={"value": 5}).status_code == 201
        duplicate = client.post(votes, headers=anna, json={"value": 4})
        assert (
            duplicate.status_code == 409
            and duplicate.json()["error"]["code"] == "duplicate"
        )


def test_vote_commit_rollback_and_concurrent_votes(clock, tmp_path, caplog) -> None:
    database = str(tmp_path / "api.db")
    with TestClient(create_app(auth_clock=clock)) as client:
        trip, (_, anna), (luca_id, _), (_, sara) = active_trip(client)
        _, episode = draft(client, trip, anna, luca_id)
        assert client.post(f"{episode}/submit", headers=anna).status_code == 200
        votes = f"{episode}/votes"

        def fail_commit(connection):
            if connection.engine.url.database == database:
                raise RuntimeError("PRIVATE_SQL_PARAMETERS")

        event.listen(Engine, "commit", fail_commit)
        try:
            rejected = client.post(votes, headers=anna, json={"value": 1})
        finally:
            event.remove(Engine, "commit", fail_commit)
        assert rejected.status_code == 500
        assert rejected.text == "Internal Server Error"
        assert "PRIVATE_SQL_PARAMETERS" not in caplog.text
        assert client.get(f"{trip}/episodes", headers=anna).json()[0]["score"] is None

        writing, second_begin, release = Event(), Event(), Event()

        def observe(connection, cursor, statement, parameters, context, executemany):
            if connection.engine.url.database != database:
                return
            if statement.startswith("DELETE FROM votes") and not writing.is_set():
                writing.set()
                assert release.wait(10), "First voter was not released"
            elif statement == "BEGIN IMMEDIATE" and writing.is_set():
                second_begin.set()

        def record(voter, value):
            return client.post(votes, headers=voter, json={"value": value})

        event.listen(Engine, "before_cursor_execute", observe)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(record, anna, 5)
                try:
                    assert writing.wait(10)
                    second = pool.submit(record, sara, 4)
                    assert second_begin.wait(10)
                finally:
                    release.set()
                one, two = first.result(15), second.result(15)
        finally:
            event.remove(Engine, "before_cursor_execute", observe)
        assert one.status_code == two.status_code == 201
        assert one.json()["status"] == "VOTING"
        assert two.json()["status"] == "COMPLETED"

    with TestClient(create_app(auth_clock=clock)) as restarted:
        (stored,) = restarted.get(f"{trip}/episodes", headers=sara).json()
        assert stored["status"] == "COMPLETED"
        assert Decimal(stored["score"]) == Decimal("4.5")
