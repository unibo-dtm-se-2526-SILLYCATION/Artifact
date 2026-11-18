"""Internal FR-01 registration, not mounted by the public application.

Registration does not require an existing authenticated identity. Its new ID
is server allocated. Real repository and secure hasher providers must be wired
before activation; the route supplies neither an identity nor a hashing fallback.
"""

from typing import Annotated, Callable, Coroutine, Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from sillycation.adapters.api.dependencies import get_new_user_id, get_register_user
from sillycation.adapters.api.mappers import registered_user_response
from sillycation.adapters.api.openapi import error_responses
from sillycation.adapters.api.schemas.requests import RegisterUserRequest
from sillycation.adapters.api.schemas.responses import RegisteredUserResponse
from sillycation.application.user_use_cases import RegisterUser
from sillycation.domain.identifiers import UserId


class _RegistrationRoute(APIRoute):
    """Keep standard 422 detail fields without echoing rejected credential data.

    RequestValidationError may retain raw input even when a field uses SecretStr.
    Only this router removes input/context from public validation errors. Typed
    domain errors continue to use the existing application exception handlers.
    """

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
                            {key: item[key] for key in ("type", "loc", "msg")}
                            for item in error.errors()
                        ]
                    },
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
    use_case: Annotated[RegisterUser, Depends(get_register_user)],
    user_id: Annotated[UserId, Depends(get_new_user_id)],
) -> RegisteredUserResponse:
    return registered_user_response(
        use_case.execute(
            user_id=user_id,
            username=body.username,
            email=body.email,
            password=body.password.get_secret_value(),
        )
    )
