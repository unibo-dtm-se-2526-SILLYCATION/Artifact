"""Every transactional command against real SQLite, including failure paths."""

from decimal import Decimal

import pytest
from sqlalchemy import Engine, event, select
from sqlalchemy.exc import IntegrityError, OperationalError

from sillycation.adapters.persistence.database import create_database
from sillycation.adapters.persistence.episode_repository import (
    SqlAlchemyEpisodeRepository,
)
from sillycation.adapters.persistence.tables import metadata
from sillycation.adapters.persistence.trip_repository import SqlAlchemyTripRepository
from sillycation.adapters.persistence.user_repository import SqlAlchemyUserRepository
from sillycation.application.ranking_use_cases import GetParticipantRanking
from sillycation.domain.episode import EpisodeStatus
from sillycation.domain.identifiers import (
    EpisodeId,
    JoinRequestId,
    UserId,
    VoteId,
)
from sillycation.domain.trip import JoinRequestStatus, TripStatus
from sillycation.domain.value_objects import InvitationCode
from tests.integration.transactional_support import (
    AUTHOR,
    PROTAGONIST,
    VOTER,
    FIRST,
    SECOND,
    TRIP,
    EPISODE,
    DAY,
    commands_for,
    seed_users,
    seed_trip,
    seed_episode,
)


def snapshot(engine: Engine):
    with engine.connect() as connection:
        return {
            table.name: connection.execute(
                select(table).order_by(*table.primary_key.columns)
            ).all()
            for table in metadata.sorted_tables
        }


def test_all_thirteen_commands_run_in_fresh_transactions_and_survive_restart(
    engine: Engine, database_url: str
) -> None:
    commands = commands_for(engine)
    seed_users(commands)
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)

    def invoke(operation):
        before = len(statements)
        result = operation()
        current = statements[before:]
        assert current.count("BEGIN IMMEDIATE") == 1
        start = current.index("BEGIN IMMEDIATE")
        assert all(statement.startswith("PRAGMA") for statement in current[:start])
        return result

    extra = UserId("extra")
    assert (
        invoke(
            lambda: commands.register_user(
                user_id=extra,
                username="Extra",
                email="extra@example.org",
                password="secret",
            )
        )
        == extra
    )
    trip = invoke(
        lambda: commands.create_trip(
            trip_id=TRIP,
            name="Holiday",
            creator_id=AUTHOR,
            start_date=DAY,
            end_date=DAY,
            invitation_code=InvitationCode("CODE"),
            description="Memo",
        )
    )
    assert trip.status is TripStatus.PLANNED
    for member in (PROTAGONIST, VOTER, SECOND):
        request = JoinRequestId(member.value)
        joined = invoke(
            lambda member=member, request=request: commands.request_join_trip(
                invitation_code=InvitationCode("CODE"),
                request_id=request,
                user_id=member,
            )
        )
        assert joined.status is JoinRequestStatus.PENDING
        if member == SECOND:
            rejected = invoke(
                lambda: commands.reject_join_request(
                    trip_id=TRIP, request_id=request, requested_by=AUTHOR
                )
            )
            assert rejected.status is JoinRequestStatus.REJECTED
        else:
            approved = invoke(
                lambda: commands.approve_join_request(
                    trip_id=TRIP, request_id=request, requested_by=AUTHOR
                )
            )
            assert approved.status is JoinRequestStatus.APPROVED
    assert (
        invoke(
            lambda: commands.activate_trip(
                trip_id=TRIP, requested_by=AUTHOR, current_date=DAY
            )
        ).status
        is TripStatus.ACTIVE
    )
    discarded = EpisodeId("discarded")
    invoke(
        lambda: commands.create_episode(
            episode_id=discarded,
            trip_id=TRIP,
            author_id=AUTHOR,
            protagonist_id=PROTAGONIST,
            title="Draft",
            description="Details",
            date=DAY,
        )
    )
    assert (
        invoke(
            lambda: commands.delete_episode(episode_id=discarded, requested_by=AUTHOR)
        )
        is None
    )
    invoke(
        lambda: commands.create_episode(
            episode_id=EPISODE,
            trip_id=TRIP,
            author_id=AUTHOR,
            protagonist_id=PROTAGONIST,
            title="Original",
            description="Details",
            date=DAY,
        )
    )
    edited = invoke(
        lambda: commands.edit_episode(
            episode_id=EPISODE,
            requested_by=AUTHOR,
            title="Changed",
            description="New",
            date=DAY,
            protagonist_id=PROTAGONIST,
        )
    )
    assert edited.title == "Changed"
    assert (
        invoke(
            lambda: commands.submit_episode(episode_id=EPISODE, requested_by=AUTHOR)
        ).status
        is EpisodeStatus.VOTING
    )
    first = invoke(
        lambda: commands.cast_vote(
            episode_id=EPISODE, vote_id=VoteId("one"), voter_id=AUTHOR, value=5
        )
    )
    assert first.status is EpisodeStatus.VOTING
    final = invoke(
        lambda: commands.cast_vote(
            episode_id=EPISODE, vote_id=VoteId("two"), voter_id=VOTER, value=4
        )
    )
    assert final.status is EpisodeStatus.COMPLETED and final.score == Decimal("4.5")
    assert (
        invoke(
            lambda: commands.complete_trip(
                trip_id=TRIP, requested_by=AUTHOR, current_date=DAY
            )
        ).status
        is TripStatus.COMPLETED
    )
    assert (
        invoke(lambda: commands.archive_trip(trip_id=TRIP, requested_by=AUTHOR)).status
        is TripStatus.ARCHIVED
    )
    event.remove(engine, "before_cursor_execute", record)
    engine.dispose()
    reopened = create_database(database_url)
    try:
        trips = SqlAlchemyTripRepository(reopened)
        episodes = SqlAlchemyEpisodeRepository(reopened)
        users = SqlAlchemyUserRepository(reopened)
        stored_trip = trips.get_by_id(TRIP)
        stored_episode = episodes.get_by_id(EPISODE)
        stored_user = users.get_by_id(extra)
        assert stored_trip is not None and stored_trip.status is TripStatus.ARCHIVED
        assert stored_episode is not None and stored_episode.title == "Changed"
        assert stored_episode.score == Decimal("4.5") and len(stored_episode.votes) == 2
        assert episodes.get_by_id(discarded) is None
        assert (
            stored_user is not None and stored_user.password_hash == "test-hash:secret"
        )
        ranking = GetParticipantRanking(trips, episodes).execute(
            trip_id=TRIP, requested_by=AUTHOR
        )
        assert ranking[0].user_id == PROTAGONIST and ranking[0].score == Decimal("4.5")
        with reopened.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    finally:
        reopened.dispose()


