from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    and_,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from data_control_service.adapters.base import (
    AdapterCapabilities,
    AdapterHealth,
    AdapterTransaction,
    DataAdapter,
    mapping_from,
    reject_client_scope,
)
from data_control_service.contracts.enums import DataTarget, Operation
from data_control_service.domain.exceptions import DataControlError
from data_control_service.domain.models import AdapterCommand, AdapterResult, ExecutionContext
from data_control_service.infrastructure.persistence.errors import PostgreSQLErrorMapper

_ACTIVE_POSTGRESQL_SESSION: ContextVar[AsyncSession | None] = ContextVar(
    "active_postgresql_session", default=None
)


@dataclass
class _TableRow:
    logical_table: str
    tenant_id: str
    biz_domain: str
    primary_key: str
    record: dict[str, Any]


class _PostgresTransaction(AdapterTransaction):
    def __init__(self, adapter: "InMemoryPostgreSQLAdapter") -> None:
        self._adapter = adapter
        self._snapshot = deepcopy(adapter._rows)

    async def commit(self) -> None:
        self._snapshot = deepcopy(self._adapter._rows)

    async def rollback(self) -> None:
        self._adapter._rows = self._snapshot


class InMemoryPostgreSQLAdapter(DataAdapter):
    name = "postgresql"
    target = DataTarget.POSTGRESQL

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str, str], _TableRow] = {}
        self.execute_count = 0

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            operations=frozenset(
                {
                    Operation.GET,
                    Operation.LIST,
                    Operation.CREATE,
                    Operation.UPDATE,
                    Operation.UPSERT,
                    Operation.DELETE,
                    Operation.BATCH,
                }
            ),
            supports_transactions=True,
            supports_atomic_transaction=True,
            supports_cursor_pagination=True,
            timeout_ms=5000,
        )

    async def health(self) -> AdapterHealth:
        return AdapterHealth(status="UP", details={"adapter": self.name, "mode": "in_memory"})

    async def begin(self, context: ExecutionContext) -> AdapterTransaction:
        return _PostgresTransaction(self)

    async def execute(self, command: AdapterCommand, context: ExecutionContext) -> AdapterResult:
        self.execute_count += 1
        if command.operation not in self.capabilities().operations:
            raise DataControlError("OPERATION_NOT_SUPPORTED")
        mapping = mapping_from(command)
        table = str(mapping.physical_mapping["logical_table"])
        primary_key = str(mapping.physical_mapping["primary_key"])
        data = dict(command.validated_payload.get("data", {}))
        query = dict(command.validated_payload.get("query", {}))
        reject_client_scope(data)
        tenant_id, biz_domain = command.scope
        resource_id = command.validated_payload.get("resource_id") or data.get(primary_key)
        if (
            command.operation in {Operation.UPDATE, Operation.DELETE}
            and not resource_id
            and not query
        ):
            raise DataControlError(
                "REQUEST_SCHEMA_INVALID", "empty update/delete condition is rejected"
            )
        if command.operation == Operation.CREATE:
            if not resource_id:
                raise DataControlError("REQUEST_SCHEMA_INVALID", "primary key is required")
            key = (table, tenant_id, biz_domain, str(resource_id))
            if key in self._rows:
                raise DataControlError("DATA_CONSTRAINT_VIOLATION")
            return self._write(key, table, tenant_id, biz_domain, primary_key, data)
        if command.operation == Operation.UPSERT:
            if not resource_id:
                raise DataControlError("REQUEST_SCHEMA_INVALID", "primary key is required")
            key = (table, tenant_id, biz_domain, str(resource_id))
            return self._write(key, table, tenant_id, biz_domain, primary_key, data)
        if command.operation == Operation.GET:
            row = self._rows.get((table, tenant_id, biz_domain, str(resource_id)))
            if row is None:
                raise DataControlError("RESOURCE_NOT_FOUND")
            return AdapterResult(status="OK", data=row.record, affected_count=1)
        if command.operation == Operation.LIST:
            rows = [
                row.record
                for key, row in self._rows.items()
                if key[:3] == (table, tenant_id, biz_domain)
            ]
            limit = int(command.validated_payload.get("options", {}).get("limit", 50))
            return AdapterResult(
                status="OK",
                data=rows[:limit],
                affected_count=len(rows[:limit]),
                has_more=len(rows) > limit,
            )
        if command.operation == Operation.UPDATE:
            key = (table, tenant_id, biz_domain, str(resource_id))
            row = self._rows.get(key)
            if row is None:
                raise DataControlError("RESOURCE_NOT_FOUND")
            merged = {**row.record, **data, "tenant_id": tenant_id, "biz_domain": biz_domain}
            return self._write(key, table, tenant_id, biz_domain, primary_key, merged)
        if command.operation == Operation.DELETE:
            existed = self._rows.pop((table, tenant_id, biz_domain, str(resource_id)), None)
            return AdapterResult(
                status="OK",
                data={"deleted": existed is not None},
                affected_count=int(existed is not None),
            )
        if command.operation == Operation.BATCH:
            items = command.validated_payload.get("data", {}).get("items", [])
            return AdapterResult(
                status="OK",
                data={"items": [{"success": True} for _ in items]},
                affected_count=len(items),
            )
        raise DataControlError("OPERATION_NOT_SUPPORTED")

    def _write(
        self,
        key: tuple[str, str, str, str],
        table: str,
        tenant_id: str,
        biz_domain: str,
        primary_key: str,
        data: dict[str, Any],
    ) -> AdapterResult:
        record = {**data, "tenant_id": tenant_id, "biz_domain": biz_domain, primary_key: key[3]}
        self._rows[key] = _TableRow(table, tenant_id, biz_domain, primary_key, record)
        return AdapterResult(
            status="OK", data={"resource_id": key[3]}, affected_count=1, resource_version="v1"
        )


