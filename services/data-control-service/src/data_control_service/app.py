from fastapi import FastAPI

from data_control_service.api.exception_handlers import register_exception_handlers
from data_control_service.api.routes.data import router as data_router
from data_control_service.api.routes.health import router as health_router
from data_control_service.config.logging import configure_logging
from data_control_service.config.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.state.settings = settings
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(data_router)
    return app
