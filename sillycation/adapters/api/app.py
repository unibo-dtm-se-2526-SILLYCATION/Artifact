"""FastAPI composition entry point, without database or business side effects."""

from fastapi import FastAPI

from sillycation.adapters.api.errors import register_exception_handlers
from sillycation.adapters.api.router import router


def create_app() -> FastAPI:
    """Create an independent application with the versioned API router.

    Run with ``uvicorn sillycation.adapters.api.app:create_app --factory``.
    """
    app = FastAPI(title="Sillycation API", version="0.1.0")
    register_exception_handlers(app)
    app.include_router(router)
    return app
