from typing import cast

from redis.asyncio import Redis


def create_redis_client(url: str, socket_timeout_seconds: float) -> Redis:
    return cast(
        Redis,
        Redis.from_url(
            url,
            socket_timeout=socket_timeout_seconds,
            socket_connect_timeout=socket_timeout_seconds,
            decode_responses=True,
            health_check_interval=30,
        ),
    )
