"""Trip membership and the PLANNED to ACTIVE lifecycle transition."""

from dataclasses import dataclass, replace
from datetime import date
from enum import Enum
from typing import Optional

from sillycation.domain.identifiers import JoinRequestId, TripId, UserId
from sillycation.domain.value_objects import InvitationCode, TripPeriod


class TripStatus(Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class JoinRequestStatus(Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class JoinRequest:
    """Immutable snapshot of a request owned and updated by its Trip."""

    id: JoinRequestId
    trip_id: TripId
    user_id: UserId
    status: JoinRequestStatus = JoinRequestStatus.PENDING


@dataclass(frozen=True)
class Participant:
    """Membership identity is the pair (trip_id, user_id)."""

    trip_id: TripId
    user_id: UserId


class Trip:
    """Owns its membership and exposes state through read-only properties.

    Creation receives an already allocated invitation code and a valid period.
    Code uniqueness and conflicts with other trips require external information.
    """

    def __init__(
        self,
        id: TripId,
        name: str,
        creator_id: UserId,
        period: TripPeriod,
        invitation_code: InvitationCode,
        description: Optional[str] = None,
    ) -> None:
        self._id = id
        self._name = name
        self._creator_id = creator_id
        self._period = period
        self._invitation_code = invitation_code
        self._description = description
        self._status = TripStatus.PLANNED
        self._participants = {Participant(id, creator_id)}
        self._join_requests: dict[JoinRequestId, JoinRequest] = {}

    @property
    def id(self) -> TripId:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def creator_id(self) -> UserId:
        return self._creator_id

    @property
    def period(self) -> TripPeriod:
        return self._period

    @property
    def invitation_code(self) -> InvitationCode:
        return self._invitation_code

    @property
    def description(self) -> Optional[str]:
        return self._description

    @property
    def status(self) -> TripStatus:
        return self._status

    @property
    def participants(self) -> frozenset[Participant]:
        return frozenset(self._participants)

    @property
    def join_requests(self) -> tuple[JoinRequest, ...]:
        """Return immutable snapshots; read again to observe later decisions."""
        return tuple(self._join_requests.values())

    def get_join_request(self, request_id: JoinRequestId) -> JoinRequest:
        try:
            return self._join_requests[request_id]
        except KeyError:
            raise ValueError("Join request does not belong to this trip") from None

    def request_to_join(
        self, request_id: JoinRequestId, user_id: UserId
    ) -> JoinRequest:
        """Create a pending request after invitation lookup and conflict checks.

        The caller resolves the invitation code to this Trip and checks conflicts
        with other trips, as specified by the join-trip sequence diagram.
        """
        self._require_planned()
        if Participant(self.id, user_id) in self._participants:
            raise ValueError("User is already a participant of this trip")
        if request_id in self._join_requests:
            raise ValueError("Join request identity is already in use")
        if any(
            request.user_id == user_id and request.status is JoinRequestStatus.PENDING
            for request in self._join_requests.values()
        ):
            raise ValueError("User already has a pending join request")
        request = JoinRequest(request_id, self.id, user_id)
        self._join_requests[request_id] = request
        return request

    def approve_join_request(
        self, request_id: JoinRequestId, *, requested_by: UserId
    ) -> None:
        """Approve after the caller has re-checked cross-trip conflicts.

        If a conflict exists, the caller must use reject_join_request instead.
        """
        request = self._require_pending_request(request_id, requested_by)
        self._participants.add(Participant(self.id, request.user_id))
        self._join_requests[request_id] = replace(
            request, status=JoinRequestStatus.APPROVED
        )

    def reject_join_request(
        self, request_id: JoinRequestId, *, requested_by: UserId
    ) -> None:
        """Reject by creator decision or upon a caller-reported trip conflict."""
        request = self._require_pending_request(request_id, requested_by)
        self._join_requests[request_id] = replace(
            request, status=JoinRequestStatus.REJECTED
        )

    def _require_pending_request(
        self, request_id: JoinRequestId, requested_by: UserId
    ) -> JoinRequest:
        self._require_creator(requested_by)
        self._require_planned()
        request = self.get_join_request(request_id)
        if request.status is not JoinRequestStatus.PENDING:
            raise ValueError("Join request must be PENDING for this operation")
        return request

    def activate(self, *, requested_by: UserId, current_date: date) -> None:
        """Activate explicitly once the start date and minimum membership are met."""
        self._require_creator(requested_by)
        self._require_planned()
        if current_date < self.period.start_date:
            raise ValueError("Trip cannot be activated before its start date")
        if len(self._participants) < 2:
            raise ValueError("Trip activation requires at least two participants")
        self._status = TripStatus.ACTIVE

    def _require_creator(self, requested_by: UserId) -> None:
        if requested_by != self.creator_id:
            raise ValueError("Only the trip creator may perform this operation")

    def _require_planned(self) -> None:
        if self.status is not TripStatus.PLANNED:
            raise ValueError("Trip must be PLANNED for this operation")
