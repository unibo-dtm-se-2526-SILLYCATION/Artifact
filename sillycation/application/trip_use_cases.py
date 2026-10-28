"""Trip workflows coordinating repository ports and domain operations.

The caller supplies authenticated actor identities, system-allocated identifiers
and invitation codes, and the current date. Generation and authentication are
outside these use cases. LookupError denotes missing users/trips; ApplicationError
denotes cross-aggregate conflicts. Domain ValueError exceptions propagate intact.
"""

from datetime import date
from typing import Optional

from sillycation.application.ports.repositories import TripRepository, UserRepository
from sillycation.domain.identifiers import JoinRequestId, TripId, UserId
from sillycation.domain.services import TripConflictService
from sillycation.domain.trip import JoinRequest, Trip
from sillycation.domain.value_objects import InvitationCode, TripPeriod


class ApplicationError(Exception):
    """A workflow cannot proceed because of a cross-aggregate conflict."""


def _get_trip(trips: TripRepository, trip_id: TripId) -> Trip:
    trip = trips.get_by_id(trip_id)
    if trip is None:
        raise LookupError("Trip not found")
    return trip


def _has_conflict(trips: TripRepository, user_id: UserId, trip: Trip) -> bool:
    existing = trips.find_active_or_planned_trips_by_participant(user_id)
    return TripConflictService().has_trip_conflict(
        user_id, trip.period, (other for other in existing if other.id != trip.id)
    )


class CreateTrip:
    def __init__(self, trips: TripRepository, users: UserRepository) -> None:
        self._trips = trips
        self._users = users

    def execute(
        self,
        *,
        trip_id: TripId,
        name: str,
        creator_id: UserId,
        start_date: date,
        end_date: date,
        invitation_code: InvitationCode,
        description: Optional[str] = None,
    ) -> Trip:
        """Create after checking creator, identity, invitation and overlap.

        Uniqueness lookups are preflight checks, not a concurrency guarantee.
        A future persistence adapter must enforce uniqueness atomically.
        """
        if self._users.get_by_id(creator_id) is None:
            raise LookupError("User not found")
        period = TripPeriod(start_date, end_date)
        if self._trips.get_by_id(trip_id) is not None:
            raise ApplicationError("Trip identity already exists")
        if self._trips.get_by_invitation_code(invitation_code) is not None:
            raise ApplicationError("Invitation code already exists")
        trip = Trip(trip_id, name, creator_id, period, invitation_code, description)
        if _has_conflict(self._trips, creator_id, trip):
            raise ApplicationError("Trip periods overlap")
        return self._trips.save(trip)


class RequestJoinTrip:
    def __init__(self, trips: TripRepository) -> None:
        self._trips = trips

    def execute(
        self,
        *,
        invitation_code: InvitationCode,
        request_id: JoinRequestId,
        user_id: UserId,
    ) -> JoinRequest:
        trip = self._trips.get_by_invitation_code(invitation_code)
        if trip is None:
            raise LookupError("Trip invitation code not found")
        if _has_conflict(self._trips, user_id, trip):
            raise ApplicationError("Trip periods overlap")
        trip.request_to_join(request_id, user_id)
        saved = self._trips.save(trip)
        return saved.get_join_request(request_id)


class ApproveJoinRequest:
    def __init__(self, trips: TripRepository) -> None:
        self._trips = trips

    def execute(
        self,
        *,
        trip_id: TripId,
        request_id: JoinRequestId,
        requested_by: UserId,
    ) -> JoinRequest:
        """Return APPROVED, or REJECTED specifically because of an overlap.

        Both domain decision methods enforce creator, PLANNED and PENDING
        before changing membership or requests. Invalid operations never save.
        """
        trip = _get_trip(self._trips, trip_id)
        request = trip.get_join_request(request_id)
        if _has_conflict(self._trips, request.user_id, trip):
            trip.reject_join_request(request_id, requested_by=requested_by)
        else:
            trip.approve_join_request(request_id, requested_by=requested_by)
        saved = self._trips.save(trip)
        return saved.get_join_request(request_id)


class RejectJoinRequest:
    def __init__(self, trips: TripRepository) -> None:
        self._trips = trips

    def execute(
        self,
        *,
        trip_id: TripId,
        request_id: JoinRequestId,
        requested_by: UserId,
    ) -> JoinRequest:
        trip = _get_trip(self._trips, trip_id)
        trip.reject_join_request(request_id, requested_by=requested_by)
        saved = self._trips.save(trip)
        return saved.get_join_request(request_id)


class ActivateTrip:
    def __init__(self, trips: TripRepository) -> None:
        self._trips = trips

    def execute(
        self,
        *,
        trip_id: TripId,
        requested_by: UserId,
        current_date: date,
    ) -> Trip:
        trip = _get_trip(self._trips, trip_id)
        trip.activate(requested_by=requested_by, current_date=current_date)
        return self._trips.save(trip)
