from copy import deepcopy
from datetime import date
from decimal import Decimal
from typing import Optional, Sequence

import pytest

from sillycation.application.ports.repositories import EpisodeRepository, TripRepository
from sillycation.application.ranking_use_cases import GetParticipantRanking
from sillycation.domain.episode import Episode
from sillycation.domain.identifiers import (
    EpisodeId,
    JoinRequestId,
    TripId,
    UserId,
    VoteId,
)
from sillycation.domain.services import RankingEntry
from sillycation.domain.trip import Trip
from sillycation.domain.value_objects import InvitationCode, TripPeriod, VoteValue


DAY = date(2026, 11, 4)
CREATOR = UserId("creator")
MEMBER = UserId("member")
PENDING = UserId("pending")


class MemoryTrips:
    def __init__(self, trip: Trip) -> None:
        self.trip = trip
        self.lookups: list[TripId] = []

    def get_by_id(self, trip_id: TripId) -> Optional[Trip]:
        self.lookups.append(trip_id)
        return self.trip if trip_id == self.trip.id else None

    def save(self, trip: Trip) -> Trip:
        raise AssertionError("Ranking must not save Trip")

    def get_by_invitation_code(self, invitation_code: InvitationCode) -> Optional[Trip]:
        raise AssertionError("Unexpected lookup")

    def find_by_participant(self, user_id: UserId) -> Sequence[Trip]:
        raise AssertionError("Unexpected query")

    def find_active_or_planned_trips_by_participant(
        self, user_id: UserId
    ) -> Sequence[Trip]:
        raise AssertionError("Unexpected query")


class MemoryEpisodes:
    def __init__(self, episodes: Sequence[Episode]) -> None:
        self.episodes = episodes
        self.queries: list[TripId] = []

    def find_by_trip(self, trip_id: TripId) -> Sequence[Episode]:
        self.queries.append(trip_id)
        return self.episodes

    def save(self, episode: Episode) -> Episode:
        raise AssertionError("Ranking must not save Episode")

    def get_by_id(self, episode_id: EpisodeId) -> Optional[Episode]:
        raise AssertionError("Unexpected lookup")

    def find_unresolved_by_trip(self, trip_id: TripId) -> Sequence[Episode]:
        raise AssertionError("Unexpected query")


def make_trip(active=False):
    trip = Trip(
        TripId("trip"), "Holiday", CREATOR, TripPeriod(DAY, DAY), InvitationCode("code")
    )
    trip.request_to_join(JoinRequestId("member"), MEMBER)
    trip.approve_join_request(JoinRequestId("member"), requested_by=CREATOR)
    trip.request_to_join(JoinRequestId("pending"), PENDING)
    if active:
        trip.activate(requested_by=CREATOR, current_date=DAY)
    return trip


@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("requester", [CREATOR, MEMBER])
def test_members_can_read_without_mutations_or_saves(
    active: bool, requester: UserId
) -> None:
    trip = make_trip(active)
    trips = MemoryTrips(trip)
    episodes = MemoryEpisodes([])
    trip_port: TripRepository = trips
    episode_port: EpisodeRepository = episodes
    before = deepcopy(vars(trip))
    result = GetParticipantRanking(trip_port, episode_port).execute(
        trip_id=trip.id, requested_by=requester
    )
    assert result == (
        RankingEntry(CREATOR, Decimal(0), 1),
        RankingEntry(MEMBER, Decimal(0), 1),
    )
    assert trips.lookups == [trip.id]
    assert episodes.queries == [trip.id]
    assert vars(trip) == before


def test_completed_episode_is_ranked_without_mutation():
    trip = make_trip(True)
    episode = Episode(
        EpisodeId("episode"), trip.id, CREATOR, MEMBER, "Title", "Description", DAY
    )
    episode.submit(requested_by=CREATOR, trip_status=trip.status)
    episode.cast_vote(
        VoteId("vote"),
        CREATOR,
        VoteValue(4),
        eligible_voters={CREATOR},
        trip_status=trip.status,
    )
    before = deepcopy([vars(trip), vars(episode)])
    result = GetParticipantRanking(
        MemoryTrips(trip), MemoryEpisodes([episode])
    ).execute(trip_id=trip.id, requested_by=MEMBER)
    assert result == (
        RankingEntry(MEMBER, Decimal(4), 1),
        RankingEntry(CREATOR, Decimal(0), 2),
    )
    assert [vars(trip), vars(episode)] == before


@pytest.mark.parametrize("requester", [UserId("outsider"), PENDING])
def test_non_members_rejected_before_loading_episodes(requester):
    trip = make_trip()
    episodes = MemoryEpisodes([])
    before = deepcopy(vars(trip))
    with pytest.raises(PermissionError):
        GetParticipantRanking(MemoryTrips(trip), episodes).execute(
            trip_id=trip.id, requested_by=requester
        )
    assert episodes.queries == []
    assert vars(trip) == before


def test_missing_trip():
    trip = make_trip()
    episodes = MemoryEpisodes([])
    with pytest.raises(LookupError, match="Trip"):
        GetParticipantRanking(MemoryTrips(trip), episodes).execute(
            trip_id=TripId("missing"), requested_by=CREATOR
        )
    assert episodes.queries == []


@pytest.mark.parametrize("source", ["trip", "episodes", "service"])
def test_errors_propagate_unchanged(source, monkeypatch):
    trip = make_trip()
    trips = MemoryTrips(trip)
    episodes = MemoryEpisodes([])
    error = (
        ValueError("inconsistent score")
        if source == "service"
        else RuntimeError("repository unavailable")
    )

    def fail(*args, **kwargs):
        raise error

    if source == "trip":
        monkeypatch.setattr(trips, "get_by_id", fail)
    elif source == "episodes":
        monkeypatch.setattr(episodes, "find_by_trip", fail)
    else:
        monkeypatch.setattr(
            "sillycation.application.ranking_use_cases.RankingService.calculate", fail
        )
    with pytest.raises(type(error)) as caught:
        GetParticipantRanking(trips, episodes).execute(
            trip_id=trip.id, requested_by=CREATOR
        )
    assert caught.value is error
