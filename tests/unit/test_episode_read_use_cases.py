from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict
from datetime import date
from decimal import Decimal
from typing import Optional, Sequence

import pytest

from sillycation.application.episode_read_use_cases import (
    GetTripDashboard,
    ListTripEpisodes,
)
from sillycation.application.ports.repositories import EpisodeRepository, TripRepository
from sillycation.application.ranking_use_cases import GetParticipantRanking
from sillycation.domain.episode import Episode, EpisodeStatus
from sillycation.domain.identifiers import (
    EpisodeId,
    JoinRequestId,
    TripId,
    UserId,
    VoteId,
)
from sillycation.domain.services import RankingEntry
from sillycation.domain.trip import Participant, Trip, TripStatus
from sillycation.domain.value_objects import InvitationCode, TripPeriod, VoteValue

DAY = date(2026, 11, 13)
CREATOR, AUTHOR, HERO, OTHER, PENDING = map(
    UserId, ("creator", "author", "hero", "other", "pending")
)
READS = (ListTripEpisodes, GetTripDashboard)


class MemoryTrips:
    def __init__(self, trip: Trip) -> None:
        self.trip = trip
        self.lookups: list[TripId] = []

    def get_by_id(self, trip_id: TripId) -> Optional[Trip]:
        self.lookups.append(trip_id)
        return self.trip if trip_id == self.trip.id else None

    def save(self, trip: Trip) -> Trip:
        raise AssertionError("Unexpected write")

    def get_by_invitation_code(self, invitation_code: InvitationCode) -> Optional[Trip]:
        raise AssertionError("Unexpected query")

    def find_by_participant(self, user_id: UserId) -> Sequence[Trip]:
        raise AssertionError("Unexpected query")

    def find_active_or_planned_trips_by_participant(
        self, user_id: UserId
    ) -> Sequence[Trip]:
        raise AssertionError("Unexpected query")


class MemoryEpisodes:
    def __init__(self, episodes: Sequence[Episode]) -> None:
        self.episodes = list(episodes)
        self.queries: list[TripId] = []

    def find_by_trip(self, trip_id: TripId) -> Sequence[Episode]:
        self.queries.append(trip_id)
        # Include foreign aggregates to verify defensive selection.
        return self.episodes

    def get_by_id(self, episode_id: EpisodeId) -> Optional[Episode]:
        raise AssertionError("Unexpected lookup")

    def find_unresolved_by_trip(self, trip_id: TripId) -> Sequence[Episode]:
        raise AssertionError("Unexpected query")

    def save(self, episode: Episode) -> Episode:
        raise AssertionError("Unexpected write")

    def delete(self, episode_id: EpisodeId) -> None:
        raise AssertionError("Unexpected delete")


def make_trip(key="trip"):
    trip = Trip(
        TripId(key),
        "Holiday",
        CREATOR,
        TripPeriod(DAY, DAY),
        InvitationCode("secret"),
        description="Trip description",
    )
    for user in (AUTHOR, HERO, OTHER):
        request = JoinRequestId(user.value)
        trip.request_to_join(request, user)
        trip.approve_join_request(request, requested_by=CREATOR)
    trip.request_to_join(JoinRequestId("pending"), PENDING)
    return trip


def make_episode(trip, key, status=EpisodeStatus.DRAFT):
    episode = Episode(
        EpisodeId(key), trip.id, AUTHOR, HERO, "Title " + key, "Description " + key, DAY
    )
    if status is not EpisodeStatus.DRAFT:
        episode.submit(requested_by=AUTHOR, trip_status=trip.status)
    if status is EpisodeStatus.COMPLETED:
        for user, value in ((CREATOR, 3), (AUTHOR, 4), (OTHER, 5)):
            episode.cast_vote(
                VoteId(key + user.value),
                user,
                VoteValue(value),
                eligible_voters={CREATOR, AUTHOR, OTHER},
                trip_status=trip.status,
            )
    return episode


def rows(result):
    return result.episodes if hasattr(result, "episodes") else result


@pytest.mark.parametrize("use_case", READS)
@pytest.mark.parametrize("actor", [AUTHOR, CREATOR, HERO, OTHER])
def test_visibility_projection_order_and_no_effects(use_case, actor) -> None:
    trip = make_trip()
    trip.activate(requested_by=CREATOR, current_date=DAY)
    draft = make_episode(trip, "b-draft")
    voting = make_episode(trip, "z-voting", EpisodeStatus.VOTING)
    completed = make_episode(trip, "a-completed", EpisodeStatus.COMPLETED)
    foreign_trip = make_trip("foreign")
    foreign_trip.activate(requested_by=CREATOR, current_date=DAY)
    foreign = make_episode(foreign_trip, "foreign", EpisodeStatus.COMPLETED)
    trips = MemoryTrips(trip)
    episodes = MemoryEpisodes([voting, foreign, draft, completed])
    trip_port: TripRepository = trips
    episode_port: EpisodeRepository = episodes
    before = deepcopy([vars(trip), *[vars(e) for e in episodes.episodes]])
    result = use_case(trip_port, episode_port).execute(
        trip_id=trip.id, requested_by=actor
    )
    visible = rows(result)
    assert isinstance(visible, tuple)
    expected = [completed, draft, voting] if actor == AUTHOR else [completed, voting]
    assert [r.id for r in visible] == [e.id for e in expected]
    for row, source in zip(visible, expected):
        assert (
            row.trip_id,
            row.author_id,
            row.protagonist_id,
            row.title,
            row.description,
            row.date,
            row.status,
            row.score,
        ) == (
            trip.id,
            AUTHOR,
            HERO,
            source.title,
            source.description,
            DAY,
            source.status,
            Decimal(4) if source is completed else None,
        )
        assert set(asdict(row)) == {
            "id",
            "trip_id",
            "author_id",
            "protagonist_id",
            "title",
            "description",
            "date",
            "status",
            "score",
        }
        with pytest.raises(FrozenInstanceError):
            setattr(row, "title", "changed")
    assert trips.lookups == [trip.id]
    assert episodes.queries == [trip.id]
    assert [vars(trip), *[vars(e) for e in episodes.episodes]] == before
    episodes.episodes.reverse()
    assert (
        use_case(trips, episodes).execute(trip_id=trip.id, requested_by=actor) == result
    )
    if use_case is GetTripDashboard:
        assert result.ranking == (
            RankingEntry(HERO, Decimal(4), 1),
            RankingEntry(AUTHOR, Decimal(0), 2),
            RankingEntry(CREATOR, Decimal(0), 2),
            RankingEntry(OTHER, Decimal(0), 2),
        )
        assert result.ranking == GetParticipantRanking(trips, episodes).execute(
            trip_id=trip.id, requested_by=actor
        )


