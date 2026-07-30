from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from data_control_service.contracts.enums import DataTarget, Operation
from data_control_service.domain.policies import ResourceDefinition, ResourceMapping
from data_control_service.infrastructure.persistence.models.resource_mapping import (
    ResourceMappingModel,
)
from data_control_service.ports.resource_mapping_repository import ResourceMappingRepository


class SQLAlchemyResourceMappingRepository(ResourceMappingRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def get_mapping(
        self,
        *,
        tenant_id: str,
        biz_domain: str,
        target: DataTarget,
        resource_type: str,
        logical_name: str,
    ) -> ResourceMapping | None:
        raise RuntimeError("use get_mapping_async for SQLAlchemyResourceMappingRepository")

    async def get_mapping_async(
        self,
        *,
        tenant_id: str,
        biz_domain: str,
        target: DataTarget,
        resource_type: str,
        logical_name: str,
    ) -> ResourceMapping | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ResourceMappingModel)
                .where(
                    ResourceMappingModel.tenant_id == tenant_id,
                    ResourceMappingModel.biz_domain == biz_domain,
                    ResourceMappingModel.target == target.value,
                    ResourceMappingModel.resource_type == resource_type,
                    ResourceMappingModel.resource_name == logical_name,
                    ResourceMappingModel.enabled.is_(True),
                )
                .order_by(ResourceMappingModel.version.desc())
                .limit(1)
            )
            model = result.scalar_one_or_none()
        if model is None:
            return None
        operations = frozenset(Operation(item) for item in model.allowed_operations)
        if DataTarget(model.target) == DataTarget.REDIS:
            config = dict(model.physical_config or {})
            return ResourceMapping(
                tenant_id=model.tenant_id,
                biz_domain=model.biz_domain,
                definition=ResourceDefinition(
                    resource_type=model.resource_type,
                    logical_name=model.resource_name,
                    target=DataTarget.REDIS,
                    allowed_operations=operations,
                    read_permission=f"data:{model.resource_name}:read",
                    write_permission=f"data:{model.resource_name}:write",
                    high_risk_operations=frozenset(
                        {Operation.DELETE, Operation.LOCK, Operation.UNLOCK}
                    ),
                    data_constraints={
                        "default_ttl_seconds": config.get("default_ttl_seconds"),
                        "max_ttl_seconds": config.get("max_ttl_seconds"),
                        "lock_default_ttl_seconds": config.get("lock_default_ttl_seconds"),
                        "lock_max_ttl_seconds": config.get("lock_max_ttl_seconds"),
                        "value_type": config.get("value_type", "JSON"),
                        "max_value_bytes": config.get("max_value_bytes"),
                        "allow_permanent_keys": config.get("allow_permanent_keys", False),
                    },
                ),
                physical_mapping={
                    "key_prefix": config.get("key_prefix", model.physical_schema),
                    "resource_name": model.resource_name,
                    "default_ttl_seconds": config.get("default_ttl_seconds"),
                    "max_ttl_seconds": config.get("max_ttl_seconds"),
                    "lock_default_ttl_seconds": config.get("lock_default_ttl_seconds"),
                    "lock_max_ttl_seconds": config.get("lock_max_ttl_seconds"),
                    "value_type": config.get("value_type", "JSON"),
                    "max_value_bytes": config.get("max_value_bytes"),
                    "allow_permanent_keys": config.get("allow_permanent_keys", False),
                },
            )
        if DataTarget(model.target) == DataTarget.MINIO:
            config = dict(model.physical_config or {})
            return ResourceMapping(
                tenant_id=model.tenant_id,
                biz_domain=model.biz_domain,
                definition=ResourceDefinition(
                    resource_type=model.resource_type,
                    logical_name=model.resource_name,
                    target=DataTarget.MINIO,
                    allowed_operations=operations,
                    read_permission=f"data:{model.resource_name}:read",
                    write_permission=f"data:{model.resource_name}:write",
                    high_risk_operations=frozenset({Operation.DELETE}),
                    data_constraints={
                        "allowed_content_types": config.get("allowed_content_types", []),
                        "allowed_extensions": config.get("allowed_extensions", []),
                        "max_object_size_bytes": config.get("max_object_size_bytes"),
                        "metadata_allowlist": config.get("metadata_allowlist", []),
                    },
                ),
                physical_mapping={
                    "bucket_name": config.get("bucket_name", model.physical_schema),
                    "object_prefix_template": config.get("object_prefix_template"),
                    "allowed_content_types": config.get("allowed_content_types", []),
                    "allowed_extensions": config.get("allowed_extensions", []),
                    "max_object_size_bytes": config.get("max_object_size_bytes"),
                    "allow_overwrite": config.get("allow_overwrite", False),
                    "allow_presigned_upload": config.get("allow_presigned_upload", True),
                    "allow_presigned_download": config.get("allow_presigned_download", True),
                    "default_upload_url_ttl_seconds": config.get("default_upload_url_ttl_seconds"),
                    "default_download_url_ttl_seconds": config.get(
                        "default_download_url_ttl_seconds"
                    ),
                    "max_presigned_ttl_seconds": config.get("max_presigned_ttl_seconds"),
                    "metadata_allowlist": config.get("metadata_allowlist", []),
                },
            )
        write_operations = {
            Operation.CREATE,
            Operation.UPDATE,
            Operation.UPSERT,
            Operation.DELETE,
            Operation.BATCH,
        }
        return ResourceMapping(
            tenant_id=model.tenant_id,
            biz_domain=model.biz_domain,
            definition=ResourceDefinition(
                resource_type=model.resource_type,
                logical_name=model.resource_name,
                target=DataTarget(model.target),
                allowed_operations=operations,
                read_permission=f"data:{model.resource_name}:read",
                write_permission=f"data:{model.resource_name}:write",
                high_risk_operations=frozenset(operations & write_operations),
                data_constraints={
                    "field_allowlist": model.field_allowlist,
                    "filter_allowlist": model.filter_allowlist,
                    "sort_allowlist": model.sort_allowlist,
                    "max_page_size": model.max_page_size,
                    "upsert_conflict_columns": model.upsert_conflict_columns,
                    "primary_key": model.primary_key_column,
                },
            ),
            physical_mapping={
                "schema": model.physical_schema,
                "table": model.physical_table,
                "logical_table": model.physical_table,
                "primary_key": model.primary_key_column,
                "tenant_column": model.tenant_column,
                "biz_domain_column": model.biz_domain_column,
                "field_allowlist": model.field_allowlist,
                "filter_allowlist": model.filter_allowlist,
                "sort_allowlist": model.sort_allowlist,
                "max_page_size": model.max_page_size,
                "upsert_conflict_columns": model.upsert_conflict_columns,
            },
        )

    async def health(self) -> dict[str, str]:
        async with self._session_factory() as session:
            await session.execute(select(ResourceMappingModel.id).limit(1))
        return {"status": "ok", "backend": "postgresql"}
