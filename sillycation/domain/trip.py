"""Trip membership and the PLANNED to ACTIVE lifecycle transition."""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional

from sillycation.domain.identifiers import TripId, UserId
from sillycation.domain.value_objects import InvitationCode, TripPeriod


class TripStatus(Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


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

    def add_participant(self, user_id: UserId, *, requested_by: UserId) -> None:
        """Record an approved membership, only while PLANNED.

        Precondition: the join request has been approved and cross-trip conflicts
        checked. This membership primitive does not implement that workflow.
        """
        self._require_creator(requested_by)
        self._require_planned()
        participant = Participant(self.id, user_id)
        if participant in self._participants:
            raise ValueError("User is already a participant of this trip")
        self._participants.add(participant)

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