class _SQLAlchemyPostgresTransaction(AdapterTransaction):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._transaction: Any | None = None
        self._token: Any | None = None

    async def start(self) -> None:
        self._session = self._session_factory()
        self._transaction = await self._session.begin()
        self._token = _ACTIVE_POSTGRESQL_SESSION.set(self._session)

    async def commit(self) -> None:
        if self._transaction is not None:
            await self._transaction.commit()
        await self._close()

    async def rollback(self) -> None:
        if self._transaction is not None:
            await self._transaction.rollback()
        await self._close()

    async def _close(self) -> None:
        if self._token is not None:
            _ACTIVE_POSTGRESQL_SESSION.reset(self._token)
        if self._session is not None:
            await self._session.close()


class SQLAlchemyPostgreSQLAdapter(DataAdapter):
    name = "postgresql"
    target = DataTarget.POSTGRESQL

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        required: bool = True,
        max_batch_size: int = 100,
    ) -> None:
        self._session_factory = session_factory
        self._required = required
        self._max_batch_size = max_batch_size
        self.execute_count = 0

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            operations=frozenset(
                {
                    Operation.GET,
                    Operation.LIST,
                    Operation.CREATE,
                    Operation.UPDATE,
                    Operation.UPSERT,
                    Operation.DELETE,
                    Operation.BATCH,
                }
            ),
            supports_transactions=True,
            supports_atomic_transaction=True,
            supports_cursor_pagination=True,
            timeout_ms=5000,
            required=self._required,
        )

    async def health(self) -> AdapterHealth:
        try:
            async with self._session_factory() as session:
                await session.execute(select(1))
            return AdapterHealth(
                status="UP",
                details={"adapter": self.name, "mode": "postgresql"},
                required=self._required,
            )
        except Exception:
            return AdapterHealth(
                status="DOWN",
                details={"adapter": self.name, "mode": "postgresql"},
                required=self._required,
            )

    async def begin(self, context: ExecutionContext) -> AdapterTransaction:
        transaction = _SQLAlchemyPostgresTransaction(self._session_factory)
        await transaction.start()
        return transaction

    async def execute(self, command: AdapterCommand, context: ExecutionContext) -> AdapterResult:
        self.execute_count += 1
        if command.operation not in self.capabilities().operations:
            raise DataControlError("OPERATION_NOT_SUPPORTED")
        active_session = _ACTIVE_POSTGRESQL_SESSION.get()
        if active_session is not None:
            return await self._execute_in_session(active_session, command)
        async with self._session_factory() as session:
            try:
                async with session.begin():
                    return await self._execute_in_session(session, command)
            except Exception as exc:
                raise PostgreSQLErrorMapper.to_error(exc) from exc

    async def _execute_in_session(
        self, session: AsyncSession, command: AdapterCommand
    ) -> AdapterResult:
        mapping = mapping_from(command)
        data = dict(command.validated_payload.get("data", {}))
        query = dict(command.validated_payload.get("query", {}))
        options = dict(command.validated_payload.get("options", {}))
        reject_client_scope(data)
        reject_client_scope(query)
        table = self._table(mapping.physical_mapping)
        if command.operation == Operation.CREATE:
            return await self._create(session, table, command, data)
        if command.operation == Operation.GET:
            return await self._get(session, table, command, query)
        if command.operation == Operation.LIST:
            return await self._list(session, table, command, query, options)
        if command.operation == Operation.UPDATE:
            return await self._update(session, table, command, data)
        if command.operation == Operation.UPSERT:
            return await self._upsert(session, table, command, data)
        if command.operation == Operation.DELETE:
            return await self._delete(session, table, command)
        if command.operation == Operation.BATCH:
            items = data.get("items", [])
            if not isinstance(items, list) or len(items) > self._max_batch_size:
                raise DataControlError("PAYLOAD_TOO_LARGE")
            return AdapterResult(status="OK", data={"items": []}, affected_count=0)
        raise DataControlError("OPERATION_NOT_SUPPORTED")

    async def _create(
        self, session: AsyncSession, table: Table, command: AdapterCommand, data: dict[str, Any]
    ) -> AdapterResult:
        row = self._validated_write_data(command, data, require_external_id=True)
        row["id"] = str(uuid4())
        now = datetime.now(UTC)
        row.update({"version": 1, "created_at": now, "updated_at": now, "deleted_at": None})
        await session.execute(insert(table).values(**row))
        return AdapterResult(
            status="OK",
            data={"resource_id": row["id"], "external_id": row["external_id"], "created": True},
            affected_count=1,
            resource_version=str(row["version"]),
        )

    async def _get(
        self, session: AsyncSession, table: Table, command: AdapterCommand, query: dict[str, Any]
    ) -> AdapterResult:
        resource_id = command.validated_payload.get("resource_id") or query.get("external_id")
        if not resource_id:
            raise DataControlError(
                "REQUEST_SCHEMA_INVALID", "resource_id or external_id is required"
            )
        statement = select(table).where(self._scope_clause(table, command))
        if command.validated_payload.get("resource_id"):
            statement = statement.where(table.c.id == str(resource_id))
        else:
            statement = statement.where(table.c.external_id == str(resource_id))
        row = (await session.execute(statement)).mappings().first()
        if row is None:
            raise DataControlError("RESOURCE_NOT_FOUND")
        return AdapterResult(
            status="OK", data=dict(row), affected_count=1, resource_version=str(row["version"])
        )

    async def _list(
        self,
        session: AsyncSession,
        table: Table,
        command: AdapterCommand,
        query: dict[str, Any],
        options: dict[str, Any],
    ) -> AdapterResult:
        mapping = mapping_from(command)
        filter_allowlist = set(mapping.physical_mapping.get("filter_allowlist", []))
        sort_allowlist = set(
            mapping.physical_mapping.get("sort_allowlist", ["updated_at", "external_id"])
        )
        max_page_size = int(mapping.physical_mapping.get("max_page_size", 100))
        limit = min(int(options.get("limit", 50)), max_page_size)
        statement = select(table).where(self._scope_clause(table, command))
        for key, value in query.items():
            if key not in filter_allowlist:
                raise DataControlError("FIELD_ACCESS_DENIED")
            statement = statement.where(table.c[key] == value)
        sort = str(options.get("sort", "updated_at"))
        if sort not in sort_allowlist:
            raise DataControlError("FIELD_ACCESS_DENIED")
        statement = statement.order_by(table.c[sort], table.c.id).limit(limit + 1)
        rows = [dict(row) for row in (await session.execute(statement)).mappings().all()]
        return AdapterResult(
            status="OK",
            data=rows[:limit],
            affected_count=len(rows[:limit]),
            has_more=len(rows) > limit,
        )

    async def _update(
        self, session: AsyncSession, table: Table, command: AdapterCommand, data: dict[str, Any]
    ) -> AdapterResult:
        resource_id = command.validated_payload.get("resource_id")
        if not resource_id or not data:
            raise DataControlError(
                "REQUEST_SCHEMA_INVALID", "resource_id and update data are required"
            )
        row = self._validated_write_data(command, data, require_external_id=False)
        row.pop("external_id", None)
        row["updated_at"] = datetime.now(UTC)
        expected_version = data.get("version")
        row.pop("version", None)
        statement = (
            update(table)
            .where(self._scope_clause(table, command), table.c.id == str(resource_id))
            .values(**row, version=table.c.version + 1)
            .returning(table.c.id, table.c.version)
        )
        if expected_version is not None:
            statement = statement.where(table.c.version == int(expected_version))
        result = (await session.execute(statement)).mappings().first()
        if result is None:
            raise DataControlError(
                "RESOURCE_VERSION_CONFLICT" if expected_version else "RESOURCE_NOT_FOUND"
            )
        return AdapterResult(
            status="OK",
            data={"resource_id": result["id"], "updated": True},
            affected_count=1,
            resource_version=str(result["version"]),
        )

    async def _upsert(
        self, session: AsyncSession, table: Table, command: AdapterCommand, data: dict[str, Any]
    ) -> AdapterResult:
        row = self._validated_write_data(command, data, require_external_id=True)
        row["id"] = str(uuid4())
        now = datetime.now(UTC)
        row.update({"created_at": now, "updated_at": now, "deleted_at": None, "version": 1})
        insert_stmt = pg_insert(table).values(**row)
        update_fields: dict[str, Any] = {
            key: insert_stmt.excluded[key]
            for key in row
            if key not in {"id", "tenant_id", "biz_domain", "external_id", "created_at"}
        }
        update_fields["version"] = table.c.version + 1
        update_fields["updated_at"] = now
        statement = insert_stmt.on_conflict_do_update(
            index_elements=["tenant_id", "biz_domain", "external_id"],
            set_=update_fields,
        ).returning(table.c.id, table.c.version)
        result = (await session.execute(statement)).mappings().one()
        return AdapterResult(
            status="OK",
            data={"resource_id": result["id"], "external_id": row["external_id"]},
            affected_count=1,
            resource_version=str(result["version"]),
        )

    async def _delete(
        self, session: AsyncSession, table: Table, command: AdapterCommand
    ) -> AdapterResult:
        resource_id = command.validated_payload.get("resource_id")
        if not resource_id:
            raise DataControlError("REQUEST_SCHEMA_INVALID", "resource_id is required")
        statement = (
            update(table)
            .where(self._scope_clause(table, command), table.c.id == str(resource_id))
            .values(
                deleted_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                version=table.c.version + 1,
            )
            .returning(table.c.id)
        )
        result = (await session.execute(statement)).first()
        return AdapterResult(
            status="OK",
            data={"deleted": result is not None},
            affected_count=int(result is not None),
        )

    def _validated_write_data(
        self, command: AdapterCommand, data: dict[str, Any], *, require_external_id: bool
    ) -> dict[str, Any]:
        mapping = mapping_from(command)
        allowlist = set(mapping.physical_mapping.get("field_allowlist", []))
        forbidden = {"id", "tenant_id", "biz_domain", "created_at", "updated_at", "deleted_at"}
        if set(data) & forbidden:
            raise DataControlError(
                "REQUEST_SCHEMA_INVALID", "client cannot override protected fields"
            )
        unknown = set(data) - allowlist - {"version"}
        if unknown:
            raise DataControlError("FIELD_ACCESS_DENIED")
        if require_external_id and not data.get("external_id"):
            raise DataControlError("REQUEST_SCHEMA_INVALID", "external_id is required")
        tenant_id, biz_domain = command.scope
        return {**data, "tenant_id": tenant_id, "biz_domain": biz_domain}

    @staticmethod
    def _scope_clause(table: Table, command: AdapterCommand) -> Any:
        tenant_id, biz_domain = command.scope
        return and_(
            table.c.tenant_id == tenant_id,
            table.c.biz_domain == biz_domain,
            table.c.deleted_at.is_(None),
        )

    @staticmethod
    def _table(mapping: dict[str, Any]) -> Table:
        metadata = MetaData()
        schema = str(mapping["schema"])
        table_name = str(mapping["table"])
        return Table(
            table_name,
            metadata,
            Column("id", PG_UUID(as_uuid=False), primary_key=True),
            Column("tenant_id", String(64), nullable=False),
            Column("biz_domain", String(64), nullable=False),
            Column("external_id", String(128), nullable=False),
            Column("record_type", String(128), nullable=False),
            Column("title", String(512)),
            Column("content", String),
            Column("attributes", JSONB),
            Column("version", Integer, nullable=False),
            Column("created_at", DateTime(timezone=True)),
            Column("updated_at", DateTime(timezone=True)),
            Column("deleted_at", DateTime(timezone=True)),
            schema=schema,
        )
