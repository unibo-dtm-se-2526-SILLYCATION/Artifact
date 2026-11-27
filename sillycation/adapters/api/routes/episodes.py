"""Authenticated episode and vote writes through the transactional facade."""

import logging
from typing import Annotated, Any, Callable, Coroutine

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse
from fastapi.routing import APIRoute

from sillycation.adapters.api.dependencies import (
    get_authenticated_user_id,
    get_new_episode_id,
    get_new_vote_id,
    get_transactional_commands,
)
from sillycation.adapters.api.errors import credential_validation_response
from sillycation.adapters.api.mappers import episode_response
from sillycation.adapters.api.openapi import BEARER_UNAUTHORIZED, error_responses
from sillycation.adapters.api.schemas.requests import (
    CastVoteRequest,
    CreateEpisodeRequest,
    EditEpisodeRequest,
)
from sillycation.adapters.api.schemas.responses import EpisodeResponse
from sillycation.application.transactional import TransactionalCommands
from sillycation.domain.errors import SillycationError
from sillycation.domain.identifiers import EpisodeId, TripId, UserId, VoteId

logger = logging.getLogger(__name__)


class _EpisodeWriteRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError as error:
                return credential_validation_response(error)
            except (SillycationError, HTTPException):
                raise
            except Exception as error:
                logger.error("Episode write failed (%s)", type(error).__name__)
                return PlainTextResponse(
                    "Internal Server Error",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        return handle


router = APIRouter(
    tags=["episodes"],
    dependencies=[Depends(get_authenticated_user_id)],
    responses={401: BEARER_UNAUTHORIZED},
    route_class=_EpisodeWriteRoute,
)
AuthenticatedUserId = Annotated[UserId, Depends(get_authenticated_user_id)]
EpisodeCommands = Annotated[TransactionalCommands, Depends(get_transactional_commands)]


@router.post(
    "/trips/{trip_id}/episodes",
    response_model=EpisodeResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(
        "not_authorized", "not_found", "invalid_state", "duplicate", "invalid_data"
    ),
)
def create_episode(
    trip_id: str,
    body: CreateEpisodeRequest,
    actor: AuthenticatedUserId,
    commands: EpisodeCommands,
    episode_id: Annotated[EpisodeId, Depends(get_new_episode_id)],
) -> EpisodeResponse:
    return episode_response(
        commands.create_episode(
            episode_id=episode_id,
            trip_id=TripId(trip_id),
            author_id=actor,
            protagonist_id=UserId(body.protagonist_id),
            title=body.title,
            description=body.description,
            date=body.date,
        )
    )


@router.put(
    "/episodes/{episode_id}",
    response_model=EpisodeResponse,
    responses=error_responses(
        "not_authorized", "not_found", "invalid_state", "invalid_data"
    ),
)
def edit_episode(
    episode_id: str,
    body: EditEpisodeRequest,
    actor: AuthenticatedUserId,
    commands: EpisodeCommands,
) -> EpisodeResponse:
    return episode_response(
        commands.edit_episode(
            episode_id=EpisodeId(episode_id),
            requested_by=actor,
            protagonist_id=UserId(body.protagonist_id),
            title=body.title,
            description=body.description,
            date=body.date,
        )
    )


@router.delete(
    "/episodes/{episode_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses("not_authorized", "not_found", "invalid_state"),
)
def delete_episode(
    episode_id: str,
    actor: AuthenticatedUserId,
    commands: EpisodeCommands,
) -> Response:
    commands.delete_episode(episode_id=EpisodeId(episode_id), requested_by=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/episodes/{episode_id}/submit",
    response_model=EpisodeResponse,
    responses=error_responses("not_authorized", "not_found", "invalid_state"),
)
def submit_episode(
    episode_id: str,
    actor: AuthenticatedUserId,
    commands: EpisodeCommands,
) -> EpisodeResponse:
    return episode_response(
        commands.submit_episode(episode_id=EpisodeId(episode_id), requested_by=actor)
    )


@router.post(
    "/episodes/{episode_id}/votes",
    response_model=EpisodeResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(
        "not_authorized", "not_found", "invalid_state", "duplicate", "invalid_data"
    ),
)
def cast_vote(
    episode_id: str,
    body: CastVoteRequest,
    actor: AuthenticatedUserId,
    commands: EpisodeCommands,
    vote_id: Annotated[VoteId, Depends(get_new_vote_id)],
) -> EpisodeResponse:
    return episode_response(
        commands.cast_vote(
            episode_id=EpisodeId(episode_id),
            vote_id=vote_id,
            voter_id=actor,
            value=body.value,
        )
    )