@pytest.mark.parametrize("command", ["register", "create", "approve", "delete"])
def test_failed_commit_never_returns_success_or_leaves_partial_data(
    engine: Engine, command
) -> None:
    commands = commands_for(engine)
    seed_users(commands)
    if command in ("approve", "delete"):
        seed_trip(commands, active=command == "delete")
    if command == "approve":
        commands.request_join_trip(
            invitation_code=InvitationCode("code-trip"),
            request_id=JoinRequestId("pending"),
            user_id=FIRST,
        )
    if command == "delete":
        seed_episode(commands)
    before = snapshot(engine)
    error = OperationalError("COMMIT", {}, RuntimeError("commit failed"))

    def fail(connection):
        raise error

    event.listen(engine, "commit", fail)
    try:
        with pytest.raises(OperationalError) as caught:
            if command == "register":
                commands.register_user(
                    user_id=UserId("extra"),
                    username="Extra",
                    email="extra@example.org",
                    password="secret",
                )
            elif command == "create":
                commands.create_trip(
                    trip_id=TRIP,
                    name="Trip",
                    creator_id=AUTHOR,
                    start_date=DAY,
                    end_date=DAY,
                    invitation_code=InvitationCode("CODE"),
                )
            elif command == "approve":
                commands.approve_join_request(
                    trip_id=TRIP,
                    request_id=JoinRequestId("pending"),
                    requested_by=AUTHOR,
                )
            else:
                commands.delete_episode(episode_id=EPISODE, requested_by=AUTHOR)
        assert caught.value is error
    finally:
        event.remove(engine, "commit", fail)
    assert snapshot(engine) == before
    assert commands.register_user(
        user_id=UserId("recovery"),
        username="Recovery",
        email="recovery@example.org",
        password="secret",
    ) == UserId("recovery")


def test_command_integrity_error_rolls_back_replaced_trip_children(
    engine: Engine,
) -> None:
    commands = commands_for(engine)
    seed_users(commands)
    seed_trip(commands, active=False)
    before = snapshot(engine)
    with pytest.raises(IntegrityError):
        commands.request_join_trip(
            invitation_code=InvitationCode("code-trip"),
            request_id=JoinRequestId("bad-request"),
            user_id=UserId("missing"),
        )
    assert snapshot(engine) == before
    joined = commands.request_join_trip(
        invitation_code=InvitationCode("code-trip"),
        request_id=JoinRequestId("valid-request"),
        user_id=FIRST,
    )
    assert joined.status is JoinRequestStatus.PENDING
