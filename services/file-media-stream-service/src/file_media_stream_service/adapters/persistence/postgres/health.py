from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class PostgresHealth:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def check(self) -> bool:
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
