"""Domain rules requiring information from multiple aggregates."""

from typing import Iterable

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
