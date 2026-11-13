"""Participant reads using caller-authenticated identities, without writes."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional, Sequence

from sillycation.application.ports.repositories import EpisodeRepository, TripRepository
from sillycation.domain.episode import Episode, EpisodeStatus
from sillycation.domain.identifiers import EpisodeId, TripId, UserId
from sillycation.domain.services import RankingEntry, RankingService
from sillycation.domain.trip import Participant, Trip, TripStatus
from sillycation.domain.value_objects import TripPeriod


@dataclass(frozen=True)
class EpisodeSummary:
    id: EpisodeId
    trip_id: TripId
    author_id: UserId
    protagonist_id: UserId
    title: str
    description: str
    date: date
    status: EpisodeStatus
    score: Optional[Decimal]


@dataclass(frozen=True)
class DashboardTrip:
    id: TripId
    name: str
    creator_id: UserId
    period: TripPeriod
    status: TripStatus
    description: Optional[str]


@dataclass(frozen=True)
class TripDashboard:
    trip: DashboardTrip
    participants: tuple[Participant, ...]
    episodes: tuple[EpisodeSummary, ...]
    ranking: tuple[RankingEntry, ...]


def _load(
    trips: TripRepository,
    episodes: EpisodeRepository,
    trip_id: TripId,
    requested_by: UserId,
) -> tuple[Trip, tuple[Episode, ...]]:
    trip = trips.get_by_id(trip_id)
    if trip is None:
        raise LookupError("Trip not found")
    if Participant(trip.id, requested_by) not in trip.participants:
        raise PermissionError("Only Trip participants may access these data")
    return trip, tuple(
        episode
        for episode in episodes.find_by_trip(trip.id)
        if episode.trip_id == trip.id
    )


def _visible(
    episodes: Sequence[Episode], requested_by: UserId
) -> tuple[EpisodeSummary, ...]:
    # SUBMITTED is transient; FR-11 makes submitted Episodes visible to members.
    return tuple(
        EpisodeSummary(
            episode.id,
            episode.trip_id,
            episode.author_id,
            episode.protagonist_id,
            episode.title,
            episode.description,
            episode.date,
            episode.status,
            episode.score if episode.status is EpisodeStatus.COMPLETED else None,
        )
        for episode in sorted(episodes, key=lambda item: item.id.value)
        if episode.status is not EpisodeStatus.DRAFT
        or episode.author_id == requested_by
    )


class ListTripEpisodes:
    def __init__(self, trips: TripRepository, episodes: EpisodeRepository) -> None:
        self._trips = trips
        self._episodes = episodes

    def execute(
        self, *, trip_id: TripId, requested_by: UserId
    ) -> tuple[EpisodeSummary, ...]:
        _, episodes = _load(self._trips, self._episodes, trip_id, requested_by)
        return _visible(episodes, requested_by)


class GetTripDashboard:
    def __init__(self, trips: TripRepository, episodes: EpisodeRepository) -> None:
        self._trips = trips
        self._episodes = episodes

    def execute(self, *, trip_id: TripId, requested_by: UserId) -> TripDashboard:
        trip, episodes = _load(self._trips, self._episodes, trip_id, requested_by)
        return TripDashboard(
            DashboardTrip(
                trip.id,
                trip.name,
                trip.creator_id,
                trip.period,
                trip.status,
                trip.description,
            ),
            tuple(sorted(trip.participants, key=lambda member: member.user_id.value)),
            _visible(episodes, requested_by),
            RankingService().calculate(trip, episodes),
        )
