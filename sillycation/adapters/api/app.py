"""FastAPI composition entry point with lifespan-scoped persistence."""

from contextlib import asynccontextmanager
from functools import partial
import os
from time import time
from typing import AsyncIterator, Callable, Optional

from fastapi import FastAPI
from sqlalchemy.engine import make_url

from sillycation.adapters.api.authentication import HttpAuthentication
from sillycation.adapters.api.dependencies import PersistenceDependencies
from sillycation.adapters.api.errors import register_exception_handlers
from sillycation.adapters.api.jwt_tokens import JwtTokens
from sillycation.adapters.api.router import router
from sillycation.adapters.api.routes.auth import router as auth_router
from sillycation.adapters.api.routes.trip_reads import (
    public_router as trip_reads_router,
)
from sillycation.adapters.api.routes.trips import router as trip_writes_router
from sillycation.adapters.api.routes.users import router as users_router
from sillycation.adapters.passwords import Argon2PasswordHasher
from sillycation.adapters.persistence.database import (
    create_database,
    resolve_database_url,
)
from sillycation.adapters.persistence.episode_repository import (
    SqlAlchemyEpisodeRepository,
)
from sillycation.adapters.persistence.login_attempts import SqliteLoginAttempts
from sillycation.adapters.persistence.trip_repository import SqlAlchemyTripRepository
from sillycation.adapters.persistence.unit_of_work import SqliteUnitOfWork
from sillycation.adapters.persistence.user_repository import SqlAlchemyUserRepository


def create_app(
    *, database_url: Optional[str] = None, auth_clock: Callable[[], float] = time
) -> FastAPI:
    """Create an independent application with the versioned API router.

    Run with ``uvicorn sillycation.adapters.api.app:create_app --factory --no-proxy-headers``.
    The SQLite file URL can be supplied here or via SILLYCATION_DATABASE_URL.
    The persistence adapter supplies the default when neither is set.
    """

    auth_enabled = os.environ.get("SILLYCATION_AUTH_ENABLED", "0")
    if auth_enabled not in ("0", "1"):
        raise ValueError("SILLYCATION_AUTH_ENABLED must be 0 or 1")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        tokens = JwtTokens.from_environment(auth_clock) if auth_enabled == "1" else None
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
            authentication = (
                HttpAuthentication(
                    tokens, SqliteLoginAttempts(engine, auth_clock), password_hasher
                )
                if tokens is not None
                else None
            )
            app.state.persistence = PersistenceDependencies(
                users=SqlAlchemyUserRepository(engine),
                trips=SqlAlchemyTripRepository(engine),
                episodes=SqlAlchemyEpisodeRepository(engine),
                unit_of_work_factory=partial(SqliteUnitOfWork, engine),
            )
            app.state.password_hasher = password_hasher
            app.state.authentication = authentication
            try:
                yield
            finally:
                del app.state.authentication
                del app.state.password_hasher
                del app.state.persistence
        finally:
            engine.dispose()

    app = FastAPI(title="Sillycation API", version="0.1.0", lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(router)
    app.include_router(users_router, prefix=router.prefix)
    if auth_enabled == "1":
        app.include_router(auth_router, prefix=router.prefix)
        app.include_router(trip_reads_router, prefix=router.prefix)
        app.include_router(trip_writes_router, prefix=router.prefix)
    return app
