"""FastAPI composition entry point with lifespan-scoped persistence."""

from contextlib import asynccontextmanager
from functools import partial
from typing import AsyncIterator, Optional

from fastapi import FastAPI
from sqlalchemy.engine import make_url

from sillycation.adapters.api.dependencies import PersistenceDependencies
from sillycation.adapters.api.errors import register_exception_handlers
from sillycation.adapters.api.router import router
from sillycation.adapters.api.routes.users import router as users_router
from sillycation.adapters.passwords import Argon2PasswordHasher
from sillycation.adapters.persistence.database import (
    create_database,
    resolve_database_url,
)
from sillycation.adapters.persistence.episode_repository import (
    SqlAlchemyEpisodeRepository,
)
from sillycation.adapters.persistence.trip_repository import SqlAlchemyTripRepository
from sillycation.adapters.persistence.unit_of_work import SqliteUnitOfWork
from sillycation.adapters.persistence.user_repository import SqlAlchemyUserRepository


def create_app(*, database_url: Optional[str] = None) -> FastAPI:
    """Create an independent application with the versioned API router.

    Run with ``uvicorn sillycation.adapters.api.app:create_app --factory``.
    The SQLite file URL can be supplied here or via SILLYCATION_DATABASE_URL.
    The persistence adapter supplies the default when neither is set.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        url = resolve_database_url(database_url)
        parsed_url = make_url(url)
        if parsed_url.get_backend_name() != "sqlite":
            raise ValueError("The FastAPI application requires a SQLite URL")
        if (
            not parsed_url.database
            or parsed_url.database in (":memory:", "file::memory:")
            or parsed_url.query.get("mode") == "memory"
        ):
            raise ValueError(
                "The FastAPI application requires a file-backed SQLite URL"
            )
        engine = create_database(url)
        try:
            password_hasher = Argon2PasswordHasher()
            app.state.persistence = PersistenceDependencies(
                users=SqlAlchemyUserRepository(engine),
                trips=SqlAlchemyTripRepository(engine),
                episodes=SqlAlchemyEpisodeRepository(engine),
                unit_of_work_factory=partial(SqliteUnitOfWork, engine),
            )
            app.state.password_hasher = password_hasher
            try:
                yield
            finally:
                del app.state.password_hasher
                del app.state.persistence
        finally:
            engine.dispose()

    app = FastAPI(title="Sillycation API", version="0.1.0", lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(router)
    app.include_router(users_router, prefix=router.prefix)
    return app
