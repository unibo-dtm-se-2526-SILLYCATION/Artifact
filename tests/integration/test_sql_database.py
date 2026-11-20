"""Real SQLite constraints and atomic updates across referenced aggregates."""

from datetime import date
from unittest.mock import Mock

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.exc import IntegrityError

from sillycation.adapters.persistence.database import (
    _enable_sqlite_foreign_keys,
    create_database,
)
from sillycation.adapters.persistence.episode_repository import (
    SqlAlchemyEpisodeRepository,
)
from sillycation.adapters.persistence.trip_repository import SqlAlchemyTripRepository
from sillycation.adapters.persistence.user_repository import SqlAlchemyUserRepository
from sillycation.adapters.persistence.tables import (
    episodes,
    join_requests,
    metadata,
    participants,
    trips,
    votes,
)
from sillycation.domain.episode import Episode
from sillycation.domain.identifiers import (
    EpisodeId,
    JoinRequestId,
    TripId,
    UserId,
    VoteId,
)
from sillycation.domain.trip import Trip, TripStatus
from sillycation.domain.user import User
from sillycation.domain.value_objects import InvitationCode, TripPeriod, VoteValue

DAY = date(2026, 11, 10)
AUTHOR, PROTAGONIST, VOTER, APPLICANT = [
    UserId(key) for key in ("author", "protagonist", "voter", "applicant")
]


@pytest.fixture
def graph(engine: Engine):
    user_repository = SqlAlchemyUserRepository(engine)
    for identity in (AUTHOR, PROTAGONIST, VOTER, APPLICANT):
        user_repository.save(
            User(identity, identity.value, identity.value + "@example.org", "hash")
        )
    trip = Trip(
        TripId("trip"), "Holiday", AUTHOR, TripPeriod(DAY, DAY), InvitationCode("CODE")
    )
    for member in (PROTAGONIST, VOTER):
        request = JoinRequestId(member.value)
        trip.request_to_join(request, member)
        trip.approve_join_request(request, requested_by=AUTHOR)
    trip.request_to_join(JoinRequestId("pending"), APPLICANT)
    trip.activate(requested_by=AUTHOR, current_date=DAY)
    trip_repository = SqlAlchemyTripRepository(engine)
    trip_repository.save(trip)
    episode = Episode(
        EpisodeId("episode"), trip.id, AUTHOR, PROTAGONIST, "Title", "Details", DAY
    )
    episode.submit(requested_by=AUTHOR, trip_status=trip.status)
    for identity in (AUTHOR, VOTER):
        episode.cast_vote(
            VoteId(identity.value),
            identity,
            VoteValue(4),
            eligible_voters={AUTHOR, VOTER},
            trip_status=trip.status,
        )
    episode_repository = SqlAlchemyEpisodeRepository(engine)
    episode_repository.save(episode)
    return user_repository, trip_repository, episode_repository, trip, episode


def snapshot(engine: Engine):
    with engine.connect() as connection:
        return {
            table.name: connection.execute(
                select(table).order_by(*table.primary_key.columns)
            ).all()
            for table in metadata.sorted_tables
        }


def assert_integrity(engine: Engine) -> None:
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []


def test_foreign_keys_on_distinct_connections_and_after_reopen(
    database_url: str,
) -> None:
    engine = create_database(database_url)
    try:
        # Holding both connections proves this checks two physical connections.
        with engine.connect() as first, engine.connect() as second:
            assert (
                first.connection.driver_connection
                is not second.connection.driver_connection
            )
            for connection in (first, second):
                assert (
                    connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
                )
        engine.dispose()
        assert_integrity(engine)
    finally:
        engine.dispose()
    reopened = create_database(database_url)
    try:
        assert_integrity(reopened)
    finally:
        reopened.dispose()


def test_foreign_keys_on_in_memory_database() -> None:
    engine = create_database("sqlite:///:memory:")
    try:
        assert_integrity(engine)
    finally:
        engine.dispose()


@pytest.mark.parametrize("autocommit", [False, True, -1])
@pytest.mark.parametrize("fail", [False, True])
def test_listener_restores_autocommit_and_closes_cursor(autocommit, fail) -> None:
    connection = Mock()
    connection.autocommit = autocommit
    cursor = connection.cursor.return_value
    observed = []

    def execute(statement):
        observed.append(connection.autocommit)
        if fail:
            raise RuntimeError("driver failure")

    cursor.execute.side_effect = execute
    if fail:
        with pytest.raises(RuntimeError, match="driver failure"):
            _enable_sqlite_foreign_keys(connection, None)
    else:
        _enable_sqlite_foreign_keys(connection, None)
    assert observed == [True]
    assert connection.autocommit == autocommit
    cursor.close.assert_called_once_with()


