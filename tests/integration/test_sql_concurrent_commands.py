"""Deterministic overlapping commands on distinct real SQLite connections."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event, get_ident, local
from typing import Callable, Optional

import pytest
from sqlalchemy import Engine, event, select
from sqlalchemy.exc import OperationalError

from sillycation.adapters.persistence.episode_repository import (
    SqlAlchemyEpisodeRepository,
)
from sillycation.adapters.persistence.trip_repository import SqlAlchemyTripRepository
from sillycation.adapters.persistence.unit_of_work import SqliteUnitOfWork
from sillycation.adapters.persistence.user_repository import SqlAlchemyUserRepository
from sillycation.adapters.persistence.tables import users
from sillycation.domain.episode import EpisodeStatus
from sillycation.domain.errors import Duplicate, InvalidState, NotFound
from sillycation.domain.identifiers import JoinRequestId, UserId, VoteId
from sillycation.domain.trip import JoinRequestStatus, Participant, TripStatus
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
from tests.integration.test_sql_transactional import snapshot


@dataclass
class Outcome:
    value: object = None
    error: Optional[Exception] = None


def interleave(
    engine: Engine, first: Callable[[], object], second: Callable[[], object]
) -> tuple[Outcome, Outcome]:
    """Pause first at DML; second must attempt BEGIN but cannot read yet."""
    paused, attempted, released, second_read = Event(), Event(), Event(), Event()
    role = local()
    connections: dict[str, set[int]] = {"first": set(), "second": set()}

    def record(connection, cursor, statement, parameters, context, executemany):
        current = getattr(role, "name", None)
        if current is None:
            return
        connections[current].add(id(connection.connection.driver_connection))
        sql = statement.lstrip().upper()
        if (
            current == "first"
            and sql.startswith(("INSERT", "UPDATE", "DELETE"))
            and not paused.is_set()
        ):
            paused.set()
            assert released.wait(timeout=10), "First command was not released"
        if current == "second":
            if sql == "BEGIN IMMEDIATE":
                attempted.set()
            if sql.startswith("SELECT"):
                second_read.set()

    def run(name, operation):
        role.name = name
        try:
            return Outcome(value=operation())
        except Exception as error:
            return Outcome(error=error)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(run, "first", first)
            try:
                assert paused.wait(timeout=10), "First command did not reach its write"
                two = pool.submit(run, "second", second)
                assert attempted.wait(timeout=10), (
                    "Second command did not attempt BEGIN"
                )
                assert not second_read.is_set(), (
                    "Second read happened before first commit"
                )
            finally:
                released.set()
            results = one.result(timeout=15), two.result(timeout=15)
        assert len(connections["first"]) == len(connections["second"]) == 1
        assert connections["first"].isdisjoint(connections["second"])
        assert second_read.is_set()
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        return results
    finally:
        released.set()
        event.remove(engine, "before_cursor_execute", record)


@pytest.fixture
def commands(engine: Engine):
    result = commands_for(engine)
    seed_users(result)
    return result


def test_two_distinct_votes_survive_and_complete_episode(
    engine: Engine, commands
) -> None:
    seed_trip(commands)
    seed_episode(commands, submitted=True)
    one, two = interleave(
        engine,
        lambda: commands.cast_vote(
            episode_id=EPISODE, vote_id=VoteId("one"), voter_id=AUTHOR, value=5
        ),
        lambda: commands.cast_vote(
            episode_id=EPISODE, vote_id=VoteId("two"), voter_id=VOTER, value=4
        ),
    )
    assert one.error is two.error is None
    stored = SqlAlchemyEpisodeRepository(engine).get_by_id(EPISODE)
    assert stored is not None and stored.status is EpisodeStatus.COMPLETED
    assert {vote.voter_id for vote in stored.votes} == {AUTHOR, VOTER}
    assert str(stored.score) == "4.5"


def test_duplicate_concurrent_vote_is_rejected_without_replacing_value(
    engine: Engine, commands
) -> None:
    seed_trip(commands)
    seed_episode(commands, submitted=True)
    one, two = interleave(
        engine,
        lambda: commands.cast_vote(
            episode_id=EPISODE, vote_id=VoteId("one"), voter_id=AUTHOR, value=5
        ),
        lambda: commands.cast_vote(
            episode_id=EPISODE, vote_id=VoteId("two"), voter_id=AUTHOR, value=1
        ),
    )
    assert one.error is None and isinstance(two.error, Duplicate)
    stored = SqlAlchemyEpisodeRepository(engine).get_by_id(EPISODE)
    assert stored is not None and len(stored.votes) == 1
    assert stored.votes[0].value.value == 5
    assert stored.status is EpisodeStatus.VOTING


@pytest.mark.parametrize("same_user", [False, True])
def test_concurrent_join_requests_do_not_replace_existing_requests(
    engine: Engine, commands, same_user
) -> None:
    seed_trip(commands, active=False)
    one, two = interleave(
        engine,
        lambda: commands.request_join_trip(
            invitation_code=InvitationCode("code-trip"),
            request_id=JoinRequestId("one"),
            user_id=FIRST,
        ),
        lambda: commands.request_join_trip(
            invitation_code=InvitationCode("code-trip"),
            request_id=JoinRequestId("two"),
            user_id=FIRST if same_user else SECOND,
        ),
    )
    assert one.error is None
    assert isinstance(two.error, Duplicate) if same_user else two.error is None
    stored = SqlAlchemyTripRepository(engine).get_by_id(TRIP)
    assert stored is not None
    pending = {
        request.id.value
        for request in stored.join_requests
        if request.status is JoinRequestStatus.PENDING
    }
    assert pending == ({"one"} if same_user else {"one", "two"})
    assert {member.user_id for member in stored.participants} == {
        AUTHOR,
        PROTAGONIST,
        VOTER,
    }


def test_concurrent_approvals_preserve_both_memberships_and_decisions(
    engine: Engine, commands
) -> None:
    seed_trip(commands, active=False)
    for request, member in (("one", FIRST), ("two", SECOND)):
        commands.request_join_trip(
            invitation_code=InvitationCode("code-trip"),
            request_id=JoinRequestId(request),
            user_id=member,
        )
    one, two = interleave(
        engine,
        lambda: commands.approve_join_request(
            trip_id=TRIP, request_id=JoinRequestId("one"), requested_by=AUTHOR
        ),
        lambda: commands.approve_join_request(
            trip_id=TRIP, request_id=JoinRequestId("two"), requested_by=AUTHOR
        ),
    )
    assert one.error is two.error is None
    stored = SqlAlchemyTripRepository(engine).get_by_id(TRIP)
    assert stored is not None
    assert {member.user_id for member in stored.participants} == {
        AUTHOR,
        PROTAGONIST,
        VOTER,
        FIRST,
        SECOND,
    }
    assert all(
        stored.get_join_request(JoinRequestId(key)).status is JoinRequestStatus.APPROVED
        for key in ("one", "two")
    )


def test_approval_on_overlapping_trip_commits_existing_use_case_rejection(
    engine: Engine, commands
) -> None:
    seed_trip(commands, members=(), active=False)
    other = seed_trip(
        commands, key="other", creator=PROTAGONIST, members=(), active=False
    )
    for key in ("trip", "other"):
        commands.request_join_trip(
            invitation_code=InvitationCode("code-" + key),
            request_id=JoinRequestId(key),
            user_id=FIRST,
        )
    one, two = interleave(
        engine,
        lambda: commands.approve_join_request(
            trip_id=TRIP, request_id=JoinRequestId("trip"), requested_by=AUTHOR
        ),
        lambda: commands.approve_join_request(
            trip_id=other, request_id=JoinRequestId("other"), requested_by=PROTAGONIST
        ),
    )
    assert one.error is two.error is None
    repository = SqlAlchemyTripRepository(engine)
    first, second = repository.get_by_id(TRIP), repository.get_by_id(other)
    assert first is not None and second is not None
    assert (
        first.get_join_request(JoinRequestId("trip")).status
        is JoinRequestStatus.APPROVED
    )
    assert (
        second.get_join_request(JoinRequestId("other")).status
        is JoinRequestStatus.REJECTED
    )
    assert Participant(other, FIRST) not in second.participants


@pytest.mark.parametrize(
    "first_action,second_action",
    [
        ("edit", "edit"),
        ("edit", "submit"),
        ("submit", "edit"),
        ("edit", "delete"),
        ("delete", "edit"),
        ("submit", "delete"),
        ("delete", "submit"),
    ],
)
def test_draft_commands_recheck_current_state_after_wait(
    engine: Engine, commands, first_action, second_action
) -> None:
    seed_trip(commands)
    seed_episode(commands)

    def operation(action, title):
        if action == "edit":
            return commands.edit_episode(
                episode_id=EPISODE,
                requested_by=AUTHOR,
                title=title,
                description=title,
                date=DAY,
                protagonist_id=PROTAGONIST,
            )
        if action == "submit":
            return commands.submit_episode(episode_id=EPISODE, requested_by=AUTHOR)
        return commands.delete_episode(episode_id=EPISODE, requested_by=AUTHOR)

    one, two = interleave(
        engine,
        lambda: operation(first_action, "First edit"),
        lambda: operation(second_action, "Second edit"),
    )
    assert one.error is None
    if first_action == "delete":
        assert isinstance(two.error, NotFound)
    elif first_action == "submit":
        assert isinstance(two.error, InvalidState)
    else:
        assert two.error is None
    stored = SqlAlchemyEpisodeRepository(engine).get_by_id(EPISODE)
    if (
        first_action == "delete"
        or second_action == "delete"
        and first_action != "submit"
    ):
        assert stored is None
    else:
        assert stored is not None
        assert stored.status is (
            EpisodeStatus.VOTING
            if "submit" in (first_action, second_action)
            else EpisodeStatus.DRAFT
        )
        expected_title = (
            "Original"
            if first_action == "submit"
            else ("Second edit" if second_action == "edit" else "First edit")
        )
        assert stored.title == expected_title


@pytest.mark.parametrize("completion_first", [False, True])
def test_trip_completion_and_episode_creation_cannot_both_succeed(
    engine: Engine, commands, completion_first
) -> None:
    seed_trip(commands)

    def complete():
        return commands.complete_trip(
            trip_id=TRIP, requested_by=AUTHOR, current_date=DAY
        )

    def create():
        return seed_episode(commands)

    one, two = interleave(
        engine,
        complete if completion_first else create,
        create if completion_first else complete,
    )
    assert one.error is None and isinstance(two.error, InvalidState)
    stored_trip = SqlAlchemyTripRepository(engine).get_by_id(TRIP)
    stored_episode = SqlAlchemyEpisodeRepository(engine).get_by_id(EPISODE)
    assert stored_trip is not None
    if completion_first:
        assert stored_trip.status is TripStatus.COMPLETED and stored_episode is None
    else:
        assert stored_trip.status is TripStatus.ACTIVE
        assert (
            stored_episode is not None and stored_episode.status is EpisodeStatus.DRAFT
        )


def test_last_vote_and_completion_observe_same_committed_state(
    engine: Engine, commands
) -> None:
    seed_trip(commands)
    seed_episode(commands, submitted=True)
    commands.cast_vote(
        episode_id=EPISODE, vote_id=VoteId("initial"), voter_id=AUTHOR, value=3
    )
    one, two = interleave(
        engine,
        lambda: commands.cast_vote(
            episode_id=EPISODE, vote_id=VoteId("last"), voter_id=VOTER, value=5
        ),
        lambda: commands.complete_trip(
            trip_id=TRIP, requested_by=AUTHOR, current_date=DAY
        ),
    )
    assert one.error is two.error is None
    stored_trip = SqlAlchemyTripRepository(engine).get_by_id(TRIP)
    stored_episode = SqlAlchemyEpisodeRepository(engine).get_by_id(EPISODE)
    assert stored_trip is not None and stored_trip.status is TripStatus.COMPLETED
    assert (
        stored_episode is not None and stored_episode.status is EpisodeStatus.COMPLETED
    )
    assert str(stored_episode.score) == "4"


@pytest.mark.parametrize("duplicate", ["none", "username", "email", "id"])
def test_concurrent_registrations_preserve_uniqueness_without_overwrite(
    engine: Engine, commands, duplicate
) -> None:
    first_id = UserId("new-first")
    second_id = first_id if duplicate == "id" else UserId("new-second")
    one, two = interleave(
        engine,
        lambda: commands.register_user(
            user_id=first_id,
            username="NewFirst",
            email="new-first@example.org",
            password="first-secret",
        ),
        lambda: commands.register_user(
            user_id=second_id,
            username="NewFirst" if duplicate == "username" else "NewSecond",
            email="new-first@example.org"
            if duplicate == "email"
            else "new-second@example.org",
            password="second-secret",
        ),
    )
    assert one.error is None
    assert (
        two.error is None if duplicate == "none" else isinstance(two.error, Duplicate)
    )
    repository = SqlAlchemyUserRepository(engine)
    stored = repository.get_by_id(first_id)
    assert stored is not None and stored.username == "NewFirst"
    assert (
        stored.email == "new-first@example.org"
        and stored.password_hash == "test-hash:first-secret"
    )
    with engine.connect() as connection:
        assert len(connection.execute(select(users)).all()) == (
            7 if duplicate == "none" else 6
        )


def test_facade_propagates_real_timeout_without_retries_or_partial_writes(
    engine: Engine, commands
) -> None:
    before = snapshot(engine)
    attempted = []
    main_thread = get_ident()
    blocked = commands_for(engine, timeout=0.02)

    def record(connection, cursor, statement, parameters, context, executemany):
        if statement == "BEGIN IMMEDIATE" and get_ident() != main_thread:
            attempted.append(statement)

    def register():
        return blocked.register_user(
            user_id=UserId("late"),
            username="Late",
            email="late@example.org",
            password="secret",
        )

    event.listen(engine, "before_cursor_execute", record)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with SqliteUnitOfWork(engine):
                pending = pool.submit(register)
                with pytest.raises(OperationalError, match="locked"):
                    pending.result(timeout=5)
        assert attempted == ["BEGIN IMMEDIATE"]
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert snapshot(engine) == before
    assert register() == UserId("late")
