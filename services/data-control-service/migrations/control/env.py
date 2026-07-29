import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from data_control_service.infrastructure.persistence.models.access_audit import (
    AccessAuditLogModel,
)
from data_control_service.infrastructure.persistence.models.audit_outbox import AuditOutboxModel
from data_control_service.infrastructure.persistence.models.base import Base
from data_control_service.infrastructure.persistence.models.change_audit import (
    ChangeAuditLogModel,
)
from data_control_service.infrastructure.persistence.models.idempotency import (
    IdempotencyRecordModel,
)
from data_control_service.infrastructure.persistence.models.policy_binding import (
    PolicyBindingModel,
)
from data_control_service.infrastructure.persistence.models.resource_mapping import (
    ResourceMappingModel,
)

_CONTROL_MODELS = (
    AccessAuditLogModel,
    AuditOutboxModel,
    ChangeAuditLogModel,
    IdempotencyRecordModel,
    PolicyBindingModel,
    ResourceMappingModel,
)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    return os.getenv("CONTROL_DATABASE_MIGRATION_URL") or config.get_main_option("sqlalchemy.url")


def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
    if type_ == "schema":
        return name in {None, "control_plane"}
    schema = parent_names.get("schema_name")
    return schema in {None, "control_plane"}


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=include_name,
        version_table_schema="control_plane",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS control_plane"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
            version_table_schema="control_plane",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
