"""Repository contracts from domain model specification section 15.

Lookups return None when no entity matches; queries return an empty sequence
when there are no matches, with no ordering guarantee. Save stores and returns
the entity, including its owned entities, as shown in the sequence diagrams.
Loading and saving Trip and Episode remain separate operations.
"""

from typing import Optional, Protocol, Sequence

from sillycation.domain.episode import Episode
from sillycation.domain.identifiers import EpisodeId, TripId, UserId
from sillycation.domain.trip import Trip
from sillycation.domain.user import User
from sillycation.domain.value_objects import InvitationCode


class UserRepository(Protocol):
    """Registration and user lookup (domain model section 15.1)."""

    def save(self, user: User) -> User: ...

    def get_by_id(self, user_id: UserId) -> Optional[User]: ...

    def get_by_username(self, username: str) -> Optional[User]: ...

    def get_by_email(self, email: str) -> Optional[User]: ...

    def exists_by_username(self, username: str) -> bool: ...

    def exists_by_email(self, email: str) -> bool: ...


class TripRepository(Protocol):
    """Persist Trip together with its Participants and JoinRequests (15.2)."""

    def save(self, trip: Trip) -> Trip: ...

    def get_by_id(self, trip_id: TripId) -> Optional[Trip]: ...

    def get_by_invitation_code(self, invitation_code: InvitationCode) -> Optional[Trip]:
        """Look up the code independently of the Trip's lifecycle state."""
        ...

    def find_by_participant(self, user_id: UserId) -> Sequence[Trip]:
        """Return all Trips with actual membership, excluding pending applicants."""
        ...

    def find_active_or_planned_trips_by_participant(
        self, user_id: UserId
    ) -> Sequence[Trip]:
        """Return only PLANNED or ACTIVE Trips with actual membership."""
        ...


class EpisodeRepository(Protocol):
    """Persist Episode together with its Votes (domain model section 15.3)."""

    def save(self, episode: Episode) -> Episode: ...

    def get_by_id(self, episode_id: EpisodeId) -> Optional[Episode]: ...

    def find_by_trip(self, trip_id: TripId) -> Sequence[Episode]:
        """Return the Trip's Episodes in any lifecycle state."""
        ...

    def find_unresolved_by_trip(self, trip_id: TripId) -> Sequence[Episode]:
        """Return only the Trip's DRAFT, SUBMITTED or VOTING Episodes."""
        ...
