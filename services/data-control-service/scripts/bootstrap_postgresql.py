from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from data_control_service.config.settings import Settings
from data_control_service.infrastructure.persistence.database import DatabaseManager
from data_control_service.infrastructure.persistence.models.policy_binding import PolicyBindingModel
from data_control_service.infrastructure.persistence.models.resource_mapping import (
    ResourceMappingModel,
)


async def main() -> None:
    settings = Settings()
    if settings.app_env not in {"development", "test"}:
        raise SystemExit("bootstrap_postgresql.py is only allowed in development/test")
    url = settings.control_database_url or os.getenv("CONTROL_DATABASE_URL")
    if not url:
        raise SystemExit("CONTROL_DATABASE_URL is required")
    manager = DatabaseManager(url, settings, name="control")
    try:
        async with manager.session() as session:
            async with session.begin():
                now = datetime.now(UTC)
                mapping_exists = await session.execute(
                    select(ResourceMappingModel.id).where(
                        ResourceMappingModel.tenant_id == "tenant_demo",
                        ResourceMappingModel.biz_domain == "demo",
                        ResourceMappingModel.target == "POSTGRESQL",
                        ResourceMappingModel.resource_type == "DOCUMENT_RECORD",
                        ResourceMappingModel.resource_name == "record",
                        ResourceMappingModel.enabled.is_(True),
                    )
                )
                if mapping_exists.scalar_one_or_none() is None:
                    session.add(
                        ResourceMappingModel(
                            id=f"resmap_{uuid4().hex}",
                            tenant_id="tenant_demo",
                            biz_domain="demo",
                            target="POSTGRESQL",
                            resource_type="DOCUMENT_RECORD",
                            resource_name="record",
                            physical_schema="data_target",
                            physical_table="platform_records",
                            primary_key_column="id",
                            tenant_column="tenant_id",
                            biz_domain_column="biz_domain",
                            allowed_operations=[
                                "GET",
                                "LIST",
                                "CREATE",
                                "UPDATE",
                                "UPSERT",
                                "DELETE",
                                "BATCH",
                            ],
                            upsert_conflict_columns=["tenant_id", "biz_domain", "external_id"],
                            field_allowlist=[
                                "external_id",
                                "record_type",
                                "title",
                                "content",
                                "attributes",
                            ],
                            filter_allowlist=["external_id", "record_type"],
                            sort_allowlist=["updated_at", "external_id"],
                            max_page_size=100,
                            enabled=True,
                            version=1,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                redis_mapping_exists = await session.execute(
                    select(ResourceMappingModel.id).where(
                        ResourceMappingModel.tenant_id == "tenant_demo",
                        ResourceMappingModel.biz_domain == "demo",
                        ResourceMappingModel.target == "REDIS",
                        ResourceMappingModel.resource_type == "CACHE_ENTRY",
                        ResourceMappingModel.resource_name == "cache",
                        ResourceMappingModel.enabled.is_(True),
                    )
                )
                if redis_mapping_exists.scalar_one_or_none() is None:
                    session.add(
                        ResourceMappingModel(
                            id=f"resmap_{uuid4().hex}",
                            tenant_id="tenant_demo",
                            biz_domain="demo",
                            target="REDIS",
                            resource_type="CACHE_ENTRY",
                            resource_name="cache",
                            physical_schema="dcs",
                            physical_table="cache",
                            primary_key_column="logical_key",
                            tenant_column="tenant_id",
                            biz_domain_column="biz_domain",
                            allowed_operations=[
                                "GET",
                                "EXISTS",
                                "UPSERT",
                                "DELETE",
                                "LOCK",
                                "UNLOCK",
                            ],
                            upsert_conflict_columns=[],
                            field_allowlist=[
                                "logical_key",
                                "value",
                                "ttl_seconds",
                                "only_if_absent",
                                "only_if_present",
                                "lock_token",
                            ],
                            filter_allowlist=[],
                            sort_allowlist=[],
                            physical_config={
                                "key_prefix": "dcs",
                                "default_ttl_seconds": settings.redis_default_ttl_seconds,
                                "max_ttl_seconds": settings.redis_max_ttl_seconds,
                                "lock_default_ttl_seconds": settings.redis_lock_default_ttl_seconds,
                                "lock_max_ttl_seconds": settings.redis_lock_max_ttl_seconds,
                                "value_type": "JSON",
                                "max_value_bytes": settings.redis_max_value_bytes,
                                "allow_permanent_keys": False,
                            },
                            max_page_size=1,
                            enabled=True,
                            version=1,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                policy_exists = await session.execute(
                    select(PolicyBindingModel.id).where(
                        PolicyBindingModel.tenant_id == "tenant_demo",
                        PolicyBindingModel.biz_domain == "demo",
                        PolicyBindingModel.subject_pattern == "*",
                        PolicyBindingModel.effect == "ALLOW",
                        PolicyBindingModel.enabled.is_(True),
                    )
                )
                if policy_exists.scalar_one_or_none() is None:
                    session.add(
                        PolicyBindingModel(
                            id=f"policy_{uuid4().hex}",
                            tenant_id="tenant_demo",
                            biz_domain="demo",
                            subject_type="SERVICE",
                            subject_pattern="*",
                            role=None,
                            permission=None,
                            source=None,
                            operation=None,
                            target="POSTGRESQL",
                            resource_type="DOCUMENT_RECORD",
                            resource_name="record",
                            effect="ALLOW",
                            constraints={},
                            priority=100,
                            enabled=True,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                redis_policy_exists = await session.execute(
                    select(PolicyBindingModel.id).where(
                        PolicyBindingModel.tenant_id == "tenant_demo",
                        PolicyBindingModel.biz_domain == "demo",
                        PolicyBindingModel.target == "REDIS",
                        PolicyBindingModel.resource_type == "CACHE_ENTRY",
                        PolicyBindingModel.resource_name == "cache",
                        PolicyBindingModel.effect == "ALLOW",
                        PolicyBindingModel.enabled.is_(True),
                    )
                )
                if redis_policy_exists.scalar_one_or_none() is None:
                    session.add(
                        PolicyBindingModel(
                            id=f"policy_{uuid4().hex}",
                            tenant_id="tenant_demo",
                            biz_domain="demo",
                            subject_type="SERVICE",
                            subject_pattern="*",
                            role=None,
                            permission=None,
                            source=None,
                            operation=None,
                            target="REDIS",
                            resource_type="CACHE_ENTRY",
                            resource_name="cache",
                            effect="ALLOW",
                            constraints={},
                            priority=100,
                            enabled=True,
                            created_at=now,
                            updated_at=now,
                        )
                    )
    finally:
        await manager.close()


if __name__ == "__main__":
    asyncio.run(main())
