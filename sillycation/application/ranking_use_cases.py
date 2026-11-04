"""Read participant rankings without persisting or changing game data."""

from sillycation.application.ports.repositories import EpisodeRepository, TripRepository
from sillycation.domain.identifiers import TripId, UserId
from sillycation.domain.services import RankingEntry, RankingService
from sillycation.domain.trip import Participant


class GetParticipantRanking:
    def __init__(self, trips: TripRepository, episodes: EpisodeRepository) -> None:
        self._trips = trips
        self._episodes = episodes

    def execute(
        self, *, trip_id: TripId, requested_by: UserId
    ) -> tuple[RankingEntry, ...]:
        """Read in any Trip state, using a caller-authenticated user identity.

        Position one identifies current leaders, not a declaration of final
        losers. Domain ValueError and technical repository errors propagate.
        """
        trip = self._trips.get_by_id(trip_id)
        if trip is None:
            raise LookupError("Trip not found")
        if Participant(trip.id, requested_by) not in trip.participants:
            raise PermissionError("Only Trip participants may read the ranking")
        episodes = self._episodes.find_by_trip(trip.id)
        return RankingService().calculate(trip, episodes)
