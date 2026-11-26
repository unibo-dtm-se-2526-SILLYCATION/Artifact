"""Exercise the production composition through routes mounted only for tests."""

from pathlib import Path
from typing import Annotated, Callable

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import Engine, event

from sillycation.adapters.api.app import create_app
from sillycation.adapters.api.dependencies import (
    get_episode_repository,
    get_trip_repository,
    get_unit_of_work_factory,
    get_user_repository,
)
from sillycation.adapters.persistence.database import create_database
from sillycation.application.ports.repositories import (
    EpisodeRepository,
    TripRepository,
    UserRepository,
)
from sillycation.application.ports.unit_of_work import UnitOfWork
from sillycation.domain.identifiers import EpisodeId, TripId, UserId
from sillycation.domain.user import User


def add_probe_routes(app: FastAPI) -> None:
    @app.post("/probe")
    def write(
        factory: Annotated[Callable[[], UnitOfWork], Depends(get_unit_of_work_factory)],
    ) -> None:
        with factory() as unit:
            unit.users.save(
                User(UserId("anna"), "Anna", "anna@example.org", "test-hash")
            )
            unit.commit()

    @app.get("/probe")
    def read(
        users: Annotated[UserRepository, Depends(get_user_repository)],
        trips: Annotated[TripRepository, Depends(get_trip_repository)],
        episodes: Annotated[EpisodeRepository, Depends(get_episode_repository)],
    ) -> dict[str, bool]:
        return {
            "user": users.get_by_id(UserId("anna")) is not None,
            "trip": trips.get_by_id(TripId("missing")) is not None,
            "episode": episodes.get_by_id(EpisodeId("missing")) is not None,
        }


def test_lifespan_initializes_and_disposes_sqlite_and_preserves_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "explicit.db"
    url = f"sqlite:///{database}"
    disposed: list[Engine] = []

    def tracked_database(configured_url: str) -> Engine:
        engine = create_database(configured_url)
        event.listen(engine, "engine_disposed", disposed.append)
        return engine

    monkeypatch.setattr(
        "sillycation.adapters.api.app.create_database", tracked_database
    )
    app = create_app(database_url=url)
    add_probe_routes(app)
    assert not database.exists()
    with TestClient(app) as client:
        assert database.exists()
        assert client.post("/probe").status_code == 200
        assert client.get("/probe").json() == {
            "user": True,
            "trip": False,
            "episode": False,
        }
        assert disposed == []
    assert len(disposed) == 1
    assert not hasattr(app.state, "persistence")

    reopened = create_app(database_url=url)
    add_probe_routes(reopened)
    environment_app = create_app()
    add_probe_routes(environment_app)
    with (
        TestClient(reopened) as client,
        TestClient(environment_app) as environment_client,
    ):
        assert client.get("/probe").json()["user"] is True
        assert environment_client.get("/probe").json()["user"] is False
        assert (tmp_path / "api.db").exists()
    assert len(disposed) == 3


@pytest.mark.parametrize("url", ["postgresql://example/db", "sqlite:///:memory:"])
def test_unsupported_database_fails_at_startup(url: str) -> None:
    app = create_app(database_url=url)
    with pytest.raises(ValueError, match="requires a .*SQLite URL"), TestClient(app):
        pytest.fail("Unsupported database started")
