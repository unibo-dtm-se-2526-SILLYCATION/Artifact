"""HTTP input validation and JSON representation, independent of persistence."""

from datetime import date
from decimal import Decimal
import json

import pytest
from pydantic import ValidationError

from sillycation.adapters.api.schemas.requests import (
    CastVoteRequest,
    CreateEpisodeRequest,
    CreateTripRequest,
    EditEpisodeRequest,
    LoginRequest,
    RegisterUserRequest,
    RequestJoinTripRequest,
)
from sillycation.adapters.api.schemas.responses import RankingEntryResponse


@pytest.mark.parametrize("value", range(1, 6))
def test_vote_accepts_only_valid_integers(value: int) -> None:
    assert (
        CastVoteRequest.model_validate_json(json.dumps({"value": value})).value == value
    )


@pytest.mark.parametrize("value", [True, False, "3", 3.0, 2.5, 0, 6, -1, None, [], {}])
def test_invalid_json_vote_is_not_coerced(value) -> None:
    with pytest.raises(ValidationError):
        CastVoteRequest.model_validate_json(json.dumps({"value": value}))


def test_decimal_vote_is_not_coerced() -> None:
    with pytest.raises(ValidationError):
        CastVoteRequest.model_validate({"value": Decimal("3")})


@pytest.mark.parametrize("body", [{}, {"value": 3, "voter_id": "spoofed"}])
def test_vote_requires_value_and_rejects_actor_fields(body) -> None:
    with pytest.raises(ValidationError):
        CastVoteRequest.model_validate(body)


def test_vote_json_schema_describes_integer_bounds() -> None:
    value = CastVoteRequest.model_json_schema()["properties"]["value"]
    assert value["type"] == "integer"
    assert value["minimum"] == 1
    assert value["maximum"] == 5


def test_trip_request_parses_iso_dates_without_changing_text() -> None:
    request = CreateTripRequest.model_validate_json(
        '{"name":" Roma ","start_date":"2026-11-10","end_date":"2026-11-12"}'
    )
    assert request.start_date == date(2026, 11, 10)
    assert request.end_date == date(2026, 11, 12)
    assert request.name == " Roma "
    assert request.description is None
    assert request.model_dump(mode="json")["start_date"] == "2026-11-10"


@pytest.mark.parametrize(
    "changes",
    [
        {"start_date": "not-a-date"},
        {"end_date": None},
        {"name": "  "},
        {"name": 7},
        {"description": 7},
        {"creator_id": "spoofed"},
        {"id": "client-generated"},
        {"status": "ACTIVE"},
        {"invitation_code": "client-generated"},
    ],
)
def test_trip_rejects_invalid_or_server_owned_fields(changes) -> None:
    body = {"name": "Roma", "start_date": "2026-11-10", "end_date": "2026-11-12"}
    with pytest.raises(ValidationError):
        CreateTripRequest.model_validate({**body, **changes})


def test_date_order_is_left_to_the_existing_use_case() -> None:
    request = CreateTripRequest.model_validate(
        {"name": "Roma", "start_date": "2026-11-12", "end_date": "2026-11-10"}
    )
    assert request.start_date > request.end_date


@pytest.mark.parametrize("schema", [CreateEpisodeRequest, EditEpisodeRequest])
def test_episode_contract_preserves_opaque_protagonist_id(schema) -> None:
    request = schema.model_validate(
        {
            "title": "Lost passport",
            "description": "At the hotel",
            "date": "2026-11-10",
            "protagonist_id": "user-not-a-uuid",
        }
    )
    assert request.protagonist_id == "user-not-a-uuid"
    assert request.date == date(2026, 11, 10)
    with pytest.raises(ValidationError):
        schema.model_validate({**request.model_dump(), "author_id": "spoofed"})
    with pytest.raises(ValidationError):
        schema.model_validate({**request.model_dump(), "title": " "})
    with pytest.raises(ValidationError):
        schema.model_validate({"title": "Partial update"})


@pytest.mark.parametrize("code", ["", "  ", None, 123])
def test_join_request_requires_text_code(code) -> None:
    with pytest.raises(ValidationError):
        RequestJoinTripRequest.model_validate({"invitation_code": code})


def test_join_code_is_not_silently_normalized() -> None:
    request = RequestJoinTripRequest(invitation_code=" AbC-123 ")
    assert request.invitation_code == " AbC-123 "


@pytest.mark.parametrize("schema", [RegisterUserRequest, LoginRequest])
def test_credentials_are_redacted_and_exact_password_is_preserved(schema) -> None:
    body = {"username": "Chiara", "password": " secret "}
    if schema is RegisterUserRequest:
        body["email"] = "chiara@example.org"
    request = schema.model_validate(body)
    assert request.password.get_secret_value() == " secret "
    assert " secret " not in repr(request)
    assert " secret " not in request.model_dump_json()
    for invalid in (None, 123, b"secret", ""):
        with pytest.raises(ValidationError):
            schema.model_validate({**body, "password": invalid})


@pytest.mark.parametrize("field", ["username", "email", "password"])
def test_registration_requires_all_fields(field: str) -> None:
    body = {"username": "Chiara", "email": "chiara@example.org", "password": "secret"}
    del body[field]
    with pytest.raises(ValidationError):
        RegisterUserRequest.model_validate(body)


def test_decimal_score_is_serialized_without_float_rounding() -> None:
    score = Decimal("1.234567890123456789012345678")
    response = RankingEntryResponse(user_id="user", score=score, position=1)
    assert json.loads(response.model_dump_json())["score"] == str(score)
    assert response.score == score
