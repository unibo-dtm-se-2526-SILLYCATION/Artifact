"""Login using existing credentials and issue a short-lived bearer token."""

import logging
from typing import Annotated, Callable, Coroutine, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse
from fastapi.routing import APIRoute

from sillycation.adapters.api.authentication import HttpAuthentication
from sillycation.adapters.api.dependencies import (
    UserRepositoryDependency,
    get_http_authentication,
)
from sillycation.adapters.api.errors import credential_validation_response
from sillycation.adapters.api.openapi import BEARER_UNAUTHORIZED, error_responses
from sillycation.adapters.api.schemas.requests import LoginRequest
from sillycation.adapters.api.schemas.responses import LoginResponse


logger = logging.getLogger(__name__)


class _LoginRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                response = await handler(request)
            except RequestValidationError as error:
                response = credential_validation_response(error)
            except HTTPException as error:
                error.headers = {**(error.headers or {}), "Cache-Control": "no-store"}
                raise
            except Exception as error:
                logger.error("Login failed (%s)", type(error).__name__)
                response = PlainTextResponse("Internal Server Error", status_code=500)
            response.headers["Cache-Control"] = "no-store"
            return response

        return handle


router = APIRouter(prefix="/auth", tags=["auth"], route_class=_LoginRoute)


@router.post(
    "/login",
    response_model=LoginResponse,
    responses={
        **error_responses(protected=False, credentials=True),
        401: BEARER_UNAUTHORIZED,
        429: {
            "description": "Login attempt budget exhausted.",
            "headers": {"Retry-After": {"schema": {"type": "integer"}}},
        },
    },
)
def login(
    body: LoginRequest,
    request: Request,
    users: UserRepositoryDependency,
    authentication: Annotated[HttpAuthentication, Depends(get_http_authentication)],
) -> LoginResponse:
    actor = authentication.authenticate(
        users,
        body.username,
        body.password.get_secret_value(),
        request.client.host if request.client else None,
    )
    return LoginResponse(
        access_token=authentication.tokens.issue(actor),
        expires_in=authentication.tokens.lifetime,
    )
