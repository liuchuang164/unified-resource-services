import logging

from file_media_stream_service.application.ports.media_provider import (
    MediaProviderPort,
    StreamCoordinationPort,
    StreamLease,
)
from file_media_stream_service.application.ports.protocols import (
    Clock,
    IdentifierFactory,
    ReconciliationStore,
    StreamEventSink,
    StreamSessionRepository,
)
from file_media_stream_service.domain.entities import StreamEvent, StreamSession
from file_media_stream_service.domain.enums import (
    StreamConnectionState,
    StreamEventType,
    StreamSessionStatus,
)

logger = logging.getLogger(__name__)


class StreamLifecycleService:
    def __init__(
        self,
        sessions: StreamSessionRepository,
        provider: MediaProviderPort,
        coordination: StreamCoordinationPort,
        events: StreamEventSink,
        reconciliation: ReconciliationStore,
        clock: Clock,
        ids: IdentifierFactory,
    ) -> None:
        self.sessions = sessions
        self.provider = provider
        self.coordination = coordination
        self.events = events
        self.reconciliation = reconciliation
        self.clock = clock
        self.ids = ids

    async def mark_connected(
        self, tenant_id: str, biz_domain: str, session_id: str
    ) -> StreamSession:
        session = await self._get(tenant_id, biz_domain, session_id)
        if not await self.coordination.heartbeat_stream(self._lease(session)):
            raise RuntimeError("Stream lease was lost")
        await self.provider.start_stream(session.media_server_session_id, session.fencing_token)
        session.connected(self.clock.now())
        await self.sessions.save(session)
        await self._event(session, StreamEventType.STREAM_CONNECTED)
        return session

    async def heartbeat(self, tenant_id: str, biz_domain: str, session_id: str) -> StreamSession:
        session = await self._get(tenant_id, biz_domain, session_id)
        if not await self.coordination.heartbeat_stream(self._lease(session)):
            session.connection_state = StreamConnectionState.DEGRADED
            session.transition_to(StreamSessionStatus.FAILED)
            await self.sessions.save(session)
            await self._event(session, StreamEventType.STREAM_TIMEOUT)
            raise RuntimeError("Stream lease was lost")
        status = await self.provider.get_stream_status(
            session.media_server_session_id, session.fencing_token
        )
        if not status.exists:
            await self._restart_required(session)
            return session
        session.last_heartbeat_at = status.last_heartbeat_at or self.clock.now()
        session.connection_state = (
            StreamConnectionState.CONNECTED
            if status.connected
            else StreamConnectionState.DISCONNECTED
        )
        await self.sessions.save(session)
        return session

    async def reconcile_scope(self, tenant_id: str, biz_domain: str) -> list[StreamSession]:
        recovered: list[StreamSession] = []
        for session in await self.sessions.list_recoverable(tenant_id, biz_domain):
            lease = self._lease(session)
            if not await self.coordination.heartbeat_stream(lease):
                replacement = await self.coordination.acquire_stream_lease(
                    session.tenant_id, session.biz_domain, session.session_id
                )
                if replacement is None:
                    await self._restart_required(session)
                    recovered.append(session)
                    continue
                session.fencing_token = replacement.fencing_token
            status = await self.provider.get_stream_status(
                session.media_server_session_id, session.fencing_token
            )
            if status.exists:
                session.connection_state = (
                    StreamConnectionState.CONNECTED
                    if status.connected
                    else StreamConnectionState.DISCONNECTED
                )
                session.last_heartbeat_at = status.last_heartbeat_at
            else:
                await self._restart_required(session)
                await self.coordination.release_stream(self._lease(session))
            await self.sessions.save(session)
            recovered.append(session)
        return recovered

    async def reconcile_all(self) -> list[StreamSession]:
        recovered: list[StreamSession] = []
        for tenant_id, biz_domain in await self.sessions.list_recovery_scopes():
            recovered.extend(await self.reconcile_scope(tenant_id, biz_domain))
        await self.reconcile_provider_orphans()
        return recovered

    async def reconcile_provider_orphans(self) -> None:
        records = await self.reconciliation.list_pending("STREAM_PROVIDER_ORPHAN")
        for key, payload in records:
            try:
                lease = StreamLease(
                    str(payload["tenant_id"]),
                    str(payload["biz_domain"]),
                    str(payload["session_id"]),
                    int(payload["fencing_token"]),
                )
                await self.provider.stop_stream(
                    str(payload["provider_session_id"]), lease.fencing_token
                )
                await self.coordination.release_stream(lease)
                await self.reconciliation.resolve(key, lease.tenant_id, lease.biz_domain)
            except Exception:
                logger.exception(
                    "stream provider orphan reconciliation failed",
                    extra={"reconciliation_key": key},
                )

    async def _restart_required(self, session: StreamSession) -> None:
        session.transition_to(StreamSessionStatus.FAILED)
        session.connection_state = StreamConnectionState.DEGRADED
        await self.sessions.save(session)
        await self.reconciliation.record(
            f"stream-restart:{session.session_id}",
            "STREAM_RESTART_REQUIRED",
            {
                "tenant_id": session.tenant_id,
                "biz_domain": session.biz_domain,
                "session_id": session.session_id,
            },
        )
        await self._event(session, StreamEventType.STREAM_RESTART_REQUIRED)

    async def _get(self, tenant_id: str, biz_domain: str, session_id: str) -> StreamSession:
        session = await self.sessions.get_by_scope_and_id(tenant_id, biz_domain, session_id)
        if session is None:
            raise RuntimeError("Stream session does not exist")
        return session

    @staticmethod
    def _lease(session: StreamSession) -> StreamLease:
        return StreamLease(
            session.tenant_id,
            session.biz_domain,
            session.session_id,
            session.fencing_token,
        )

    async def _event(self, session: StreamSession, event_type: StreamEventType) -> None:
        await self.events.write_stream_event(
            StreamEvent(
                self.ids.new_id("evt"),
                session.tenant_id,
                session.biz_domain,
                session.session_id,
                event_type,
                session.provider_type,
                self.clock.now(),
                {"connection_state": session.connection_state.value},
            )
        )
