"""Public FR-01 registration with a server-allocated identity."""

import logging
from sqlite3 import IntegrityError as SQLiteIntegrityError
from typing import Annotated, Callable, Coroutine, Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import IntegrityError

from sillycation.adapters.api.dependencies import (
    get_new_user_id,
    get_transactional_commands,
)
from sillycation.adapters.api.mappers import registered_user_response
from sillycation.adapters.api.openapi import error_responses
from sillycation.adapters.api.schemas.requests import RegisterUserRequest
from sillycation.adapters.api.schemas.responses import RegisteredUserResponse
from sillycation.application.transactional import TransactionalCommands
from sillycation.domain.errors import Duplicate, SillycationError
from sillycation.domain.identifiers import UserId


logger = logging.getLogger(__name__)

_USER_UNIQUENESS_ERRORS = {
    "UNIQUE constraint failed: users.id": "SQLITE_CONSTRAINT_PRIMARYKEY",
    "UNIQUE constraint failed: users.username": "SQLITE_CONSTRAINT_UNIQUE",
    "UNIQUE constraint failed: users.email": "SQLITE_CONSTRAINT_UNIQUE",
}


def _is_user_uniqueness_violation(error: Exception) -> bool:
    if not isinstance(error, IntegrityError) or not isinstance(
        error.orig, SQLiteIntegrityError
    ):
        return False
    expected = _USER_UNIQUENESS_ERRORS.get(str(error.orig))
    # Python 3.9 and 3.10 provide the SQLite message but no extended error name.
    return (
        expected is not None
        and getattr(error.orig, "sqlite_errorname", expected) == expected
    )


class _RegistrationRoute(APIRoute):
    """Keep credentials and SQL details out of registration errors and logs."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError as error:
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    content={
                        "detail": [
                            {
                                "type": item["type"],
                                "loc": ["body"]
                                if item["type"] == "extra_forbidden"
                                else item["loc"],
                                "msg": item["msg"],
                            }
                            for item in error.errors()
                        ]
                    },
                )
            except SillycationError:
                raise
            except Exception as error:
                if _is_user_uniqueness_violation(error):
                    raise Duplicate("User already exists") from None
                logger.error("Registration failed (%s)", type(error).__name__)
                return PlainTextResponse(
                    "Internal Server Error",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        return handle


router = APIRouter(prefix="/users", tags=["users"], route_class=_RegistrationRoute)


@router.post(
    "",
    response_model=RegisteredUserResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(
        "duplicate", "invalid_data", protected=False, registration=True
    ),
)
def register_user(
    body: RegisterUserRequest,
    commands: Annotated[TransactionalCommands, Depends(get_transactional_commands)],
    user_id: Annotated[UserId, Depends(get_new_user_id)],
) -> RegisteredUserResponse:
    return registered_user_response(
        commands.register_user(
            user_id=user_id,
            username=body.username,
            email=body.email,
            password=body.password.get_secret_value(),
        )
    )
