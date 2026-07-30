from __future__ import annotations

import argparse
import asyncio
import json

from data_control_service.application.object_cleanup_service import ObjectCleanupService
from data_control_service.config.settings import Settings
from data_control_service.infrastructure.persistence.database import DatabaseManager
from data_control_service.infrastructure.persistence.repositories.sqlalchemy_object_record import (
    SQLAlchemyObjectRecordRepository,
)


async def main() -> None:
    parser = argparse.ArgumentParser(description="cleanup MinIO object metadata")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    settings = Settings()
    if not settings.control_database_url:
        raise SystemExit("CONTROL_DATABASE_URL is required")
    manager = DatabaseManager(settings.control_database_url, settings, name="control")
    try:
        service = ObjectCleanupService(SQLAlchemyObjectRecordRepository(manager.session_factory))
        result = await service.cleanup_pending_uploads(
            tenant_id="tenant_demo",
            biz_domain="demo",
            resource_type="OBJECT_ASSET",
            resource_name="asset",
            limit=args.limit,
            dry_run=args.dry_run,
        )
        print(json.dumps(result.__dict__, ensure_ascii=False))
    finally:
        await manager.close()


if __name__ == "__main__":
    asyncio.run(main())
