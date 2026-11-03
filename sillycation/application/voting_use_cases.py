"""Voting orchestration; Episode owns eligibility checks, completion and score."""

from sillycation.application.ports.repositories import EpisodeRepository, TripRepository
from sillycation.domain.episode import Episode
from sillycation.domain.identifiers import EpisodeId, UserId, VoteId
from sillycation.domain.value_objects import VoteValue


class CastVote:
    def __init__(self, trips: TripRepository, episodes: EpisodeRepository) -> None:
        self._trips = trips
        self._episodes = episodes

    def execute(
        self, *, episode_id: EpisodeId, vote_id: VoteId, voter_id: UserId, value: int
    ) -> Episode:
        """Record a vote using the owning Trip's membership and current status.

        The caller supplies an authenticated voter identity and an allocated
        VoteId. Domain ValueError and technical repository errors propagate.
        The returned Episode includes the persisted votes, status and score.
        """
        episode = self._episodes.get_by_id(episode_id)
        if episode is None:
            raise LookupError("Episode not found")
        trip = self._trips.get_by_id(episode.trip_id)
        if trip is None:
            raise LookupError("Trip not found")
        eligible_voters = {
            participant.user_id
            for participant in trip.participants
            if participant.user_id != episode.protagonist_id
        }
        episode.cast_vote(
            vote_id,
            voter_id,
            VoteValue(value),
            eligible_voters=eligible_voters,
            trip_status=trip.status,
        )
        return self._episodes.save(episode)