@pytest.mark.parametrize("status", list(TripStatus))
def test_dashboard_trip_data_history_and_immutability(status):
    trip = make_trip()
    stored = []
    if status is not TripStatus.PLANNED:
        trip.activate(requested_by=CREATOR, current_date=DAY)
        stored = [make_episode(trip, "done", EpisodeStatus.COMPLETED)]
    if status in (TripStatus.COMPLETED, TripStatus.ARCHIVED):
        trip.complete(
            requested_by=CREATOR, current_date=DAY, has_unresolved_episodes=False
        )
    if status is TripStatus.ARCHIVED:
        trip.archive(requested_by=CREATOR)
    trips, episodes = MemoryTrips(trip), MemoryEpisodes(stored)
    before = deepcopy([vars(trip), *[vars(e) for e in stored]])
    result = GetTripDashboard(trips, episodes).execute(
        trip_id=trip.id, requested_by=AUTHOR
    )
    assert asdict(result.trip) == {
        "id": {"value": "trip"},
        "name": "Holiday",
        "creator_id": {"value": "creator"},
        "period": {"start_date": DAY, "end_date": DAY},
        "status": status,
        "description": "Trip description",
    }
    assert result.participants == tuple(
        Participant(trip.id, u) for u in (AUTHOR, CREATOR, HERO, OTHER)
    )
    assert set(asdict(result)) == {"trip", "participants", "episodes", "ranking"}
    for obj, field in (
        (result, "trip"),
        (result.trip, "name"),
        (result.participants[0], "user_id"),
        (result.ranking[0], "score"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(obj, field, None)
    assert isinstance(result.ranking, tuple)
    assert episodes.queries == [trip.id]
    assert trips.lookups == [trip.id]
    assert (
        ListTripEpisodes(trips, episodes).execute(trip_id=trip.id, requested_by=AUTHOR)
        == result.episodes
    )
    assert [vars(trip), *[vars(e) for e in stored]] == before


@pytest.mark.parametrize("use_case", READS)
@pytest.mark.parametrize("actor", [PENDING, UserId("outsider")])
def test_unauthorized_before_episode_query(use_case, actor):
    trip = make_trip()
    episodes = MemoryEpisodes([])
    before = deepcopy(vars(trip))
    with pytest.raises(PermissionError):
        use_case(MemoryTrips(trip), episodes).execute(
            trip_id=trip.id, requested_by=actor
        )
    assert episodes.queries == []
    assert vars(trip) == before


@pytest.mark.parametrize("use_case", READS)
def test_missing_trip(use_case):
    episodes = MemoryEpisodes([])
    with pytest.raises(LookupError):
        use_case(MemoryTrips(make_trip()), episodes).execute(
            trip_id=TripId("missing"), requested_by=AUTHOR
        )
    assert episodes.queries == []


@pytest.mark.parametrize("use_case", READS)
def test_no_episodes(use_case):
    trip = make_trip()
    result = use_case(MemoryTrips(trip), MemoryEpisodes([])).execute(
        trip_id=trip.id, requested_by=AUTHOR
    )
    assert rows(result) == ()
    if use_case is GetTripDashboard:
        assert result.ranking == tuple(
            RankingEntry(u, Decimal(0), 1) for u in (AUTHOR, CREATOR, HERO, OTHER)
        )


@pytest.mark.parametrize("use_case", READS)
@pytest.mark.parametrize("source", ["trip", "episodes"])
def test_technical_errors_propagate(use_case, source, monkeypatch):
    trip = make_trip()
    trips, episodes = MemoryTrips(trip), MemoryEpisodes([])
    before = deepcopy(vars(trip))
    failure = RuntimeError("Storage unavailable")

    def fail(*args):
        raise failure

    monkeypatch.setattr(
        trips if source == "trip" else episodes,
        "get_by_id" if source == "trip" else "find_by_trip",
        fail,
    )
    with pytest.raises(RuntimeError) as caught:
        use_case(trips, episodes).execute(trip_id=trip.id, requested_by=AUTHOR)
    assert caught.value is failure
    assert vars(trip) == before
