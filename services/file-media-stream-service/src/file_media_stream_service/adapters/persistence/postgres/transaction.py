from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session


class PostgresTransactionManager:
    def __init__(self, sessions: async_scoped_session[AsyncSession]) -> None:
        self.sessions = sessions

    async def commit(self) -> None:
        await self.sessions().commit()

    async def rollback(self) -> None:
        await self.sessions().rollback()

    async def close(self) -> None:
        await self.sessions.remove()
