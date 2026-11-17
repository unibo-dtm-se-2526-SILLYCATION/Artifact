"""Request bodies for the first MVP operations.

Actor identities come from authentication, resource IDs from routes, and new IDs
from the server. Business rules involving membership, dates or lifecycle remain
in the existing use cases and domain. Unknown fields are rejected.
"""

from datetime import date
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints

NonBlankText = Annotated[str, StringConstraints(strict=True, pattern=r"\S")]


class RequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterUserRequest(RequestBody):
    username: NonBlankText
    email: NonBlankText
    password: SecretStr = Field(strict=True, min_length=1)


class LoginRequest(RequestBody):
    """Credentials only; the authentication response belongs to step 15."""

    username: NonBlankText
    password: SecretStr = Field(strict=True, min_length=1)


class CreateTripRequest(RequestBody):
    name: NonBlankText
    start_date: date
    end_date: date
    description: Optional[str] = Field(default=None, strict=True)


class RequestJoinTripRequest(RequestBody):
    invitation_code: NonBlankText


class EpisodeFields(RequestBody):
    title: NonBlankText
    description: NonBlankText
    date: date
    protagonist_id: NonBlankText


class CreateEpisodeRequest(EpisodeFields):
    pass


class EditEpisodeRequest(EpisodeFields):
    """Full replacement of draft fields, matching EditEpisode.execute."""


class CastVoteRequest(RequestBody):
    # HTTP shape validation: never coerce bool, str, float or Decimal to int.
    value: int = Field(strict=True, ge=1, le=5)
