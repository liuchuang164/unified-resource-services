from contextvars import ContextVar
from dataclasses import dataclass

from file_media_stream_service.application.ports.protocols import ReconciliationStore


@dataclass(frozen=True, slots=True)
class PendingFileCommit:
    kind: str
    tenant_id: str
    biz_domain: str
    resource_id: str
    version_id: str | None


class FileMetadataCommitReconciler:
    """Records completed object-storage effects when the request DB commit fails."""

    def __init__(self, reconciliation: ReconciliationStore) -> None:
        self.reconciliation = reconciliation
        self._pending: ContextVar[list[PendingFileCommit] | None] = ContextVar(
            "file_metadata_commit_reconciliation", default=None
        )

    def begin(self) -> None:
        self._pending.set([])

    def register(
        self,
        tenant_id: str,
        biz_domain: str,
        resource_id: str,
        version_id: str,
    ) -> None:
        pending = PendingFileCommit(
            "FILE_METADATA_SYNC_REQUIRED",
            tenant_id,
            biz_domain,
            resource_id,
            version_id,
        )
        self._append(pending)

    def register_delete(
        self,
        tenant_id: str,
        biz_domain: str,
        resource_id: str,
        version_id: str | None,
    ) -> None:
        self._append(
            PendingFileCommit(
                "FILE_DELETE_PENDING",
                tenant_id,
                biz_domain,
                resource_id,
                version_id,
            )
        )

    def _append(self, pending: PendingFileCommit) -> None:
        records = self._pending.get()
        if records is None:
            records = []
            self._pending.set(records)
        records.append(pending)

    async def reconcile(self) -> None:
        try:
            for pending in self._pending.get() or []:
                version_suffix = pending.version_id or "all"
                key_prefix = (
                    "file-metadata"
                    if pending.kind == "FILE_METADATA_SYNC_REQUIRED"
                    else "file-delete"
                )
                payload = {
                    "tenant_id": pending.tenant_id,
                    "biz_domain": pending.biz_domain,
                    "resource_id": pending.resource_id,
                }
                if pending.version_id is not None:
                    payload["version_id"] = pending.version_id
                await self.reconciliation.record(
                    f"{key_prefix}:{pending.resource_id}:{version_suffix}",
                    pending.kind,
                    payload,
                )
        finally:
            self.clear()

    def clear(self) -> None:
        records = self._pending.get()
        if records is not None:
            records.clear()
        self._pending.set(None)
