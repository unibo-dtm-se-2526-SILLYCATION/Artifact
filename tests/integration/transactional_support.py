"""Test-only setup through real transactional commands and file-backed SQLite."""

from datetime import date

from sqlalchemy import Engine

from sillycation.adapters.persistence.unit_of_work import SqliteUnitOfWork
from sillycation.application.transactional import TransactionalCommands
from sillycation.domain.identifiers import EpisodeId, JoinRequestId, TripId, UserId
from sillycation.domain.value_objects import InvitationCode

DAY = date(2026, 11, 10)
AUTHOR, PROTAGONIST, VOTER, FIRST, SECOND = [
    UserId(key) for key in ("author", "protagonist", "voter", "first", "second")
]
TRIP = TripId("trip")
EPISODE = EpisodeId("episode")


class TestHasher:
    """Only a test double; never supplied by production composition."""

    def hash(self, password: str) -> str:
        return "test-hash:" + password

    def verify(self, password: str, password_hash: str) -> bool:
        return password_hash == self.hash(password)


def commands_for(engine: Engine, *, timeout: float = 10.0) -> TransactionalCommands:
    return TransactionalCommands(
        lambda: SqliteUnitOfWork(engine, timeout=timeout), TestHasher()
    )


def seed_users(commands: TransactionalCommands) -> None:
    for identity in (AUTHOR, PROTAGONIST, VOTER, FIRST, SECOND):
        commands.register_user(
            user_id=identity,
            username=identity.value,
            email=identity.value + "@example.org",
            password="secret",
        )


def seed_trip(
    commands: TransactionalCommands,
    *,
    key: str = "trip",
    creator: UserId = AUTHOR,
    members: tuple[UserId, ...] = (PROTAGONIST, VOTER),
    active: bool = True,
) -> TripId:
    identity = TripId(key)
    code = InvitationCode("code-" + key)
    commands.create_trip(
        trip_id=identity,
        name=key,
        creator_id=creator,
        start_date=DAY,
        end_date=DAY,
        invitation_code=code,
    )
    for member in members:
        request = JoinRequestId(key + "-" + member.value)
        commands.request_join_trip(
            invitation_code=code, request_id=request, user_id=member
        )
        commands.approve_join_request(
            trip_id=identity, request_id=request, requested_by=creator
        )
    if active:
        commands.activate_trip(trip_id=identity, requested_by=creator, current_date=DAY)
    return identity


def seed_episode(
    commands: TransactionalCommands, *, submitted: bool = False
) -> EpisodeId:
    commands.create_episode(
        episode_id=EPISODE,
        trip_id=TRIP,
        author_id=AUTHOR,
        protagonist_id=PROTAGONIST,
        title="Original",
        description="Details",
        date=DAY,
    )
    if submitted:
        commands.submit_episode(episode_id=EPISODE, requested_by=AUTHOR)
    return EPISODE
