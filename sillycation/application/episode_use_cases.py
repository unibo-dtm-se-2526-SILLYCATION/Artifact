"""Episode creation, draft editing/deletion and submission through repository ports.

The caller supplies authenticated actor identities and allocated EpisodeIds.
LookupError denotes missing aggregates; EpisodeApplicationError denotes
application preconditions. Domain ValueError and repository failures propagate.
"""

from datetime import date as Date

from sillycation.application.ports.repositories import EpisodeRepository, TripRepository
from sillycation.domain.episode import Episode
from sillycation.domain.identifiers import EpisodeId, TripId, UserId
from sillycation.domain.trip import Participant, Trip, TripStatus


class EpisodeApplicationError(Exception):
    """An Episode workflow fails an application precondition."""


def _get_trip(trips: TripRepository, trip_id: TripId) -> Trip:
    trip = trips.get_by_id(trip_id)
    if trip is None:
        raise LookupError("Trip not found")
    return trip


def _get_episode(episodes: EpisodeRepository, episode_id: EpisodeId) -> Episode:
    episode = episodes.get_by_id(episode_id)
    if episode is None:
        raise LookupError("Episode not found")
    return episode


def _require_active(trip: Trip) -> None:
    if trip.status is not TripStatus.ACTIVE:
        raise EpisodeApplicationError("Trip must be ACTIVE")


def _require_participant(trip: Trip, user_id: UserId) -> None:
    if Participant(trip.id, user_id) not in trip.participants:
        raise EpisodeApplicationError("User must be a participant of this Trip")


def _require_date(trip: Trip, date: Date) -> None:
    if not trip.period.start_date <= date <= trip.period.end_date:
        raise EpisodeApplicationError("Episode date must fall within the Trip period")


class CreateEpisode:
    def __init__(self, trips: TripRepository, episodes: EpisodeRepository) -> None:
        self._trips = trips
        self._episodes = episodes

    def execute(
        self,
        *,
        episode_id: EpisodeId,
        trip_id: TripId,
        author_id: UserId,
        protagonist_id: UserId,
        title: str,
        description: str,
        date: Date,
    ) -> Episode:
        """Create a DRAFT after cross-aggregate checks (FR-09, model section 20.2).

        The identity lookup is preliminary, not an atomic uniqueness guarantee.
        """
        if self._episodes.get_by_id(episode_id) is not None:
            raise EpisodeApplicationError("Episode identity already exists")
        trip = _get_trip(self._trips, trip_id)
        _require_active(trip)
        _require_participant(trip, author_id)
        _require_participant(trip, protagonist_id)
        _require_date(trip, date)
        episode = Episode(
            episode_id, trip.id, author_id, protagonist_id, title, description, date
        )
        return self._episodes.save(episode)


class EditEpisode:
    def __init__(self, trips: TripRepository, episodes: EpisodeRepository) -> None:
        self._trips = trips
        self._episodes = episodes

    def execute(
        self,
        *,
        episode_id: EpisodeId,
        requested_by: UserId,
        title: str,
        description: str,
        date: Date,
        protagonist_id: UserId,
    ) -> Episode:
        """Replace draft fields; author authorization and DRAFT belong to Episode."""
        episode = _get_episode(self._episodes, episode_id)
        trip = _get_trip(self._trips, episode.trip_id)
        _require_active(trip)
        _require_participant(trip, protagonist_id)
        _require_date(trip, date)
        episode.edit(
            requested_by=requested_by,
            title=title,
            description=description,
            date=date,
            protagonist_id=protagonist_id,
        )
        return self._episodes.save(episode)


class DeleteEpisode:
    def __init__(self, trips: TripRepository, episodes: EpisodeRepository) -> None:
        self._trips = trips
        self._episodes = episodes

    def execute(self, *, episode_id: EpisodeId, requested_by: UserId) -> None:
        """Remove an author's draft after validating its owning Trip.

        Repository failures propagate, including disappearance during deletion.
        These preliminary checks do not provide concurrency guarantees.
        """
        episode = _get_episode(self._episodes, episode_id)
        trip = _get_trip(self._trips, episode.trip_id)
        _require_active(trip)
        episode.ensure_deletable(requested_by=requested_by)
        self._episodes.delete(episode.id)


class SubmitEpisode:
    def __init__(self, trips: TripRepository, episodes: EpisodeRepository) -> None:
        self._trips = trips
        self._episodes = episodes

    def execute(self, *, episode_id: EpisodeId, requested_by: UserId) -> Episode:
        """Submit using the owning Trip's current status; the domain opens voting."""
        episode = _get_episode(self._episodes, episode_id)
        trip = _get_trip(self._trips, episode.trip_id)
        episode.submit(requested_by=requested_by, trip_status=trip.status)
        return self._episodes.save(episode)
