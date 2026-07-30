from contextvars import ContextVar
from copy import deepcopy

from file_media_stream_service.application.ports.media_provider import (
    MediaProviderPort,
    StreamCoordinationPort,
    StreamLease,
)
from file_media_stream_service.application.ports.protocols import ReconciliationStore
from file_media_stream_service.domain.entities import StreamSession


class StreamProvisioningCompensator:
    """Tracks provider effects until READY and idempotency commit atomically."""

    def __init__(
        self,
        provider: MediaProviderPort,
        coordination: StreamCoordinationPort,
        reconciliation: ReconciliationStore,
    ) -> None:
        self.provider = provider
        self.coordination = coordination
        self.reconciliation = reconciliation
        self._pending: ContextVar[list[tuple[StreamSession, int]] | None] = ContextVar(
            "stream_provisioning_compensation", default=None
        )

    def begin(self) -> None:
        self._pending.set([])

    async def register(self, session: StreamSession, fencing_token: int) -> None:
        pending = self._pending.get()
        if pending is None:
            pending = []
            self._pending.set(pending)
        pending.append((deepcopy(session), fencing_token))

    async def compensate(self) -> None:
        pending = self._pending.get()
        if not pending:
            return
        session, fencing_token = pending[-1]
        key = f"stream-provider-orphan:{session.session_id}"
        payload = {
            "tenant_id": session.tenant_id,
            "biz_domain": session.biz_domain,
            "session_id": session.session_id,
            "provider_type": session.provider_type,
            "provider_session_id": session.media_server_session_id,
            "fencing_token": fencing_token,
            "required_action": "STOP_PROVIDER_STREAM",
        }
        recovery_recorded = False
        try:
            await self.reconciliation.record(key, "STREAM_PROVIDER_ORPHAN", payload)
            recovery_recorded = True
        except Exception:
            # Synchronous compensation remains the primary safety path during a DB outage.
            recovery_recorded = False
        try:
            await self.provider.stop_stream(session.media_server_session_id, fencing_token)
            await self.coordination.release_stream(
                StreamLease(
                    session.tenant_id,
                    session.biz_domain,
                    session.session_id,
                    fencing_token,
                )
            )
        except Exception:
            if not recovery_recorded:
                raise
        else:
            if recovery_recorded:
                await self.reconciliation.resolve(key, session.tenant_id, session.biz_domain)
        finally:
            self.clear()

    def clear(self) -> None:
        pending = self._pending.get()
        if pending is not None:
            pending.clear()
        self._pending.set(None)
