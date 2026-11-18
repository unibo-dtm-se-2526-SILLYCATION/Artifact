"""Protected episode/vote operations; not mounted by the public factory.

Actor identity and generated IDs are server dependencies. Existing use cases
enforce membership, authorship, lifecycle, dates and voting rules. Submission
opens voting and the last eligible vote completes the episode automatically.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from sillycation.adapters.api.dependencies import (
    get_authenticated_user_id,
    get_cast_vote,
    get_create_episode,
    get_delete_episode,
    get_edit_episode,
    get_new_episode_id,
    get_new_vote_id,
    get_submit_episode,
)
from sillycation.adapters.api.mappers import episode_response
from sillycation.adapters.api.openapi import error_responses
from sillycation.adapters.api.schemas.requests import (
    CastVoteRequest,
    CreateEpisodeRequest,
    EditEpisodeRequest,
)
from sillycation.adapters.api.schemas.responses import EpisodeResponse
from sillycation.application.episode_use_cases import (
    CreateEpisode,
    DeleteEpisode,
    EditEpisode,
    SubmitEpisode,
)
from sillycation.application.voting_use_cases import CastVote
from sillycation.domain.identifiers import EpisodeId, TripId, UserId, VoteId

router = APIRouter(tags=["episodes"], dependencies=[Depends(get_authenticated_user_id)])
AuthenticatedUserId = Annotated[UserId, Depends(get_authenticated_user_id)]


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
    use_case: Annotated[CreateEpisode, Depends(get_create_episode)],
    episode_id: Annotated[EpisodeId, Depends(get_new_episode_id)],
) -> EpisodeResponse:
    return episode_response(
        use_case.execute(
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
    use_case: Annotated[EditEpisode, Depends(get_edit_episode)],
) -> EpisodeResponse:
    return episode_response(
        use_case.execute(
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
    use_case: Annotated[DeleteEpisode, Depends(get_delete_episode)],
) -> Response:
    use_case.execute(episode_id=EpisodeId(episode_id), requested_by=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/episodes/{episode_id}/submit",
    response_model=EpisodeResponse,
    responses=error_responses("not_authorized", "not_found", "invalid_state"),
)
def submit_episode(
    episode_id: str,
    actor: AuthenticatedUserId,
    use_case: Annotated[SubmitEpisode, Depends(get_submit_episode)],
) -> EpisodeResponse:
    return episode_response(
        use_case.execute(episode_id=EpisodeId(episode_id), requested_by=actor)
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
    use_case: Annotated[CastVote, Depends(get_cast_vote)],
    vote_id: Annotated[VoteId, Depends(get_new_vote_id)],
) -> EpisodeResponse:
    return episode_response(
        use_case.execute(
            episode_id=EpisodeId(episode_id),
            vote_id=vote_id,
            voter_id=actor,
            value=body.value,
        )
    )
