import asyncio
from dataclasses import dataclass
from typing import Protocol


class HealthCheck(Protocol):
    async def check(self) -> bool: ...


@dataclass(slots=True)
class ProductionReadiness:
    postgres: HealthCheck
    redis: HealthCheck
    minio: HealthCheck

    async def check(self) -> dict[str, str]:
        results = await asyncio.gather(
            self.postgres.check(),
            self.redis.check(),
            self.minio.check(),
            return_exceptions=True,
        )
        names = ("postgres", "redis", "minio")
        return {
            name: "ok" if result is True else "unavailable"
            for name, result in zip(names, results, strict=True)
        }
