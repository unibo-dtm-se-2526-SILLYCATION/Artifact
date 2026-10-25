"""Episode lifecycle and voting, independent of persistence."""

from dataclasses import dataclass
from datetime import date as Date
from decimal import Decimal
from enum import Enum
from typing import Iterable, Optional

from sillycation.domain.identifiers import EpisodeId, TripId, UserId, VoteId
from sillycation.domain.trip import TripStatus
from sillycation.domain.value_objects import VoteValue


@dataclass(frozen=True)
class Vote:
    """An immutable vote owned by an Episode."""

    id: VoteId
    episode_id: EpisodeId
    voter_id: UserId
    value: VoteValue

    def __post_init__(self) -> None:
        if not isinstance(self.value, VoteValue):
            raise ValueError("Vote requires a validated VoteValue")


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

    Completion occurs automatically with the final eligible vote; no manual
    completion operation is exposed.
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
        self._votes: dict[UserId, Vote] = {}
        self._eligible_voters: Optional[frozenset[UserId]] = None
        self._score: Optional[Decimal] = None

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

    @property
    def votes(self) -> tuple[Vote, ...]:
        return tuple(self._votes.values())

    @property
    def score(self) -> Optional[Decimal]:
        """Final arithmetic mean, absent until COMPLETED (FR-16)."""
        return self._score

    def has_vote_from(self, voter_id: UserId) -> bool:
        return voter_id in self._votes

    def cast_vote(
        self,
        vote_id: VoteId,
        voter_id: UserId,
        value: VoteValue,
        *,
        eligible_voters: Iterable[UserId],
        trip_status: TripStatus,
    ) -> Vote:
        """Record a vote and complete when every eligible voter has voted.

        The caller supplies this Trip's current status and locked participant
        identities minus the protagonist, as in the voting sequence diagram.
        The first accepted vote freezes that context for subsequent votes.
        """
        if self.status is not EpisodeStatus.VOTING:
            raise ValueError("Episode must be VOTING to receive votes")
        if trip_status is not TripStatus.ACTIVE:
            raise ValueError("Voting requires an ACTIVE trip")
        eligible = frozenset(eligible_voters)
        if self.protagonist_id in eligible or voter_id == self.protagonist_id:
            raise ValueError("The protagonist cannot be an eligible voter")
        if voter_id not in eligible:
            raise ValueError("Voter is not eligible for this episode")
        if self._eligible_voters is not None and eligible != self._eligible_voters:
            raise ValueError("Eligible voters cannot change during voting")
        if self.has_vote_from(voter_id):
            raise ValueError("User has already voted on this episode")
        if any(vote.id == vote_id for vote in self._votes.values()):
            raise ValueError("Vote identity is already in use")
        vote = Vote(vote_id, self.id, voter_id, value)
        self._eligible_voters = eligible
        self._votes[voter_id] = vote
        if self._votes.keys() == eligible:
            self._score = Decimal(
                sum(recorded.value.value for recorded in self._votes.values())
            ) / Decimal(len(self._votes))
            self._status = EpisodeStatus.COMPLETED
        return vote

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
