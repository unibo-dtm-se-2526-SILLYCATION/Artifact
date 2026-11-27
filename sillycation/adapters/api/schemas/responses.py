"""Explicit public projections, without credentials or private aggregate data.

Dates use ISO 8601, enums their string values, and Decimal scores JSON strings
(Pydantic's default), preserving precision without conversion to binary floats.
"""

from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel

from sillycation.domain.episode import EpisodeStatus
from sillycation.domain.trip import JoinRequestStatus, TripStatus


class RegisteredUserResponse(BaseModel):
    id: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class TripSummaryResponse(BaseModel):
    id: str
    name: str
    creator_id: str
    start_date: date
    end_date: date
    status: TripStatus


class TripResponse(TripSummaryResponse):
    description: Optional[str]


class InvitationCodeResponse(BaseModel):
    invitation_code: str


class ParticipantResponse(BaseModel):
    trip_id: str
    user_id: str


class JoinRequestResponse(BaseModel):
    id: str
    trip_id: str
    user_id: str
    status: JoinRequestStatus


class EpisodeResponse(BaseModel):
    id: str
    trip_id: str
    author_id: str
    protagonist_id: str
    title: str
    description: str
    date: date
    status: EpisodeStatus
    score: Optional[Decimal]


class RankingEntryResponse(BaseModel):
    user_id: str
    score: Decimal
    position: int


class TripDashboardResponse(BaseModel):
    trip: TripResponse
    participants: list[ParticipantResponse]
    episodes: list[EpisodeResponse]
    ranking: list[RankingEntryResponse]
