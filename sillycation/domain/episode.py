"""Episode draft data and submission, independent of persistence and voting."""

from datetime import date as Date
from enum import Enum

from sillycation.domain.identifiers import EpisodeId, TripId, UserId
from sillycation.domain.trip import TripStatus


class EpisodeStatus(Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VOTING = "VOTING"
    COMPLETED = "COMPLETED"


class Episode:
    """Separate aggregate referencing its Trip only by identity.

    Creation requires the caller to verify that the Trip is ACTIVE, author and
    protagonist belong to it, and the episode date is within its period (domain
    specification section 20.2). Editing requires rechecking the protagonist and
    date against that same Trip. This aggregate does not store Trip membership.

    COMPLETED is reserved for the future voting workflow; no manual completion
    operation is exposed.
    """

    def __init__(
        self,
        id: EpisodeId,
        trip_id: TripId,
        author_id: UserId,
        protagonist_id: UserId,
        title: str,
        description: str,
        date: Date,
    ) -> None:
        if id is None or trip_id is None or author_id is None:
            raise ValueError("Episode, trip and author identities are required")
        self._validate_data(title, description, date, protagonist_id)
        self._id = id
        self._trip_id = trip_id
        self._author_id = author_id
        self._protagonist_id = protagonist_id
        self._title = title
        self._description = description
        self._date = date
        self._status = EpisodeStatus.DRAFT

    @property
    def id(self) -> EpisodeId:
        return self._id

    @property
    def trip_id(self) -> TripId:
        return self._trip_id

    @property
    def author_id(self) -> UserId:
        return self._author_id

    @property
    def protagonist_id(self) -> UserId:
        return self._protagonist_id

    @property
    def title(self) -> str:
        return self._title

    @property
    def description(self) -> str:
        return self._description

    @property
    def date(self) -> Date:
        return self._date

    @property
    def status(self) -> EpisodeStatus:
        return self._status

    def edit(
        self,
        *,
        requested_by: UserId,
        title: str,
        description: str,
        date: Date,
        protagonist_id: UserId,
    ) -> None:
        """Replace draft data after external protagonist/date validation."""
        self._require_author_draft(requested_by)
        self._validate_data(title, description, date, protagonist_id)
        self._title = title
        self._description = description
        self._date = date
        self._protagonist_id = protagonist_id

    def submit(self, *, requested_by: UserId, trip_status: TripStatus) -> None:
        """Submit and automatically open voting using the current Trip status.

        The caller must supply the status of the Trip identified by trip_id.
        SUBMITTED is transient within this operation (FR-11 and FR-12).
        """
        self._require_author_draft(requested_by)
        if trip_status is not TripStatus.ACTIVE:
            raise ValueError("Episode submission requires an ACTIVE trip")
        self._status = EpisodeStatus.SUBMITTED
        self._status = EpisodeStatus.VOTING

    def _require_author_draft(self, requested_by: UserId) -> None:
        if requested_by != self.author_id:
            raise ValueError("Only the episode author may perform this operation")
        if self.status is not EpisodeStatus.DRAFT:
            raise ValueError("Episode must be DRAFT for this operation")

    @staticmethod
    def _validate_data(
        title: str, description: str, date: Date, protagonist_id: UserId
    ) -> None:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Episode title is required")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("Episode description is required")
        if date is None or protagonist_id is None:
            raise ValueError("Episode date and protagonist are required")
