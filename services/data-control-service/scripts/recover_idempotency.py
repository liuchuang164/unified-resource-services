from __future__ import annotations

import argparse
import asyncio
import json

from data_control_service.application.idempotency_recovery_service import IdempotencyRecoveryService
from data_control_service.config.settings import Settings
from data_control_service.infrastructure.persistence.database import (
    DatabaseManager,
    require_database_url,
)
from data_control_service.infrastructure.persistence.repositories import (
    SQLAlchemyIdempotencyRepository,
)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect or recover RECOVERY_REQUIRED records")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = Settings()
    control_url = require_database_url(settings.control_database_url, "control", settings)
    target_url = require_database_url(
        settings.postgresql_adapter_database_url, "postgresql target", settings
    )
    control = DatabaseManager(control_url, settings, name="control")
    target = DatabaseManager(target_url, settings, name="postgresql_adapter")
    try:
        repository = SQLAlchemyIdempotencyRepository(
            control.session_factory,
            processing_timeout_seconds=settings.idempotency_processing_timeout_seconds,
        )
        service = IdempotencyRecoveryService(
            idempotency_repository=repository,
            target_session_factory=target.session_factory,
        )
        result = await service.run_once(limit=args.limit, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await control.close()
        await target.close()


if __name__ == "__main__":
    asyncio.run(main())
