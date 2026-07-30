import hashlib
import json
from datetime import timedelta
from typing import Any

from file_media_stream_service.application.dto.contracts import RequestContext
from file_media_stream_service.application.ports.media_provider import (
    MediaProviderPort,
    StreamCoordinationPort,
    StreamLease,
)
from file_media_stream_service.application.ports.protocols import (
    Clock,
    EventBus,
    FileRepository,
    IdentifierFactory,
    MediaServer,
    ObjectStorage,
    ProcessingJobRepository,
    Processor,
    ReconciliationStore,
    StreamEventSink,
    StreamSessionRepository,
)
from file_media_stream_service.domain.entities.models import (
    FileResource,
    ProcessingJob,
    StreamEvent,
    StreamSession,
)
from file_media_stream_service.domain.enums.status import (
    FileResourceStatus,
    ProcessingJobStatus,
    StreamConnectionState,
    StreamEventType,
    StreamSessionStatus,
)
from file_media_stream_service.domain.exceptions.errors import (
    FileResourceNotFound,
    ProcessingJobNotFound,
    StreamSessionNotFound,
)
from file_media_stream_service.domain.services.object_key import (
    generate_object_key,
    normalize_filename,
)


def public_dict(
    value: FileResource | StreamSession | ProcessingJob,
) -> dict[str, Any]:
    if isinstance(value, FileResource):
        return {
            "resource_id": value.resource_id,
            "tenant_id": value.tenant_id,
            "biz_domain": value.biz_domain,
            "owner_type": value.owner_type,
            "owner_id": value.owner_id,
            "original_filename": value.original_filename,
            "normalized_filename": value.normalized_filename,
            "mime_type": value.mime_type,
            "size_bytes": value.size_bytes,
            "sha256": value.sha256,
            "status": value.status.value,
            "version": value.version,
            "created_by": value.created_by,
            "created_at": value.created_at.isoformat(),
            "updated_at": value.updated_at.isoformat(),
        }
    if isinstance(value, StreamSession):
        return {
            "session_id": value.session_id,
            "tenant_id": value.tenant_id,
            "biz_domain": value.biz_domain,
            "caller_id": value.caller_id,
            "protocol": value.protocol,
            "direction": value.direction,
            "status": value.status.value,
            "lease_expires_at": value.lease_expires_at.isoformat(),
            "created_at": value.created_at.isoformat(),
            "updated_at": value.updated_at.isoformat(),
        }
    return {
        "job_id": value.job_id,
        "tenant_id": value.tenant_id,
        "biz_domain": value.biz_domain,
        "operation": value.operation,
        "input_resource_id": value.input_resource_id,
        "output_resource_ids": list(value.output_resource_ids),
        "status": value.status.value,
        "processor_type": value.processor_type,
        "attempt": value.attempt,
        "created_at": value.created_at.isoformat(),
        "updated_at": value.updated_at.isoformat(),
    }


def canonical_request_hash(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode()).hexdigest()


