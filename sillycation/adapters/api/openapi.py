"""Per-operation error documentation, independent of routing/business behavior.

Callers enumerate errors from their actual use case. FastAPI validation stays
separate from application InvalidData at 422. Protected operations additionally
document their current fail-closed 503, without inventing authentication/401.
"""

from typing import Any, Union

from sillycation.adapters.api.errors import ERROR_CONTRACTS
from sillycation.adapters.api.schemas.errors import (
    ApplicationErrorResponse,
    ErrorCode,
    ProtectedAPIUnavailableResponse,
    RegistrationValidationErrorResponse,
    RequestValidationErrorResponse,
)


def error_responses(
    *codes: ErrorCode,
    protected: bool = True,
    registration: bool = False,
) -> dict[Union[int, str], dict[str, Any]]:
    """Build documentation only: no handlers, dependencies or routes are changed.

    Fixed public examples reuse the same contract as the runtime handlers. No
    example contains credential values, raw exception text or database details.
    """
    responses: dict[Union[int, str], dict[str, Any]] = {}
    contracts = {
        code: (status_code, message)
        for _, status_code, code, message in ERROR_CONTRACTS
    }
    for code in codes:
        status_code, message = contracts[code]
        response = responses.setdefault(
            status_code,
            {
                "description": "Application error (error object).",
                "model": ApplicationErrorResponse,
                "content": {"application/json": {"examples": {}}},
            },
        )
        response["content"]["application/json"]["examples"][code] = {
            "summary": code,
            "value": {"error": {"code": code, "message": message}},
        }

    validation_example = {
        "summary": "Request validation (detail array; not an application error)",
        "value": {
            "detail": [
                {"type": "missing", "loc": ["body", "field"], "msg": "Field required"}
            ]
        },
    }
    validation_model: Any = (
        RegistrationValidationErrorResponse
        if registration
        else RequestValidationErrorResponse
    )
    if "invalid_data" in codes:
        response = responses[422]
        response["description"] = (
            "Invalid application data (error) or request validation failure (detail)."
        )
        response["model"] = (
            Union[ApplicationErrorResponse, RegistrationValidationErrorResponse]
            if registration
            else Union[ApplicationErrorResponse, RequestValidationErrorResponse]
        )
        response["content"]["application/json"]["examples"]["request_validation"] = (
            validation_example
        )
    else:
        responses[422] = {
            "description": "Request validation failure (detail array).",
            "model": validation_model,
            "content": {
                "application/json": {
                    "examples": {"request_validation": validation_example}
                }
            },
        }
    if registration:
        responses[422]["description"] += (
            " Rejected input and context values are omitted from registration errors."
        )
    if protected:
        responses[503] = {
            "description": "Protected operations are unavailable until secure identity is configured.",
            "model": ProtectedAPIUnavailableResponse,
            "content": {
                "application/json": {
                    "example": {"detail": "Protected API is not configured"}
                }
            },
        }
    return responses
