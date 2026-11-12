"""Authorized Trip reads using caller-authenticated identities, without writes."""

from dataclasses import dataclass

from sillycation.application.ports.repositories import TripRepository
from sillycation.domain.identifiers import TripId, UserId
from sillycation.domain.trip import (
    JoinRequest,
    JoinRequestStatus,
    Participant,
    Trip,
    TripStatus,
)
from sillycation.domain.value_objects import InvitationCode, TripPeriod


@dataclass(frozen=True)
class TripSummary:
    """List information excluding invitation codes and join requests."""

    id: TripId
    name: str
    creator_id: UserId
    period: TripPeriod
    status: TripStatus


def _get_trip(trips: TripRepository, trip_id: TripId) -> Trip:
    trip = trips.get_by_id(trip_id)
    if trip is None:
        raise LookupError("Trip not found")
    return trip


def _require_creator(trip: Trip, requested_by: UserId) -> None:
    if requested_by != trip.creator_id:
        raise PermissionError("Only the Trip creator may access this information")


class GetTripInvitationCode:
    def __init__(self, trips: TripRepository) -> None:
        self._trips = trips

    def execute(self, *, trip_id: TripId, requested_by: UserId) -> InvitationCode:
        """Read the code as creator in any state; use for joining remains restricted."""
        trip = _get_trip(self._trips, trip_id)
        _require_creator(trip, requested_by)
        return trip.invitation_code


class GetPendingJoinRequests:
    def __init__(self, trips: TripRepository) -> None:
        self._trips = trips

    def execute(
        self, *, trip_id: TripId, requested_by: UserId
    ) -> tuple[JoinRequest, ...]:
        """Read pending requests as creator, including after the PLANNED phase."""
        trip = _get_trip(self._trips, trip_id)
        _require_creator(trip, requested_by)
        return tuple(
            sorted(
                (
                    request
                    for request in trip.join_requests
                    if request.status is JoinRequestStatus.PENDING
                ),
                key=lambda request: request.id.value,
            )
        )


class GetTripParticipants:
    def __init__(self, trips: TripRepository) -> None:
        self._trips = trips

    def execute(
        self, *, trip_id: TripId, requested_by: UserId
    ) -> tuple[Participant, ...]:
        trip = _get_trip(self._trips, trip_id)
        if Participant(trip.id, requested_by) not in trip.participants:
            raise PermissionError(
                "Only Trip participants may read the participant list"
            )
        return tuple(
            sorted(trip.participants, key=lambda participant: participant.user_id.value)
        )


class ListMyTrips:
    def __init__(self, trips: TripRepository) -> None:
        self._trips = trips

    def execute(
        self, *, requested_by: UserId, archived: bool = False
    ) -> tuple[TripSummary, ...]:
        """Separate archived Trips from PLANNED, ACTIVE and COMPLETED Trips."""
        trips = self._trips.find_by_participant(requested_by)
        states = (
            (TripStatus.ARCHIVED,)
            if archived
            else (TripStatus.PLANNED, TripStatus.ACTIVE, TripStatus.COMPLETED)
        )
        matching = (
            trip
            for trip in trips
            if trip.status in states
            and Participant(trip.id, requested_by) in trip.participants
        )
        return tuple(
            TripSummary(trip.id, trip.name, trip.creator_id, trip.period, trip.status)
            for trip in sorted(matching, key=lambda trip: trip.id.value)
        )
