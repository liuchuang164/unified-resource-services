from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from data_control_service.api.dependencies import close_database_managers
from data_control_service.api.exception_handlers import register_exception_handlers
from data_control_service.api.routes.data import router as data_router
from data_control_service.api.routes.health import router as health_router
from data_control_service.config.logging import configure_logging
from data_control_service.config.settings import Settings
from data_control_service.domain.exceptions import DataControlError


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    if settings.app_env.lower() == "production" and settings.auth_provider == "development":
        raise DataControlError(
            "CONFIGURATION_INVALID",
            "DevelopmentAuthProvider cannot be enabled in production",
        )
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await close_database_managers()

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(data_router)
    return app
