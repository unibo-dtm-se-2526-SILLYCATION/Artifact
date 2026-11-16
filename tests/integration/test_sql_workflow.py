"""The existing use cases working together with the SQL repositories.

One complete game is played through the application layer only, so every step
reads its data back from the database and writes its result to it.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import Engine

from sillycation.adapters.persistence.episode_repository import (
    SqlAlchemyEpisodeRepository,
)
from sillycation.adapters.persistence.trip_repository import SqlAlchemyTripRepository
from sillycation.adapters.persistence.user_repository import SqlAlchemyUserRepository
from sillycation.application.episode_use_cases import CreateEpisode, SubmitEpisode
from sillycation.application.ranking_use_cases import GetParticipantRanking
from sillycation.application.trip_use_cases import (
    ActivateTrip,
    ApproveJoinRequest,
    CompleteTrip,
    CreateTrip,
    RequestJoinTrip,
)
from sillycation.application.user_use_cases import RegisterUser
from sillycation.application.voting_use_cases import CastVote
from sillycation.domain.episode import EpisodeStatus
from sillycation.domain.identifiers import (
    EpisodeId,
    JoinRequestId,
    TripId,
    UserId,
    VoteId,
)
from sillycation.domain.trip import TripStatus
from sillycation.domain.value_objects import InvitationCode


ANNA = UserId("anna")
LUCA = UserId("luca")
SARA = UserId("sara")
TRIP = TripId("trip")
EPISODE = EpisodeId("episode")
START = date(2026, 11, 10)
END = date(2026, 11, 12)


class PlainHasher:
    """Stands in for the real password hasher, which is not under test here."""

    def hash(self, password: str) -> str:
        return f"hashed:{password}"

    def verify(self, password: str, password_hash: str) -> bool:
        return password_hash == f"hashed:{password}"


def test_a_whole_trip_is_played_through_the_database(engine: Engine) -> None:
    users = SqlAlchemyUserRepository(engine)
    trips = SqlAlchemyTripRepository(engine)
    episodes = SqlAlchemyEpisodeRepository(engine)

    for user_id in (ANNA, LUCA, SARA):
        RegisterUser(users, PlainHasher()).execute(
            user_id=user_id,
            username=user_id.value,
            email=f"{user_id.value}@example.org",
            password="secret",
        )

    CreateTrip(trips, users).execute(
        trip_id=TRIP,
        name="Lisbon",
        creator_id=ANNA,
        start_date=START,
        end_date=END,
        invitation_code=InvitationCode("LISBON"),
    )
    for user_id in (LUCA, SARA):
        request_id = JoinRequestId(f"request-{user_id.value}")
        RequestJoinTrip(trips).execute(
            invitation_code=InvitationCode("LISBON"),
            request_id=request_id,
            user_id=user_id,
        )
        ApproveJoinRequest(trips).execute(
            trip_id=TRIP, request_id=request_id, requested_by=ANNA
        )
    ActivateTrip(trips).execute(trip_id=TRIP, requested_by=ANNA, current_date=START)

    CreateEpisode(trips, episodes).execute(
        episode_id=EPISODE,
        trip_id=TRIP,
        author_id=ANNA,
        protagonist_id=LUCA,
        title="Lost passport",
        description="Left it at the hotel",
        date=START,
    )
    SubmitEpisode(trips, episodes).execute(episode_id=EPISODE, requested_by=ANNA)
    CastVote(trips, episodes).execute(
        episode_id=EPISODE, vote_id=VoteId("vote-anna"), voter_id=ANNA, value=5
    )
    CastVote(trips, episodes).execute(
        episode_id=EPISODE, vote_id=VoteId("vote-sara"), voter_id=SARA, value=4
    )

    CompleteTrip(trips, episodes).execute(
        trip_id=TRIP, requested_by=ANNA, current_date=END
    )

    stored_trip = trips.get_by_id(TRIP)
    stored_episode = episodes.get_by_id(EPISODE)
    ranking = GetParticipantRanking(trips, episodes).execute(
        trip_id=TRIP, requested_by=SARA
    )
    assert stored_trip is not None
    assert stored_trip.status is TripStatus.COMPLETED
    assert stored_episode is not None
    assert stored_episode.status is EpisodeStatus.COMPLETED
    assert stored_episode.score == Decimal("4.5")
    assert [(entry.user_id, entry.score, entry.position) for entry in ranking] == [
        (LUCA, Decimal("4.5"), 1),
        (ANNA, Decimal("0"), 2),
        (SARA, Decimal("0"), 2),
    ]
