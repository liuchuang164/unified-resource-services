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
                minio_mapping_exists = await session.execute(
                    select(ResourceMappingModel.id).where(
                        ResourceMappingModel.tenant_id == "tenant_demo",
                        ResourceMappingModel.biz_domain == "demo",
                        ResourceMappingModel.target == "MINIO",
                        ResourceMappingModel.resource_type == "OBJECT_ASSET",
                        ResourceMappingModel.resource_name == "asset",
                        ResourceMappingModel.enabled.is_(True),
                    )
                )
                if minio_mapping_exists.scalar_one_or_none() is None:
                    session.add(
                        ResourceMappingModel(
                            id=f"resmap_{uuid4().hex}",
                            tenant_id="tenant_demo",
                            biz_domain="demo",
                            target="MINIO",
                            resource_type="OBJECT_ASSET",
                            resource_name="asset",
                            physical_schema=settings.minio_default_bucket,
                            physical_table="objects",
                            primary_key_column="logical_object_id",
                            tenant_column="tenant_id",
                            biz_domain_column="biz_domain",
                            allowed_operations=[
                                "GET",
                                "EXISTS",
                                "LIST",
                                "CREATE",
                                "PRESIGN_UPLOAD",
                                "UPLOAD_COMPLETE",
                                "PRESIGN_DOWNLOAD",
                                "DELETE",
                            ],
                            upsert_conflict_columns=[],
                            field_allowlist=[
                                "logical_object_id",
                                "filename",
                                "content_type",
                                "size_bytes",
                                "content_base64",
                                "content_text",
                                "metadata",
                            ],
                            filter_allowlist=["status", "content_type"],
                            sort_allowlist=["created_at", "updated_at"],
                            physical_config={
                                "bucket_name": settings.minio_default_bucket,
                                "object_prefix_template": (
                                    "tenant/{tenant_id}/{biz_domain}/{resource_name}/"
                                    "{yyyy}/{mm}/{logical_object_id}/{safe_filename}"
                                ),
                                "allowed_content_types": [
                                    item.strip()
                                    for item in settings.minio_allowed_content_types.split(",")
                                    if item.strip()
                                ],
                                "allowed_extensions": [
                                    item.strip()
                                    for item in settings.minio_allowed_extensions.split(",")
                                    if item.strip()
                                ],
                                "max_object_size_bytes": settings.minio_max_object_size_bytes,
                                "allow_overwrite": False,
                                "allow_presigned_upload": True,
                                "allow_presigned_download": True,
                                "default_upload_url_ttl_seconds": (
                                    settings.minio_default_presigned_upload_ttl_seconds
                                ),
                                "default_download_url_ttl_seconds": (
                                    settings.minio_default_presigned_download_ttl_seconds
                                ),
                                "max_presigned_ttl_seconds": (
                                    settings.minio_max_presigned_ttl_seconds
                                ),
                                "metadata_allowlist": ["description", "tags"],
                            },
                            max_page_size=100,
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
                minio_policy_exists = await session.execute(
                    select(PolicyBindingModel.id).where(
                        PolicyBindingModel.tenant_id == "tenant_demo",
                        PolicyBindingModel.biz_domain == "demo",
                        PolicyBindingModel.target == "MINIO",
                        PolicyBindingModel.resource_type == "OBJECT_ASSET",
                        PolicyBindingModel.resource_name == "asset",
                        PolicyBindingModel.effect == "ALLOW",
                        PolicyBindingModel.enabled.is_(True),
                    )
                )
                if minio_policy_exists.scalar_one_or_none() is None:
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
                            target="MINIO",
                            resource_type="OBJECT_ASSET",
                            resource_name="asset",
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