class UseCases:
    def __init__(
        self,
        files: FileRepository,
        sessions: StreamSessionRepository,
        jobs: ProcessingJobRepository,
        storage: ObjectStorage,
        media_server: MediaServer,
        processor: Processor,
        events: EventBus,
        clock: Clock,
        ids: IdentifierFactory,
        reconciliation: ReconciliationStore,
        stream_lease_seconds: int = 300,
        media_provider: MediaProviderPort | None = None,
        stream_coordination: StreamCoordinationPort | None = None,
        stream_events: StreamEventSink | None = None,
    ) -> None:
        self.files = files
        self.sessions = sessions
        self.jobs = jobs
        self.storage = storage
        self.media_server = media_server
        self.processor = processor
        self.events = events
        self.clock = clock
        self.ids = ids
        self.reconciliation = reconciliation
        self.stream_lease_seconds = stream_lease_seconds
        self.media_provider = media_provider
        self.stream_coordination = stream_coordination
        self.stream_events = stream_events

    async def execute(
        self, operation: str, context: RequestContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        handlers = {
            "file.initialize_upload": self.initialize_upload,
            "file.get_resource": self.get_resource,
            "media.create_stream_session": self.create_stream_session,
            "media.get_stream_session": self.get_stream_session,
            "media.close_stream_session": self.close_stream_session,
            "media.submit_processing_job": self.submit_processing_job,
            "media.get_processing_job": self.get_processing_job,
        }
        return await handlers[operation](context, payload)

    async def initialize_upload(
        self, context: RequestContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        resource_id = self.ids.new_id("res")
        filename = str(payload["filename"])
        safe_name = normalize_filename(filename)
        object_key = generate_object_key(
            context.tenant_id, context.biz_domain, resource_id, 1, safe_name
        )
        resource = FileResource(
            resource_id=resource_id,
            tenant_id=context.tenant_id,
            biz_domain=context.biz_domain,
            owner_type=str(payload["owner_type"]),
            owner_id=str(payload["owner_id"]),
            original_filename=filename,
            normalized_filename=safe_name,
            object_key=object_key,
            mime_type=str(payload["mime_type"]),
            size_bytes=int(payload["size_bytes"]),
            sha256=None,
            status=FileResourceStatus.PENDING_UPLOAD,
            version=1,
            created_by=context.caller_id,
            created_at=self.clock.now(),
            updated_at=self.clock.now(),
        )
        upload_reference = await self.storage.initialize_upload(
            object_key, resource.mime_type, resource.size_bytes
        )
        try:
            await self.files.add(resource)
        except Exception:
            await self.storage.abort_upload(object_key)
            raise
        try:
            await self.events.publish("file.upload_initialized", {"resource_id": resource_id})
        except Exception:
            recovery_key = f"upload:{resource_id}"
            await self.reconciliation.record(
                recovery_key,
                "UPLOAD_COMPENSATION",
                {
                    "tenant_id": context.tenant_id,
                    "biz_domain": context.biz_domain,
                    "resource_id": resource_id,
                },
            )
            compensation_failed = False
            try:
                await self.files.delete(context.tenant_id, context.biz_domain, resource_id)
            except Exception:
                compensation_failed = True
            try:
                await self.storage.abort_upload(object_key)
            except Exception:
                compensation_failed = True
            if not compensation_failed:
                await self.reconciliation.resolve(
                    recovery_key, context.tenant_id, context.biz_domain
                )
            raise
        return {"resource": public_dict(resource), "upload_reference": upload_reference}

    async def get_resource(
        self, context: RequestContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        resource = await self.files.get_by_scope_and_id(
            context.tenant_id, context.biz_domain, str(payload["resource_id"])
        )
        if resource is None:
            raise FileResourceNotFound("File resource not found")
        return {"resource": public_dict(resource)}

    async def create_stream_session(
        self, context: RequestContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        session_id = self.ids.new_id("ses")
        lease = self.clock.now() + timedelta(seconds=self.stream_lease_seconds)
        session = StreamSession(
            session_id=session_id,
            tenant_id=context.tenant_id,
            biz_domain=context.biz_domain,
            caller_id=context.caller_id,
            protocol=str(payload["protocol"]),
            direction=str(payload["direction"]),
            status=StreamSessionStatus.CREATING,
            lease_expires_at=lease,
            endpoint_reference="",
            created_at=self.clock.now(),
            updated_at=self.clock.now(),
        )
        stream_lease: StreamLease | None = None
        if self.media_provider is not None and self.stream_coordination is not None:
            stream_lease = await self.stream_coordination.acquire_stream_lease(
                context.tenant_id, context.biz_domain, session_id
            )
            if stream_lease is None:
                raise RuntimeError("Stream lease is unavailable")
            try:
                endpoint = await self.media_provider.create_stream_endpoint(
                    context.tenant_id,
                    context.biz_domain,
                    session_id,
                    str(payload["protocol"]),
                    str(payload["direction"]),
                    lease,
                    stream_lease.fencing_token,
                )
            except Exception:
                session.transition_to(StreamSessionStatus.FAILED)
                session.fencing_token = stream_lease.fencing_token
                await self.sessions.add(session)
                await self.reconciliation.record(
                    f"stream-provider:{session_id}",
                    "STREAM_PROVIDER_CREATE_FAILED",
                    {
                        "tenant_id": context.tenant_id,
                        "biz_domain": context.biz_domain,
                        "session_id": session_id,
                    },
                )
                await self.stream_coordination.release_stream(stream_lease)
                raise
            session.provider_type = endpoint.provider_type
            session.stream_key = endpoint.stream_key
            session.input_protocol = endpoint.input_protocol
            session.output_protocol = endpoint.output_protocol
            session.endpoint = endpoint.endpoint_reference
            session.endpoint_reference = endpoint.media_server_session_id
            session.media_server_session_id = endpoint.media_server_session_id
            session.connection_state = StreamConnectionState.CONNECTING
            session.fencing_token = stream_lease.fencing_token
        else:
            endpoint_reference = await self.media_server.create_session(
                str(payload["protocol"]), str(payload["direction"]), lease
            )
            session.endpoint_reference = endpoint_reference
            session.endpoint = endpoint_reference
        session.transition_to(StreamSessionStatus.READY)
        try:
            await self.sessions.add(session)
        except Exception:
            recovery_key = f"session-create:{session_id}"
            await self.reconciliation.record(
                recovery_key,
                "SESSION_CREATE_COMPENSATION",
                {
                    "tenant_id": context.tenant_id,
                    "biz_domain": context.biz_domain,
                    "session_id": session_id,
                },
            )
            try:
                if self.media_provider is not None and stream_lease is not None:
                    await self.media_provider.stop_stream(
                        session.media_server_session_id, stream_lease.fencing_token
                    )
                    await self.stream_coordination.release_stream(stream_lease)  # type: ignore[union-attr]
                else:
                    await self.media_server.close_session(session.endpoint_reference)
            except Exception:
                raise
            else:
                await self.reconciliation.resolve(
                    recovery_key, context.tenant_id, context.biz_domain
                )
            raise
        await self._write_stream_event(session, StreamEventType.STREAM_CREATED)
        return {"session": public_dict(session)}

    async def get_stream_session(
        self, context: RequestContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        session = await self.sessions.get_by_scope_and_id(
            context.tenant_id, context.biz_domain, str(payload["session_id"])
        )
        if session is None:
            raise StreamSessionNotFound("Stream session not found")
        return {"session": public_dict(session)}

    async def close_stream_session(
        self, context: RequestContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        session = await self.sessions.get_by_scope_and_id(
            context.tenant_id, context.biz_domain, str(payload["session_id"])
        )
        if session is None:
            raise StreamSessionNotFound("Stream session not found")
        if session.status is not StreamSessionStatus.CLOSED:
            stream_lease = StreamLease(
                session.tenant_id,
                session.biz_domain,
                session.session_id,
                session.fencing_token,
            )
            if self.media_provider is not None and session.media_server_session_id:
                lease_is_current = (
                    self.stream_coordination is not None
                    and await self.stream_coordination.heartbeat_stream(stream_lease)
                )
                if not lease_is_current:
                    raise RuntimeError("Stream lease was lost")
                await self.media_provider.stop_stream(
                    session.media_server_session_id, session.fencing_token
                )
            else:
                await self.media_server.close_session(session.endpoint_reference)
            session.close()
            session.connection_state = StreamConnectionState.DISCONNECTED
            try:
                await self.sessions.save(session)
            except Exception:
                await self.reconciliation.record(
                    f"session-close:{session.session_id}",
                    "SESSION_CLOSE_RECONCILIATION",
                    {
                        "tenant_id": context.tenant_id,
                        "biz_domain": context.biz_domain,
                        "session_id": session.session_id,
                    },
                )
                try:
                    await self.events.publish(
                        "media.session_reconciliation_required",
                        {"session_id": session.session_id},
                    )
                except Exception:
                    event_delivery_failed = True
                else:
                    event_delivery_failed = False
                if event_delivery_failed:
                    # The pending reconciliation record is the recovery truth.
                    await self.reconciliation.record(
                        f"session-close:{session.session_id}",
                        "SESSION_CLOSE_RECONCILIATION",
                        {
                            "tenant_id": context.tenant_id,
                            "biz_domain": context.biz_domain,
                            "session_id": session.session_id,
                        },
                    )
                raise
            if self.stream_coordination is not None:
                await self.stream_coordination.release_stream(stream_lease)
            await self._write_stream_event(session, StreamEventType.STREAM_DISCONNECTED)
        return {"session": public_dict(session)}

    async def _write_stream_event(
        self, session: StreamSession, event_type: StreamEventType
    ) -> None:
        if self.stream_events is None:
            return
        await self.stream_events.write_stream_event(
            StreamEvent(
                event_id=self.ids.new_id("evt"),
                tenant_id=session.tenant_id,
                biz_domain=session.biz_domain,
                session_id=session.session_id,
                event_type=event_type,
                provider=session.provider_type,
                timestamp=self.clock.now(),
                metadata={"connection_state": session.connection_state.value},
            )
        )

    async def submit_processing_job(
        self, context: RequestContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        input_id = str(payload["input_resource_id"])
        resource = await self.files.get_by_scope_and_id(
            context.tenant_id, context.biz_domain, input_id
        )
        if resource is None:
            raise FileResourceNotFound("Input file resource not found")
        job = ProcessingJob(
            job_id=self.ids.new_id("job"),
            tenant_id=context.tenant_id,
            biz_domain=context.biz_domain,
            operation=str(payload["operation"]),
            input_resource_id=input_id,
            output_resource_ids=(),
            status=ProcessingJobStatus.PENDING,
            processor_type=str(payload["processor_type"]),
            attempt=0,
            created_at=self.clock.now(),
            updated_at=self.clock.now(),
        )
        job.transition_to(ProcessingJobStatus.QUEUED)
        await self.jobs.add(job)
        try:
            await self.processor.submit(job.processor_type, input_id, payload.get("options", {}))
        except Exception:
            job.transition_to(ProcessingJobStatus.FAILED)
            await self.jobs.save(job)
            raise
        return {"job": public_dict(job)}

    async def get_processing_job(
        self, context: RequestContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        job = await self.jobs.get_by_scope_and_id(
            context.tenant_id, context.biz_domain, str(payload["job_id"])
        )
        if job is None:
            raise ProcessingJobNotFound("Processing job not found")
        return {"job": public_dict(job)}
