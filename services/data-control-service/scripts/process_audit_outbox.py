from __future__ import annotations

import argparse
import asyncio
import json
from uuid import uuid4

from data_control_service.application.audit_outbox_processor import AuditOutboxProcessor
from data_control_service.config.settings import Settings
from data_control_service.infrastructure.persistence.database import (
    DatabaseManager,
    require_database_url,
)
from data_control_service.infrastructure.persistence.repositories import (
    SQLAlchemyAuditOutboxRepository,
)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Process pending audit outbox events once")
    parser.add_argument("--batch-size", type=int, default=None)
    args = parser.parse_args()

    settings = Settings()
    control_url = require_database_url(settings.control_database_url, "control", settings)
    control = DatabaseManager(control_url, settings, name="control")
    try:
        repository = SQLAlchemyAuditOutboxRepository(control.session_factory)
        processor = AuditOutboxProcessor(
            outbox_repository=repository,
            audit_session_factory=control.session_factory,
            worker_id=f"audit-worker-{uuid4().hex}",
            batch_size=args.batch_size or settings.audit_outbox_batch_size,
            lock_timeout_seconds=settings.audit_outbox_lock_timeout_seconds,
        )
        result = await processor.run_once()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await control.close()


if __name__ == "__main__":
    asyncio.run(main())
