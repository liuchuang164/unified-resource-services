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
    FileUploadSessionRepository,
    FileVersionRepository,
    IdentifierFactory,
    MalwareScannerPort,
    MediaServer,
    ObjectStorage,
    ProcessingJobRepository,
    Processor,
    ProvisioningCompensator,
    RangeAccessGrantStore,
    ReconciliationStore,
    StreamEventSink,
    StreamSessionRepository,
    TransactionManager,
)
from file_media_stream_service.domain.entities.models import (
    FileResource,
    FileResourceVersion,
    FileUploadSession,
    ProcessingJob,
    RangeAccessGrant,
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
        transactions: TransactionManager | None = None,
        provisioning_compensator: ProvisioningCompensator | None = None,
        file_versions: FileVersionRepository | None = None,
        file_uploads: FileUploadSessionRepository | None = None,
        range_grants: RangeAccessGrantStore | None = None,
        malware_scanner: MalwareScannerPort | None = None,
        upload_ttl_seconds: int = 900,
        range_grant_ttl_seconds: int = 60,
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
        self.transactions = transactions
        self.provisioning_compensator = provisioning_compensator
        self.file_versions = file_versions
        self.file_uploads = file_uploads
        self.range_grants = range_grants
        self.malware_scanner = malware_scanner
        self.upload_ttl_seconds = upload_ttl_seconds
        self.range_grant_ttl_seconds = range_grant_ttl_seconds

    async def execute(
        self, operation: str, context: RequestContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        handlers = {
            "file.initialize_upload": self.initialize_upload,
            "file.get_resource": self.get_resource,
            "file.complete_upload": self.complete_upload,
            "file.abort_upload": self.abort_upload,
            "file.create_download_url": self.create_download_url,
            "file.read_range": self.issue_range_access,
            "file.get_metadata": self.get_metadata,
            "file.delete_file": self.delete_file,
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
        handle = await self.storage.create_multipart_upload(object_key)
        upload = FileUploadSession(
            upload_id=self.ids.new_id("upl"),
            resource_id=resource_id,
            tenant_id=context.tenant_id,
            biz_domain=context.biz_domain,
            provider_upload_id=handle.provider_upload_id,
            upload_reference=upload_reference,
            expires_at=self.clock.now() + timedelta(seconds=self.upload_ttl_seconds),
        )
        try:
            await self.files.add(resource)
            if self.file_uploads is not None:
                await self.file_uploads.add(upload)
        except Exception:
            await self.storage.abort_multipart_upload(object_key, handle.provider_upload_id)
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
        return {
            "resource": public_dict(resource),
            "upload_id": upload.upload_id,
            "upload_reference": upload_reference,
            "expires_at": upload.expires_at.isoformat(),
        }

    async def complete_upload(
        self, context: RequestContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        resource = await self._file(context, str(payload["resource_id"]))
        upload = await self._upload(context, str(payload["upload_id"]))
        if upload.resource_id != resource.resource_id or upload.aborted:
            raise FileResourceNotFound("File upload not found")
        if upload.completed and resource.status is FileResourceStatus.AVAILABLE:
            return {"resource": public_dict(resource)}
        resource.transition_to(FileResourceStatus.UPLOADING)
        parts = tuple((int(part["part_number"]), str(part["etag"])) for part in payload["parts"])
        try:
            metadata = await self.storage.complete_multipart_upload(
                resource.object_key, upload.provider_upload_id, parts
            )
            resource.transition_to(FileResourceStatus.VERIFYING)
            checksum = str(payload["checksum"]).lower()
            if metadata.size_bytes != resource.size_bytes or metadata.checksum.lower() != checksum:
                raise ValueError("uploaded object metadata does not match declaration")
            if metadata.content_type and metadata.content_type != resource.mime_type:
                raise ValueError("uploaded object content type does not match declaration")
            if self.malware_scanner is not None:
                await self.malware_scanner.validate_metadata(
                    resource.normalized_filename,
                    resource.mime_type,
                    metadata.size_bytes,
                    metadata.checksum,
                )
            resource.sha256 = metadata.checksum.lower()
            resource.transition_to(FileResourceStatus.AVAILABLE)
            await self.files.save(resource)
            if self.file_versions is not None:
                await self.file_versions.add(
                    FileResourceVersion(
                        version_id=self.ids.new_id("ver"),
                        resource_id=resource.resource_id,
                        tenant_id=resource.tenant_id,
                        biz_domain=resource.biz_domain,
                        version=resource.version,
                        object_key=resource.object_key,
                        size_bytes=resource.size_bytes,
                        checksum=resource.sha256,
                        status=resource.status,
                        created_at=self.clock.now(),
                    )
                )
            upload.completed = True
            if self.file_uploads is not None:
                await self.file_uploads.save(upload)
        except Exception:
            if resource.status in {
                FileResourceStatus.UPLOADING,
                FileResourceStatus.VERIFYING,
            }:
                resource.transition_to(FileResourceStatus.FAILED)
                try:
                    await self.files.save(resource)
                except Exception:
                    await self.reconciliation.record(
                        f"file-metadata:{resource.resource_id}",
                        "FILE_METADATA_SYNC_REQUIRED",
                        {
                            "tenant_id": context.tenant_id,
                            "biz_domain": context.biz_domain,
                            "resource_id": resource.resource_id,
                        },
                    )
            elif resource.status is FileResourceStatus.AVAILABLE:
                await self.reconciliation.record(
                    f"file-metadata:{resource.resource_id}",
                    "FILE_METADATA_SYNC_REQUIRED",
                    {
                        "tenant_id": context.tenant_id,
                        "biz_domain": context.biz_domain,
                        "resource_id": resource.resource_id,
                    },
                )
            raise
        return {"resource": public_dict(resource)}

    async def abort_upload(
        self, context: RequestContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        resource = await self._file(context, str(payload["resource_id"]))
        upload = await self._upload(context, str(payload["upload_id"]))
        if upload.resource_id != resource.resource_id:
            raise FileResourceNotFound("File upload not found")
        if not upload.aborted:
            await self.storage.abort_multipart_upload(
                resource.object_key, upload.provider_upload_id
            )
            upload.aborted = True
            if self.file_uploads is not None:
                await self.file_uploads.save(upload)
            if resource.status in {
                FileResourceStatus.PENDING_UPLOAD,
                FileResourceStatus.UPLOADING,
            }:
                resource.transition_to(FileResourceStatus.FAILED)
                await self.files.save(resource)
        return {"resource": public_dict(resource)}

    async def create_download_url(
        self, context: RequestContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        resource = await self._available_file(context, str(payload["resource_id"]))
        url, expires_at = await self.storage.create_download_url(resource.object_key)
        return {
            "resource_id": resource.resource_id,
            "url": url,
            "expires_at": expires_at.isoformat(),
        }

    async def issue_range_access(
        self, context: RequestContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        resource = await self._available_file(context, str(payload["resource_id"]))
        offset, length = int(payload["offset"]), int(payload["length"])
        if offset >= resource.size_bytes or offset + length > resource.size_bytes:
            raise ValueError("requested range is outside the resource")
        if self.range_grants is None:
            raise RuntimeError("Range access store is unavailable")
        grant = RangeAccessGrant(
            reference_id=self.ids.new_id("rng"),
            resource_id=resource.resource_id,
            tenant_id=context.tenant_id,
            biz_domain=context.biz_domain,
            caller_id=context.caller_id,
            caller_type=context.caller_type,
            request_id=context.request_id,
            trace_id=context.trace_id,
            offset=offset,
            length=length,
            expires_at=self.clock.now() + timedelta(seconds=self.range_grant_ttl_seconds),
        )
        await self.range_grants.issue(grant)
        return {
            "reference_id": grant.reference_id,
            "resource_id": grant.resource_id,
            "offset": grant.offset,
            "length": grant.length,
            "expires_at": grant.expires_at.isoformat(),
        }

    async def consume_range_access(
        self, reference_id: str
    ) -> tuple[RangeAccessGrant, FileResource, Any]:
        if self.range_grants is None:
            raise FileResourceNotFound("Range access reference not found")
        grant = await self.range_grants.consume(reference_id)
        if grant is None or grant.expires_at <= self.clock.now():
            raise FileResourceNotFound("Range access reference not found")
        resource = await self.files.get_by_scope_and_id(
            grant.tenant_id, grant.biz_domain, grant.resource_id
        )
        if resource is None or resource.status is not FileResourceStatus.AVAILABLE:
            raise FileResourceNotFound("File resource not found")
        return (
            grant,
            resource,
            self.storage.stream_range(resource.object_key, grant.offset, grant.length),
        )

    async def get_metadata(
        self, context: RequestContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        resource = await self._file(context, str(payload["resource_id"]))
        versions = (
            await self.file_versions.list_by_scope_and_resource(
                context.tenant_id, context.biz_domain, resource.resource_id
            )
            if self.file_versions is not None
            else []
        )
        return {
            "resource": public_dict(resource),
            "versions": [
                {
                    "version_id": item.version_id,
                    "version": item.version,
                    "size_bytes": item.size_bytes,
                    "checksum": item.checksum,
                    "status": item.status.value,
                    "created_at": item.created_at.isoformat(),
                }
                for item in versions
            ],
        }

    async def delete_file(self, context: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
        resource = await self._file(context, str(payload["resource_id"]))
        if resource.status is FileResourceStatus.DELETED:
            return {"resource": public_dict(resource)}
        resource.transition_to(FileResourceStatus.DELETING)
        try:
            await self.storage.delete(resource.object_key)
            resource.transition_to(FileResourceStatus.DELETED)
        except Exception:
            resource.transition_to(FileResourceStatus.FAILED)
            await self.files.save(resource)
            raise
        await self.files.save(resource)
        return {"resource": public_dict(resource)}

    async def _file(self, context: RequestContext, resource_id: str) -> FileResource:
        resource = await self.files.get_by_scope_and_id(
            context.tenant_id, context.biz_domain, resource_id
        )
        if resource is None:
            raise FileResourceNotFound("File resource not found")
        return resource

    async def _available_file(self, context: RequestContext, resource_id: str) -> FileResource:
        resource = await self._file(context, resource_id)
        if resource.status is not FileResourceStatus.AVAILABLE:
            raise ValueError("File resource is not available")
        return resource

    async def _upload(self, context: RequestContext, upload_id: str) -> FileUploadSession:
        upload = (
            await self.file_uploads.get_by_scope_and_id(
                context.tenant_id, context.biz_domain, upload_id
            )
            if self.file_uploads is not None
            else None
        )
        if upload is None:
            raise FileResourceNotFound("File upload not found")
        return upload

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
        await self.sessions.add(session)
        if self.transactions is not None:
            await self.transactions.commit()
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
                await self.sessions.save(session)
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
            if self.provisioning_compensator is not None:
                await self.provisioning_compensator.register(session, stream_lease.fencing_token)
        else:
            endpoint_reference = await self.media_server.create_session(
                str(payload["protocol"]), str(payload["direction"]), lease
            )
            session.endpoint_reference = endpoint_reference
            session.endpoint = endpoint_reference
        session.transition_to(StreamSessionStatus.READY)
        try:
            await self.sessions.save(session)
        except Exception:
            if self.transactions is not None:
                await self.transactions.rollback()
                await self.transactions.close()
            if self.provisioning_compensator is not None:
                await self.provisioning_compensator.compensate()
            elif self.media_provider is not None and stream_lease is not None:
                await self.media_provider.stop_stream(
                    session.media_server_session_id, stream_lease.fencing_token
                )
                await self.stream_coordination.release_stream(stream_lease)  # type: ignore[union-attr]
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
