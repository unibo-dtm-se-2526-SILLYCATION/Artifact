"""Domain rules requiring information from multiple aggregates."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional

from sillycation.domain.episode import Episode, EpisodeStatus
from sillycation.domain.identifiers import UserId
from sillycation.domain.trip import Participant, Trip, TripStatus
from sillycation.domain.value_objects import TripPeriod


class TripConflictService:
    """Check the non-overlapping participation rule (INV-04)."""

    def has_trip_conflict(
        self, user_id: UserId, trip_period: TripPeriod, existing_trips: Iterable[Trip]
    ) -> bool:
        """Check a candidate period against trips supplied by the caller.

        The caller supplies the user's other trips, loading them again when
        approving a join request. Only actual membership in PLANNED or ACTIVE
        trips counts; pending requests do not reserve a period. No state changes
        or join-request decisions are performed here.
        """
        return any(
            trip.status in (TripStatus.PLANNED, TripStatus.ACTIVE)
            and Participant(trip.id, user_id) in trip.participants
            and trip_period.overlaps(trip.period)
            for trip in existing_trips
        )


@dataclass(frozen=True)
class RankingEntry:
    """A participant's current total and competition position."""

    user_id: UserId
    score: Decimal
    position: int


class RankingService:
    """Calculate participant totals from completed Episodes (FR-17 and FR-18)."""

    def calculate(
        self, trip: Trip, episodes: Iterable[Episode]
    ) -> tuple[RankingEntry, ...]:
        totals = {participant.user_id: Decimal(0) for participant in trip.participants}
        completed = (
            episode
            for episode in episodes
            if episode.trip_id == trip.id and episode.status is EpisodeStatus.COMPLETED
        )
        # Fix accumulation order too: Decimal addition uses the current context.
        for episode in sorted(completed, key=lambda item: item.id.value):
            if episode.score is None:
                raise ValueError("Completed episode has no score")
            if episode.protagonist_id not in totals:
                raise ValueError("Episode protagonist is not a Trip participant")
            totals[episode.protagonist_id] += episode.score

        ordered = sorted(totals.items(), key=lambda item: (-item[1], item[0].value))
        entries = []
        previous_score: Optional[Decimal] = None
        position = 0
        for index, (user_id, score) in enumerate(ordered, start=1):
            if score != previous_score:
                position = index
            entries.append(RankingEntry(user_id, score, position))
            previous_score = score
        return tuple(entries)
