from asyncio import current_task

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_scoped_session,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(
    database_url: str, pool_size: int, max_overflow: int, connect_timeout_seconds: float
) -> AsyncEngine:
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        connect_args={"timeout": connect_timeout_seconds},
    )


def create_session_registry(engine: AsyncEngine) -> async_scoped_session[AsyncSession]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return async_scoped_session(factory, scopefunc=current_task)
