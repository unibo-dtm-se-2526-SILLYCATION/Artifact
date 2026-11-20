"""Delegation and transaction semantics, without pretending fakes prove locking."""

from copy import deepcopy
from datetime import date
from types import TracebackType
from typing import Optional
from unittest.mock import Mock, patch, sentinel

import pytest

from sillycation.application.ports.passwords import PasswordHasher
from sillycation.application.ports.repositories import (
    EpisodeRepository,
    TripRepository,
    UserRepository,
)
from sillycation.application.ports.unit_of_work import UnitOfWork
from sillycation.application.transactional import TransactionalCommands
from sillycation.domain.identifiers import (
    EpisodeId,
    JoinRequestId,
    TripId,
    UserId,
    VoteId,
)
from sillycation.domain.user import User
from sillycation.domain.value_objects import InvitationCode

DAY = date(2026, 11, 10)
USER, TRIP, EPISODE, REQUEST, VOTE = (
    UserId("user"),
    TripId("trip"),
    EpisodeId("episode"),
    JoinRequestId("request"),
    VoteId("vote"),
)
OPERATIONS = [
    (
        "register_user",
        "RegisterUser",
        ("users", "passwords"),
        dict(
            user_id=USER, username="User", email="user@example.org", password="secret"
        ),
    ),
    (
        "create_trip",
        "CreateTrip",
        ("trips", "users"),
        dict(
            trip_id=TRIP,
            name="Trip",
            creator_id=USER,
            start_date=DAY,
            end_date=DAY,
            invitation_code=InvitationCode("CODE"),
            description="Memo",
        ),
    ),
    (
        "request_join_trip",
        "RequestJoinTrip",
        ("trips",),
        dict(invitation_code=InvitationCode("CODE"), request_id=REQUEST, user_id=USER),
    ),
    (
        "approve_join_request",
        "ApproveJoinRequest",
        ("trips",),
        dict(trip_id=TRIP, request_id=REQUEST, requested_by=USER),
    ),
    (
        "reject_join_request",
        "RejectJoinRequest",
        ("trips",),
        dict(trip_id=TRIP, request_id=REQUEST, requested_by=USER),
    ),
    (
        "activate_trip",
        "ActivateTrip",
        ("trips",),
        dict(trip_id=TRIP, requested_by=USER, current_date=DAY),
    ),
    (
        "complete_trip",
        "CompleteTrip",
        ("trips", "episodes"),
        dict(trip_id=TRIP, requested_by=USER, current_date=DAY),
    ),
    ("archive_trip", "ArchiveTrip", ("trips",), dict(trip_id=TRIP, requested_by=USER)),
    (
        "create_episode",
        "CreateEpisode",
        ("trips", "episodes"),
        dict(
            episode_id=EPISODE,
            trip_id=TRIP,
            author_id=USER,
            protagonist_id=USER,
            title="Title",
            description="Details",
            date=DAY,
        ),
    ),
    (
        "edit_episode",
        "EditEpisode",
        ("trips", "episodes"),
        dict(
            episode_id=EPISODE,
            requested_by=USER,
            protagonist_id=USER,
            title="Changed",
            description="New",
            date=DAY,
        ),
    ),
    (
        "delete_episode",
        "DeleteEpisode",
        ("trips", "episodes"),
        dict(episode_id=EPISODE, requested_by=USER),
    ),
    (
        "submit_episode",
        "SubmitEpisode",
        ("trips", "episodes"),
        dict(episode_id=EPISODE, requested_by=USER),
    ),
    (
        "cast_vote",
        "CastVote",
        ("trips", "episodes"),
        dict(episode_id=EPISODE, vote_id=VOTE, voter_id=USER, value=4),
    ),
]


@pytest.mark.parametrize("method,case,dependencies,arguments", OPERATIONS)
def test_every_command_constructs_existing_use_case_inside_transaction(
    method, case, dependencies, arguments
) -> None:
    events = []
    unit = Mock(spec=UnitOfWork)

    def enter():
        events.append("enter")
        return unit

    unit.__enter__ = Mock(side_effect=enter)
    unit.__exit__ = Mock(side_effect=lambda *args: events.append("exit"))
    unit.commit.side_effect = lambda: events.append("commit")
    factory = Mock(return_value=unit)
    passwords = Mock(spec=PasswordHasher)
    result = None if method == "delete_episode" else sentinel.result
    with patch("sillycation.application.transactional." + case) as constructor:
        use_case = Mock()

        def construct(*args):
            events.append("construct")
            return use_case

        def execute(**kwargs):
            events.append("execute")
            return result

        constructor.side_effect = construct
        use_case.execute.side_effect = execute
        commands = TransactionalCommands(factory, passwords)
        assert getattr(commands, method)(**arguments) is result
        constructor.assert_called_once_with(
            *(
                passwords if name == "passwords" else getattr(unit, name)
                for name in dependencies
            )
        )
        use_case.execute.assert_called_once_with(**arguments)
    assert events == ["enter", "construct", "execute", "commit", "exit"]
    factory.assert_called_once_with()


