"""Translate only the five typed domain/application failures to public errors.

Application errors use {"error": {"code": "...", "message": "..."}}. Messages
are fixed public text: exception messages, SQL, credentials and request data are
never copied into the response. FastAPI request validation and HTTPException
handlers are unchanged. Unexpected exceptions remain server errors.
"""

from functools import partial

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from sillycation.domain.errors import (
    Duplicate,
    InvalidData,
    InvalidState,
    NotAuthorized,
    NotFound,
)


ERROR_CONTRACTS = (
    (
        NotAuthorized,
        status.HTTP_403_FORBIDDEN,
        "not_authorized",
        "Operation not permitted.",
    ),
    (NotFound, status.HTTP_404_NOT_FOUND, "not_found", "Resource not found."),
    (
        InvalidState,
        status.HTTP_409_CONFLICT,
        "invalid_state",
        "Operation not allowed in the current state.",
    ),
    (
        Duplicate,
        status.HTTP_409_CONFLICT,
        "duplicate",
        "Resource or action already exists.",
    ),
    (
        InvalidData,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "invalid_data",
        "Invalid application data.",
    ),
)


async def _application_error_response(
    request: Request,
    exc: Exception,
    *,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    # Deliberately do not inspect request or exc: neither is safe public text.
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Install handlers per application, never on generic built-in/SQL errors.

    Registration by exception class also handles subclasses through Starlette's
    exception lookup. No text matching or catch-all application handler is used.
    """
    for error_type, status_code, code, message in ERROR_CONTRACTS:
        app.add_exception_handler(
            error_type,
            partial(
                _application_error_response,
                status_code=status_code,
                code=code,
                message=message,
            ),
        )
