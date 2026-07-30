from __future__ import annotations

from minio import Minio
from urllib3 import PoolManager, Timeout

from data_control_service.config.settings import Settings
from data_control_service.domain.exceptions import DataControlError
from data_control_service.infrastructure.minio.error_mapper import MinIOErrorMapper
from data_control_service.infrastructure.minio.executor import MinIOExecutor


class MinIOManager:
    def __init__(self, settings: Settings) -> None:
        if not settings.minio_endpoint:
            raise DataControlError("CONFIGURATION_INVALID", "MINIO_ENDPOINT is required")
        if not settings.minio_access_key or not settings.minio_secret_key:
            raise DataControlError("CONFIGURATION_INVALID", "MinIO credentials are required")
        self._settings = settings
        self._endpoint = settings.minio_endpoint
        self._client: Minio | None = None
        self._executor = MinIOExecutor(settings.minio_max_concurrency)
        self._create_client()

    def _create_client(self) -> None:
        if self._client is not None:
            return
        http_client = PoolManager(
            maxsize=self._settings.minio_max_concurrency,
            timeout=Timeout(
                connect=self._settings.minio_connect_timeout_seconds,
                read=self._settings.minio_read_timeout_seconds,
            ),
            retries=False,
        )
        self._client = Minio(
            self._endpoint,
            access_key=self._settings.minio_access_key,
            secret_key=self._settings.minio_secret_key,
            secure=self._settings.minio_secure,
            http_client=http_client,
        )

    async def start(self) -> None:
        self._create_client()

    def client(self) -> Minio:
        if self._client is None:
            raise DataControlError("CONFIGURATION_INVALID", "MinIOManager was not started")
        return self._client

    def executor(self) -> MinIOExecutor:
        return self._executor

    async def health(self) -> dict[str, str]:
        try:
            exists = await self._executor.run(
                lambda: self.client().bucket_exists(self._settings.minio_default_bucket)
            )
        except Exception as exc:
            raise MinIOErrorMapper.to_error(exc) from exc
        return {"status": "ok" if exists else "error"}

    async def close(self) -> None:
        await self._executor.close()
        self._client = None
