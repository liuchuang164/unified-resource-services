from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from data_control_service.config.settings import Settings
from data_control_service.domain.exceptions import DataControlError


def redact_database_url(url: str | None) -> str:
    if not url:
        return "<unset>"
    parsed = make_url(url)
    return parsed.render_as_string(hide_password=True)


class DatabaseManager:
    def __init__(self, url: str, settings: Settings, *, name: str) -> None:
        self._url = url
        self._name = name
        connect_args = {
            "server_settings": {
                "statement_timeout": str(settings.database_statement_timeout_ms),
            },
            "timeout": settings.database_connect_timeout_seconds,
        }
        engine_options = {
            "pool_pre_ping": True,
            "connect_args": connect_args,
        }
        if settings.app_env == "test":
            engine_options["poolclass"] = NullPool
        else:
            engine_options.update(
                {
                    "pool_size": settings.database_pool_size,
                    "max_overflow": settings.database_max_overflow,
                    "pool_timeout": settings.database_pool_timeout_seconds,
                }
            )
        self.engine: AsyncEngine = create_async_engine(url, **engine_options)
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    @property
    def safe_url(self) -> str:
        return redact_database_url(self._url)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session

    async def ping(self) -> dict[str, str]:
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            return {"status": "ok", "database": self._name}
        except Exception as exc:
            raise DataControlError(
                "ADAPTER_UNAVAILABLE", f"{self._name} database unavailable"
            ) from exc

    async def close(self) -> None:
        await self.engine.dispose()


def require_database_url(value: str | None, name: str, settings: Settings) -> str:
    if not value:
        if settings.app_env in {"production", "test"}:
            raise DataControlError("CONFIGURATION_INVALID", f"{name} database url is required")
        raise DataControlError("CONFIGURATION_INVALID", f"{name} database url is not configured")
    return value