@pytest.mark.parametrize(
    "table,column",
    [
        (trips, "creator_id"),
        (participants, "trip_id"),
        (participants, "user_id"),
        (join_requests, "trip_id"),
        (join_requests, "user_id"),
        (episodes, "trip_id"),
        (episodes, "author_id"),
        (episodes, "protagonist_id"),
        (votes, "episode_id"),
        (votes, "voter_id"),
    ],
    ids=[
        "trip-creator",
        "participant-trip",
        "participant-user",
        "request-trip",
        "request-user",
        "episode-trip",
        "episode-author",
        "episode-protagonist",
        "vote-episode",
        "vote-user",
    ],
)
def test_each_foreign_key_rejects_missing_parent(
    engine: Engine, graph, table, column
) -> None:
    before = snapshot(engine)
    with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
        with engine.begin() as connection:
            row = connection.execute(select(table)).mappings().first()
            assert row is not None
            condition = [key == row[key.name] for key in table.primary_key.columns]
            connection.execute(
                update(table).where(*condition).values({column: "missing"})
            )
    assert snapshot(engine) == before
    assert_integrity(engine)


def test_updating_referenced_users_preserves_all_relations(
    engine: Engine, graph
) -> None:
    repository, _, _, _, _ = graph
    before = snapshot(engine)
    for identity in (AUTHOR, PROTAGONIST, VOTER, APPLICANT):
        changed = User(
            identity,
            "new-" + identity.value,
            "new-" + identity.value + "@example.org",
            "new-hash",
        )
        assert repository.save(changed) is changed
        loaded = repository.get_by_id(identity)
        assert loaded is not None
        assert (loaded.username, loaded.email, loaded.password_hash) == (
            changed.username,
            changed.email,
            changed.password_hash,
        )
    after = snapshot(engine)
    assert {key: value for key, value in after.items() if key != "users"} == {
        key: value for key, value in before.items() if key != "users"
    }
    assert_integrity(engine)


def test_updating_trip_preserves_episodes_votes_and_membership(
    engine: Engine, graph
) -> None:
    _, repository, episode_repository, trip, episode = graph
    before = snapshot(engine)
    trip.complete(requested_by=AUTHOR, current_date=DAY, has_unresolved_episodes=False)
    repository.save(trip)
    trip.archive(requested_by=AUTHOR)
    repository.save(trip)
    loaded = repository.get_by_id(trip.id)
    assert loaded is not None and loaded.status is TripStatus.ARCHIVED
    assert loaded.participants == trip.participants
    assert set(loaded.join_requests) == set(trip.join_requests)
    after = snapshot(engine)
    for name in ("episodes", "votes", "participants", "join_requests"):
        assert after[name] == before[name]
    loaded_episode = episode_repository.get_by_id(episode.id)
    assert loaded_episode is not None
    assert set(loaded_episode.votes) == set(episode.votes)
    assert loaded_episode.score == episode.score
    assert_integrity(engine)


def test_failed_user_update_rolls_back_without_losing_references(
    engine: Engine, graph
) -> None:
    repository, _, _, _, _ = graph
    before = snapshot(engine)
    with pytest.raises(IntegrityError):
        repository.save(
            User(AUTHOR, PROTAGONIST.value, "changed@example.org", "changed-hash")
        )
    assert snapshot(engine) == before
    assert_integrity(engine)


@pytest.mark.parametrize("new", [False, True])
def test_failed_child_insert_rolls_back_trip_and_owned_rows(
    engine: Engine, graph, new
) -> None:
    _, repository, _, trip, _ = graph
    before = snapshot(engine)
    replacement = Trip(
        TripId("new-trip") if new else trip.id,
        "Changed",
        AUTHOR,
        trip.period,
        InvitationCode("NEW") if new else trip.invitation_code,
    )
    replacement.request_to_join(JoinRequestId("bad-request"), UserId("missing"))
    with pytest.raises(IntegrityError):
        repository.save(replacement)
    assert snapshot(engine) == before
    assert_integrity(engine)


@pytest.mark.parametrize("new", [False, True])
def test_failed_vote_insert_restores_episode_and_all_previous_votes(
    engine: Engine, graph, new
) -> None:
    _, _, repository, trip, episode = graph
    before = snapshot(engine)
    replacement = Episode(
        EpisodeId("new-episode") if new else episode.id,
        trip.id,
        AUTHOR,
        PROTAGONIST,
        "Changed",
        "Changed",
        DAY,
    )
    replacement.submit(requested_by=AUTHOR, trip_status=trip.status)
    missing = UserId("missing")
    for identity in (AUTHOR, missing):
        replacement.cast_vote(
            VoteId("new-" + identity.value),
            identity,
            VoteValue(5),
            eligible_voters={AUTHOR, missing},
            trip_status=trip.status,
        )
    with pytest.raises(IntegrityError):
        repository.save(replacement)
    assert snapshot(engine) == before
    assert_integrity(engine)


def test_deleting_episode_removes_owned_votes_and_preserves_other_data(
    engine: Engine, graph
) -> None:
    _, _, repository, _, episode = graph
    before = snapshot(engine)
    repository.delete(episode.id)
    after = snapshot(engine)
    assert after["episodes"] == after["votes"] == []
    for name in ("users", "trips", "participants", "join_requests"):
        assert after[name] == before[name]
    assert_integrity(engine)
