"""Documentation models for existing error bodies; never change their runtime.

Application failures use ``error``. FastAPI input failures use ``detail`` and
may contain extra input/context fields. Registration strips those extra fields.
"""

from typing import Literal, Union

from pydantic import BaseModel, ConfigDict

ErrorCode = Literal[
    "not_authorized", "not_found", "invalid_state", "duplicate", "invalid_data"
]


class ApplicationErrorDetail(BaseModel):
    code: ErrorCode
    message: str


class ApplicationErrorResponse(BaseModel):
    error: ApplicationErrorDetail


class RegistrationValidationErrorDetail(BaseModel):
    """The registration router returns only these three safe metadata fields."""

    model_config = ConfigDict(extra="forbid")
    type: str
    loc: list[Union[str, int]]
    msg: str


class RequestValidationErrorDetail(BaseModel):
    """Standard FastAPI/Pydantic detail, including optional diagnostic fields."""

    model_config = ConfigDict(extra="allow")
    type: str
    loc: list[Union[str, int]]
    msg: str


class RequestValidationErrorResponse(BaseModel):
    detail: list[RequestValidationErrorDetail]


class RegistrationValidationErrorResponse(BaseModel):
    detail: list[RegistrationValidationErrorDetail]


class ProtectedAPIUnavailableResponse(BaseModel):
    detail: Literal["Protected API is not configured"]