class FakeUnit:
    """Staged snapshots, rather than immediate writes to shared fake storage."""

    def __init__(self, stored: dict[UserId, User], *, fail_save: bool = False) -> None:
        self.stored = stored
        self.working: dict[UserId, User] = {}
        self.active = False
        self.committed = False
        self.exited = False
        self.fail_save = fail_save
        self.users = Mock(spec=UserRepository)
        self.trips = Mock(spec=TripRepository)
        self.episodes = Mock(spec=EpisodeRepository)
        self.users.get_by_id.side_effect = self.get
        self.users.exists_by_username.side_effect = lambda username: any(
            user.username == username for user in self.working.values()
        )
        self.users.exists_by_email.side_effect = lambda email: any(
            user.email == email for user in self.working.values()
        )
        self.users.save.side_effect = self.save

    def __enter__(self) -> "FakeUnit":
        assert not self.active and not self.exited
        self.active = True
        self.working = deepcopy(self.stored)
        return self

    def get(self, identity: UserId) -> Optional[User]:
        assert self.active
        return deepcopy(self.working.get(identity))

    def save(self, user: User) -> User:
        assert self.active
        self.working[user.id] = deepcopy(user)
        if self.fail_save:
            raise RuntimeError("save failure")
        return deepcopy(user)

    def commit(self) -> None:
        assert self.active
        self.stored.clear()
        self.stored.update(deepcopy(self.working))
        self.committed = True

    def rollback(self) -> None:
        self.working = {}

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        if not self.committed:
            self.rollback()
        self.active = False
        self.exited = True


def test_each_command_obtains_a_fresh_unit_and_commits_real_use_case_result() -> None:
    stored: dict[UserId, User] = {}
    instances: list[FakeUnit] = []

    def factory() -> UnitOfWork:
        unit = FakeUnit(stored)
        instances.append(unit)
        return unit

    passwords = Mock(spec=PasswordHasher)
    passwords.hash.return_value = "encoded"
    commands = TransactionalCommands(factory, passwords)
    for key in ("first", "second"):
        assert commands.register_user(
            user_id=UserId(key),
            username=key,
            email=key + "@example.org",
            password="secret",
        ) == UserId(key)
    assert len(instances) == 2 and instances[0] is not instances[1]
    assert all(unit.committed and unit.exited for unit in instances)
    assert len(stored) == 2
    assert all(user.password_hash == "encoded" for user in stored.values())


def test_save_failure_discards_staged_mutation_without_commit() -> None:
    stored: dict[UserId, User] = {}
    unit = FakeUnit(stored, fail_save=True)
    passwords = Mock(spec=PasswordHasher)
    passwords.hash.return_value = "encoded"
    commands = TransactionalCommands(lambda: unit, passwords)
    with pytest.raises(RuntimeError, match="save failure"):
        commands.register_user(
            user_id=USER, username="User", email="user@example.org", password="secret"
        )
    assert stored == {} and unit.working == {}
    assert unit.exited and not unit.committed


@pytest.mark.parametrize("stage", ["enter", "execute", "commit", "exit"])
def test_failures_propagate_and_never_produce_an_apparent_success(stage) -> None:
    unit = Mock(spec=UnitOfWork)
    unit.__enter__ = Mock(return_value=unit)
    unit.__exit__ = Mock(return_value=None)
    factory = Mock(return_value=unit)
    error = RuntimeError(stage)
    with patch("sillycation.application.transactional.ArchiveTrip") as constructor:
        constructor.return_value.execute.return_value = sentinel.result
        target = {
            "enter": unit.__enter__,
            "execute": constructor.return_value.execute,
            "commit": unit.commit,
            "exit": unit.__exit__,
        }[stage]
        target.side_effect = error
        commands = TransactionalCommands(factory, Mock(spec=PasswordHasher))
        with pytest.raises(RuntimeError) as caught:
            commands.archive_trip(trip_id=TRIP, requested_by=USER)
        assert caught.value is error
        factory.assert_called_once_with()
        if stage in ("enter", "execute"):
            unit.commit.assert_not_called()
