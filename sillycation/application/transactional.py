"""Typed transactional entry points; existing use cases retain all business rules.

Each command creates a fresh unit, loads its state inside the transaction and
returns only after commit and context cleanup succeed. There are no retries.
Callers must use these commands explicitly: standalone use cases and HTTP
providers are unchanged and do not acquire these concurrency guarantees.
"""

from datetime import date
from typing import Callable, Optional, TypeVar

from sillycation.application.ports.passwords import PasswordHasher
from sillycation.application.ports.unit_of_work import UnitOfWork
from sillycation.application.user_use_cases import RegisterUser
from sillycation.application.trip_use_cases import (
    CreateTrip,
    RequestJoinTrip,
    ApproveJoinRequest,
    RejectJoinRequest,
    ActivateTrip,
    CompleteTrip,
    ArchiveTrip,
)
from sillycation.application.episode_use_cases import (
    CreateEpisode,
    EditEpisode,
    DeleteEpisode,
    SubmitEpisode,
)
from sillycation.application.voting_use_cases import CastVote
from sillycation.domain.episode import Episode
from sillycation.domain.trip import Trip, JoinRequest
from sillycation.domain.identifiers import (
    UserId,
    TripId,
    JoinRequestId,
    EpisodeId,
    VoteId,
)
from sillycation.domain.value_objects import InvitationCode

Result = TypeVar("Result")


class TransactionalCommands:
    def __init__(
        self, uow_factory: Callable[[], UnitOfWork], passwords: PasswordHasher
    ) -> None:
        self._uow_factory = uow_factory
        self._passwords = passwords

    def _run(self, operation: Callable[[UnitOfWork], Result]) -> Result:
        with self._uow_factory() as uow:
            result = operation(uow)
            uow.commit()
        return result

    def register_user(
        self, *, user_id: UserId, username: str, email: str, password: str
    ) -> UserId:
        return self._run(
            lambda uow: RegisterUser(uow.users, self._passwords).execute(
                user_id=user_id, username=username, email=email, password=password
            )
        )

    def create_trip(
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
        return self._run(
            lambda uow: CreateTrip(uow.trips, uow.users).execute(
                trip_id=trip_id,
                name=name,
                creator_id=creator_id,
                start_date=start_date,
                end_date=end_date,
                invitation_code=invitation_code,
                description=description,
            )
        )

    def request_join_trip(
        self,
        *,
        invitation_code: InvitationCode,
        request_id: JoinRequestId,
        user_id: UserId,
    ) -> JoinRequest:
        return self._run(
            lambda uow: RequestJoinTrip(uow.trips).execute(
                invitation_code=invitation_code, request_id=request_id, user_id=user_id
            )
        )

    def approve_join_request(
        self, *, trip_id: TripId, request_id: JoinRequestId, requested_by: UserId
    ) -> JoinRequest:
        return self._run(
            lambda uow: ApproveJoinRequest(uow.trips).execute(
                trip_id=trip_id, request_id=request_id, requested_by=requested_by
            )
        )

    def reject_join_request(
        self, *, trip_id: TripId, request_id: JoinRequestId, requested_by: UserId
    ) -> JoinRequest:
        return self._run(
            lambda uow: RejectJoinRequest(uow.trips).execute(
                trip_id=trip_id, request_id=request_id, requested_by=requested_by
            )
        )

    def activate_trip(
        self, *, trip_id: TripId, requested_by: UserId, current_date: date
    ) -> Trip:
        return self._run(
            lambda uow: ActivateTrip(uow.trips).execute(
                trip_id=trip_id, requested_by=requested_by, current_date=current_date
            )
        )

    def complete_trip(
        self, *, trip_id: TripId, requested_by: UserId, current_date: date
    ) -> Trip:
        return self._run(
            lambda uow: CompleteTrip(uow.trips, uow.episodes).execute(
                trip_id=trip_id, requested_by=requested_by, current_date=current_date
            )
        )

    def archive_trip(self, *, trip_id: TripId, requested_by: UserId) -> Trip:
        return self._run(
            lambda uow: ArchiveTrip(uow.trips).execute(
                trip_id=trip_id, requested_by=requested_by
            )
        )

    def create_episode(
        self,
        *,
        episode_id: EpisodeId,
        trip_id: TripId,
        author_id: UserId,
        protagonist_id: UserId,
        title: str,
        description: str,
        date: date,
    ) -> Episode:
        return self._run(
            lambda uow: CreateEpisode(uow.trips, uow.episodes).execute(
                episode_id=episode_id,
                trip_id=trip_id,
                author_id=author_id,
                protagonist_id=protagonist_id,
                title=title,
                description=description,
                date=date,
            )
        )

    def edit_episode(
        self,
        *,
        episode_id: EpisodeId,
        requested_by: UserId,
        title: str,
        description: str,
        date: date,
        protagonist_id: UserId,
    ) -> Episode:
        return self._run(
            lambda uow: EditEpisode(uow.trips, uow.episodes).execute(
                episode_id=episode_id,
                requested_by=requested_by,
                title=title,
                description=description,
                date=date,
                protagonist_id=protagonist_id,
            )
        )

    def delete_episode(self, *, episode_id: EpisodeId, requested_by: UserId) -> None:
        return self._run(
            lambda uow: DeleteEpisode(uow.trips, uow.episodes).execute(
                episode_id=episode_id, requested_by=requested_by
            )
        )

    def submit_episode(self, *, episode_id: EpisodeId, requested_by: UserId) -> Episode:
        return self._run(
            lambda uow: SubmitEpisode(uow.trips, uow.episodes).execute(
                episode_id=episode_id, requested_by=requested_by
            )
        )

    def cast_vote(
        self, *, episode_id: EpisodeId, vote_id: VoteId, voter_id: UserId, value: int
    ) -> Episode:
        return self._run(
            lambda uow: CastVote(uow.trips, uow.episodes).execute(
                episode_id=episode_id, vote_id=vote_id, voter_id=voter_id, value=value
            )
        )
