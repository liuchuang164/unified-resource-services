from redis.asyncio import ConnectionPool, Redis

from data_control_service.config.settings import Settings
from data_control_service.domain.exceptions import DataControlError


class RedisManager:
    def __init__(self, settings: Settings) -> None:
        if not settings.redis_url:
            raise DataControlError("CONFIGURATION_INVALID", "REDIS_URL is required")
        self._settings = settings
        self._pool: ConnectionPool | None = None
        self._client: Redis | None = None
        self._create_client()

    def _create_client(self) -> None:
        if self._client is not None:
            return
        connection_options = {
            "username": self._settings.redis_username or None,
            "password": self._settings.redis_password or None,
            "max_connections": self._settings.redis_max_connections,
            "socket_connect_timeout": self._settings.redis_socket_connect_timeout_seconds,
            "socket_timeout": self._settings.redis_socket_timeout_seconds,
            "health_check_interval": self._settings.redis_health_check_interval_seconds,
            "decode_responses": True,
        }
        self._pool = ConnectionPool.from_url(
            self._settings.redis_url or "",
            **connection_options,
        )
        self._client = Redis(connection_pool=self._pool)

    async def start(self) -> None:
        self._create_client()

    def client(self) -> Redis:
        if self._client is None:
            raise DataControlError("CONFIGURATION_INVALID", "RedisManager was not started")
        return self._client

    async def ping(self) -> dict[str, str]:
        await self.start()
        ok = await self.client().ping()
        return {"status": "ok" if ok else "error"}

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        if self._pool is not None:
            await self._pool.aclose()
        self._client = None
        self._pool = None

    @staticmethod
    def redact_url(url: str | None) -> str:
        if not url:
            return ""
        if "@" not in url:
            return url
        scheme, rest = url.split("://", 1)
        return f"{scheme}://***@{rest.split('@', 1)[1]}"
