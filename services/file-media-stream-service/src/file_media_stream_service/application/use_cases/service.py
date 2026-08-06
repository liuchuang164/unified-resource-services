import hashlib
import json
from collections.abc import AsyncIterator
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
    FileMetadataCommitTracker,
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
    UploadPartGrantStore,
)
from file_media_stream_service.domain.entities.models import (
    FileResource,
    FileResourceVersion,
    FileUploadSession,
    ProcessingJob,
    ProcessorInputReference,
    RangeAccessGrant,
    StreamEvent,
    StreamSession,
    UploadPartGrant,
)
from file_media_stream_service.domain.enums.status import (
    FileResourceStatus,
    ProcessingJobStatus,
    StreamConnectionState,
    StreamEventType,
    StreamSessionStatus,
    UploadSessionStatus,
)
from file_media_stream_service.domain.exceptions.errors import (
    FileResourceNotFound,
    InvalidStateTransition,
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
            "current_version_id": value.current_version_id,
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


class UploadPartTransferFailed(RuntimeError):
    def __init__(self, grant: UploadPartGrant) -> None:
        super().__init__("Upload part transfer failed")
        self.grant = grant


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
        file_metadata_commit_tracker: FileMetadataCommitTracker | None = None,
        file_versions: FileVersionRepository | None = None,
        file_uploads: FileUploadSessionRepository | None = None,
        range_grants: RangeAccessGrantStore | None = None,
        malware_scanner: MalwareScannerPort | None = None,
        upload_ttl_seconds: int = 900,
        range_grant_ttl_seconds: int = 60,
        upload_part_grants: UploadPartGrantStore | None = None,
        upload_part_grant_ttl_seconds: int = 60,
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
        self.file_metadata_commit_tracker = file_metadata_commit_tracker
        self.file_versions = file_versions
        self.file_uploads = file_uploads
        self.range_grants = range_grants
        self.malware_scanner = malware_scanner
        self.upload_ttl_seconds = upload_ttl_seconds
        self.range_grant_ttl_seconds = range_grant_ttl_seconds
        self.upload_part_grants = upload_part_grants
        self.upload_part_grant_ttl_seconds = upload_part_grant_ttl_seconds

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
            "file.create_upload_part_urls": self.create_upload_part_references,
            "file.create_version_upload": self.create_version_upload,
            "file.switch_current_version": self.switch_current_version,
            "file.delete_version": self.delete_version,
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
        handle = await self.storage.create_multipart_upload(object_key, str(payload["mime_type"]))
        version_id = self.ids.new_id("ver")
        upload = FileUploadSession(
            upload_id=self.ids.new_id("upl"),
            resource_id=resource_id,
            tenant_id=context.tenant_id,
            biz_domain=context.biz_domain,
            provider_upload_id=handle.provider_upload_id,
            upload_reference=upload_reference,
            expires_at=self.clock.now() + timedelta(seconds=self.upload_ttl_seconds),
            status=UploadSessionStatus.INIT,
            version_id=version_id,
            created_at=self.clock.now(),
            updated_at=self.clock.now(),
        )
        version = FileResourceVersion(
            version_id=version_id,
            resource_id=resource.resource_id,
            tenant_id=resource.tenant_id,
            biz_domain=resource.biz_domain,
            version=1,
            object_key=resource.object_key,
            size_bytes=resource.size_bytes,
            checksum=None,
            status=FileResourceStatus.PENDING_UPLOAD,
            created_at=self.clock.now(),
            mime_type=resource.mime_type,
        )
        try:
            await self.files.add(resource)
            if self.file_uploads is not None:
                await self.file_uploads.add(upload)
            if self.file_versions is not None:
                await self.file_versions.add(version)
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
            "upload_session_id": upload.upload_id,
            "upload_reference": upload_reference,
            "expires_at": upload.expires_at.isoformat(),
        }

    async def complete_upload(
        self, context: RequestContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        resource = await self._file(context, str(payload["resource_id"]))
        upload = await self._upload(context, str(payload["upload_id"]))
        if upload.resource_id != resource.resource_id:
            raise FileResourceNotFound("File upload not found")
        if upload.status is UploadSessionStatus.COMPLETED:
            return await self._complete_result(resource, upload)
        await self._ensure_upload_active(upload)
        parts = tuple((int(part["part_number"]), str(part["etag"])) for part in payload["parts"])
        part_numbers = {number for number, _ in parts}
        expected_parts = set(range(1, upload.total_parts + 1))
        if part_numbers != set(upload.uploaded_parts) or part_numbers != expected_parts:
            raise ValueError("Completed parts do not match uploaded parts")
        version = await self._version_for_upload(context, upload)
        is_initial_version = resource.current_version_id is None
        if is_initial_version:
            resource.transition_to(FileResourceStatus.UPLOADING)
        version.transition_to(FileResourceStatus.UPLOADING)
        try:
            metadata = await self.storage.complete_multipart_upload(
                version.object_key, upload.provider_upload_id, parts
            )
            if self.file_metadata_commit_tracker is not None:
                self.file_metadata_commit_tracker.register(
                    context.tenant_id,
                    context.biz_domain,
                    resource.resource_id,
                    version.version_id,
                )
            version.transition_to(FileResourceStatus.VERIFYING)
            if is_initial_version:
                resource.transition_to(FileResourceStatus.VERIFYING)
            checksum = str(payload["checksum"]).lower()
            if metadata.size_bytes != version.size_bytes or metadata.checksum.lower() != checksum:
                raise ValueError("uploaded object metadata does not match declaration")
            if metadata.content_type and metadata.content_type != version.mime_type:
                raise ValueError("uploaded object content type does not match declaration")
            if self.malware_scanner is not None:
                await self.malware_scanner.validate_metadata(
                    resource.normalized_filename,
                    version.mime_type,
                    metadata.size_bytes,
                    metadata.checksum,
                )
            version.checksum = metadata.checksum.lower()
            version.transition_to(FileResourceStatus.AVAILABLE)
            if self.file_versions is not None:
                await self.file_versions.save(version)
            if is_initial_version:
                self._apply_current_version(resource, version)
                resource.transition_to(FileResourceStatus.AVAILABLE)
                await self.files.save(resource)
            upload.mark_completed(self.clock.now())
            if self.file_uploads is not None:
                await self.file_uploads.save(upload)
        except Exception:
            if version.status in {FileResourceStatus.UPLOADING, FileResourceStatus.VERIFYING}:
                version.transition_to(FileResourceStatus.FAILED)
                if self.file_versions is not None:
                    await self.file_versions.save(version)
            if is_initial_version and resource.status in {
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
            elif version.status is FileResourceStatus.AVAILABLE:
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
        return await self._complete_result(resource, upload)

    async def abort_upload(
        self, context: RequestContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        resource = await self._file(context, str(payload["resource_id"]))
        upload = await self._upload(context, str(payload["upload_id"]))
        if upload.resource_id != resource.resource_id:
            raise FileResourceNotFound("File upload not found")
        if upload.status not in {UploadSessionStatus.ABORTED, UploadSessionStatus.COMPLETED}:
            version = await self._version_for_upload(context, upload)
            await self.storage.abort_multipart_upload(version.object_key, upload.provider_upload_id)
            upload.mark_aborted(self.clock.now())
            if version.status in {
                FileResourceStatus.PENDING_UPLOAD,
                FileResourceStatus.UPLOADING,
                FileResourceStatus.VERIFYING,
            }:
                version.transition_to(FileResourceStatus.FAILED)
                if self.file_versions is not None:
                    await self.file_versions.save(version)
            if self.file_uploads is not None:
                await self.file_uploads.save(upload)
            if resource.status in {
                FileResourceStatus.PENDING_UPLOAD,
                FileResourceStatus.UPLOADING,
            }:
                resource.transition_to(FileResourceStatus.FAILED)
                await self.files.save(resource)
        return {"resource": public_dict(resource)}

    async def create_upload_part_references(
        self, context: RequestContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        resource = await self._file(context, str(payload["resource_id"]))
        upload = await self._upload(context, str(payload["upload_session_id"]))
        if upload.resource_id != resource.resource_id:
            raise FileResourceNotFound("File upload not found")
        if self.upload_part_grants is None:
            raise RuntimeError("Upload part grant store is unavailable")
        now = self.clock.now()
        parts = tuple(sorted(set(int(part) for part in payload["parts"])))
        await self._ensure_upload_active(upload)
        upload.authorize_parts(parts, now)
        expires_at = min(
            upload.expires_at,
            now + timedelta(seconds=self.upload_part_grant_ttl_seconds),
        )
        references: list[dict[str, Any]] = []
        for part_number in parts:
            grant = UploadPartGrant(
                reference_id=self.ids.new_id("part"),
                resource_id=resource.resource_id,
                upload_session_id=upload.upload_id,
                tenant_id=context.tenant_id,
                biz_domain=context.biz_domain,
                caller_id=context.caller_id,
                caller_type=context.caller_type,
                request_id=context.request_id,
                trace_id=context.trace_id,
                part_number=part_number,
                expires_at=expires_at,
            )
            await self.upload_part_grants.issue(grant)
            references.append(
                {
                    "part_number": part_number,
                    "upload_reference": grant.reference_id,
                    "expires_at": expires_at.isoformat(),
                }
            )
        if self.file_uploads is not None:
            await self.file_uploads.save(upload)
        return {"parts": references}

    async def consume_upload_part(
        self, reference_id: str, content: bytes
    ) -> tuple[UploadPartGrant, str]:
        grant, upload, version = await self._consume_upload_part_grant(reference_id)
        try:
            etag = await self.storage.upload_part_content(
                version.object_key,
                upload.provider_upload_id,
                grant.part_number,
                content,
            )
            await self._mark_part_uploaded(upload, grant.part_number)
        except Exception as error:
            raise UploadPartTransferFailed(grant) from error
        return grant, etag

    async def consume_upload_part_stream(
        self,
        reference_id: str,
        content: AsyncIterator[bytes],
        content_length: int,
    ) -> tuple[UploadPartGrant, str]:
        grant, upload, version = await self._consume_upload_part_grant(reference_id)
        try:
            etag = await self.storage.upload_part_stream(
                version.object_key,
                upload.provider_upload_id,
                grant.part_number,
                content,
                content_length,
            )
            await self._mark_part_uploaded(upload, grant.part_number)
        except Exception as error:
            raise UploadPartTransferFailed(grant) from error
        return grant, etag

    async def _consume_upload_part_grant(
        self, reference_id: str
    ) -> tuple[UploadPartGrant, FileUploadSession, FileResourceVersion]:
        if self.upload_part_grants is None:
            raise FileResourceNotFound("Upload part reference not found")
        grant = await self.upload_part_grants.consume(reference_id)
        if grant is None or grant.expires_at <= self.clock.now():
            raise FileResourceNotFound("Upload part reference not found")
        context = RequestContext.model_construct(
            request_id=grant.request_id,
            trace_id=grant.trace_id,
            tenant_id=grant.tenant_id,
            biz_domain=grant.biz_domain,
            caller_type=grant.caller_type,
            caller_id=grant.caller_id,
        )
        upload = await self._upload(context, grant.upload_session_id)
        await self._ensure_upload_active(upload)
        if upload.resource_id != grant.resource_id:
            raise FileResourceNotFound("Upload part reference not found")
        version = await self._version_for_upload(context, upload)
        return grant, upload, version

    async def _mark_part_uploaded(self, upload: FileUploadSession, part_number: int) -> None:
        upload.part_uploaded(part_number, self.clock.now())
        if self.file_uploads is not None:
            await self.file_uploads.save(upload)

    async def create_version_upload(
        self, context: RequestContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        resource = await self._available_file(context, str(payload["resource_id"]))
        if self.file_versions is None or self.file_uploads is None:
            raise RuntimeError("File version persistence is unavailable")
        versions = await self.file_versions.list_by_scope_and_resource(
            context.tenant_id, context.biz_domain, resource.resource_id
        )
        version_number = max((item.version for item in versions), default=0) + 1
        object_key = generate_object_key(
            context.tenant_id,
            context.biz_domain,
            resource.resource_id,
            version_number,
            resource.normalized_filename,
        )
        await self.storage.initialize_upload(
            object_key, str(payload["mime_type"]), int(payload["size_bytes"])
        )
        handle = await self.storage.create_multipart_upload(object_key, str(payload["mime_type"]))
        now = self.clock.now()
        version = FileResourceVersion(
            version_id=self.ids.new_id("ver"),
            resource_id=resource.resource_id,
            tenant_id=context.tenant_id,
            biz_domain=context.biz_domain,
            version=version_number,
            object_key=object_key,
            size_bytes=int(payload["size_bytes"]),
            checksum=None,
            status=FileResourceStatus.PENDING_UPLOAD,
            created_at=now,
            mime_type=str(payload["mime_type"]),
        )
        upload = FileUploadSession(
            upload_id=self.ids.new_id("upl"),
            resource_id=resource.resource_id,
            tenant_id=context.tenant_id,
            biz_domain=context.biz_domain,
            provider_upload_id=handle.provider_upload_id,
            upload_reference=self.ids.new_id("upref"),
            expires_at=now + timedelta(seconds=self.upload_ttl_seconds),
            status=UploadSessionStatus.INIT,
            version_id=version.version_id,
            created_at=now,
            updated_at=now,
        )
        try:
            await self.file_versions.add(version)
            await self.file_uploads.add(upload)
        except Exception:
            await self.storage.abort_multipart_upload(object_key, handle.provider_upload_id)
            raise
        return {
            "resource_id": resource.resource_id,
            "version": self._public_version(version),
            "upload_session_id": upload.upload_id,
            "expires_at": upload.expires_at.isoformat(),
        }

    async def switch_current_version(
        self, context: RequestContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        resource = await self._available_file(context, str(payload["resource_id"]))
        version = await self._version(context, str(payload["version_id"]))
        if (
            version.resource_id != resource.resource_id
            or version.status is not FileResourceStatus.AVAILABLE
        ):
            raise FileResourceNotFound("File version not found")
        if resource.current_version_id != version.version_id:
            self._apply_current_version(resource, version)
            await self.files.save(resource)
        return {"resource": public_dict(resource), "version": self._public_version(version)}

    async def delete_version(
        self, context: RequestContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        resource = await self._file(context, str(payload["resource_id"]))
        version = await self._version(context, str(payload["version_id"]))
        if version.resource_id != resource.resource_id:
            raise FileResourceNotFound("File version not found")
        if resource.current_version_id == version.version_id:
            raise ValueError("Current version cannot be deleted")
        if version.status is FileResourceStatus.DELETED:
            return {"version": self._public_version(version)}
        version.transition_to(FileResourceStatus.DELETING)
        try:
            await self.storage.delete(version.object_key)
            if self.file_metadata_commit_tracker is not None:
                self.file_metadata_commit_tracker.register_delete(
                    context.tenant_id,
                    context.biz_domain,
                    resource.resource_id,
                    version.version_id,
                )
            version.transition_to(FileResourceStatus.DELETED)
            if self.file_versions is not None:
                await self.file_versions.save(version)
        except Exception:
            version.transition_to(FileResourceStatus.FAILED)
            if self.file_versions is not None:
                await self.file_versions.save(version)
            await self._record_delete_pending(resource, version.version_id)
            raise
        return {"version": self._public_version(version)}

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
            "versions": [self._public_version(item) for item in versions],
        }

    async def delete_file(self, context: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
        resource = await self._file(context, str(payload["resource_id"]))
        if resource.status is FileResourceStatus.DELETED:
            return {"resource": public_dict(resource)}
        resource.transition_to(FileResourceStatus.DELETING)
        uploads = (
            await self.file_uploads.list_by_scope_and_resource(
                context.tenant_id, context.biz_domain, resource.resource_id
            )
            if self.file_uploads is not None
            else []
        )
        versions = (
            await self.file_versions.list_by_scope_and_resource(
                context.tenant_id, context.biz_domain, resource.resource_id
            )
            if self.file_versions is not None
            else []
        )
        versions_by_id = {version.version_id: version for version in versions}
        try:
            for upload in uploads:
                if upload.status in {
                    UploadSessionStatus.COMPLETED,
                    UploadSessionStatus.ABORTED,
                }:
                    continue
                version = versions_by_id.get(upload.version_id or "")
                if version is None:
                    raise FileResourceNotFound("File version for upload not found")
                await self.storage.abort_multipart_upload(
                    version.object_key, upload.provider_upload_id
                )
                if self.file_metadata_commit_tracker is not None:
                    self.file_metadata_commit_tracker.register_delete(
                        context.tenant_id,
                        context.biz_domain,
                        resource.resource_id,
                        version.version_id,
                    )
                upload.mark_aborted(self.clock.now())
                if self.file_uploads is not None:
                    await self.file_uploads.save(upload)
                if version.status in {
                    FileResourceStatus.PENDING_UPLOAD,
                    FileResourceStatus.UPLOADING,
                    FileResourceStatus.VERIFYING,
                }:
                    version.transition_to(FileResourceStatus.FAILED)
                    if self.file_versions is not None:
                        await self.file_versions.save(version)
            for version in versions:
                if version.status is FileResourceStatus.DELETED:
                    continue
                if version.status is not FileResourceStatus.DELETING:
                    version.transition_to(FileResourceStatus.DELETING)
                await self.storage.delete(version.object_key)
                if self.file_metadata_commit_tracker is not None:
                    self.file_metadata_commit_tracker.register_delete(
                        context.tenant_id,
                        context.biz_domain,
                        resource.resource_id,
                        version.version_id,
                    )
                version.transition_to(FileResourceStatus.DELETED)
                if self.file_versions is not None:
                    await self.file_versions.save(version)
            if not versions:
                await self.storage.delete(resource.object_key)
                if self.file_metadata_commit_tracker is not None:
                    self.file_metadata_commit_tracker.register_delete(
                        context.tenant_id,
                        context.biz_domain,
                        resource.resource_id,
                        None,
                    )
            resource.transition_to(FileResourceStatus.DELETED)
        except Exception:
            resource.transition_to(FileResourceStatus.FAILED)
            await self.files.save(resource)
            await self._record_delete_pending(resource, None)
            raise
        await self.files.save(resource)
        return {"resource": public_dict(resource)}

    async def processor_input_reference(
        self, context: RequestContext, resource_id: str, version_id: str | None = None
    ) -> ProcessorInputReference:
        resource = await self._available_file(context, resource_id)
        selected_id = version_id or resource.current_version_id
        if selected_id is None:
            raise FileResourceNotFound("Current file version not found")
        version = await self._version(context, selected_id)
        if (
            version.resource_id != resource.resource_id
            or version.status is not FileResourceStatus.AVAILABLE
        ):
            raise FileResourceNotFound("File version not found")
        if version.checksum is None:
            raise ValueError("File version checksum is unavailable")
        return ProcessorInputReference(
            resource_id=resource.resource_id,
            version_id=version.version_id,
            tenant_id=context.tenant_id,
            biz_domain=context.biz_domain,
            mime_type=version.mime_type,
            checksum=version.checksum,
            storage_reference=f"file-resource:{resource.resource_id}:{version.version_id}",
        )

    async def _complete_result(
        self, resource: FileResource, upload: FileUploadSession
    ) -> dict[str, Any]:
        version = None
        if self.file_versions is not None and upload.version_id is not None:
            version = await self.file_versions.get_by_scope_and_id(
                upload.tenant_id, upload.biz_domain, upload.version_id
            )
        result: dict[str, Any] = {"resource": public_dict(resource)}
        if version is not None:
            result["version"] = self._public_version(version)
        return result

    async def _version_for_upload(
        self, context: RequestContext, upload: FileUploadSession
    ) -> FileResourceVersion:
        if upload.version_id is None:
            resource = await self._file(context, upload.resource_id)
            return FileResourceVersion(
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
                mime_type=resource.mime_type,
            )
        return await self._version(context, upload.version_id)

    async def _version(self, context: RequestContext, version_id: str) -> FileResourceVersion:
        version = (
            await self.file_versions.get_by_scope_and_id(
                context.tenant_id, context.biz_domain, version_id
            )
            if self.file_versions is not None
            else None
        )
        if version is None:
            raise FileResourceNotFound("File version not found")
        return version

    def _apply_current_version(self, resource: FileResource, version: FileResourceVersion) -> None:
        resource.current_version_id = version.version_id
        resource.object_key = version.object_key
        resource.mime_type = version.mime_type
        resource.size_bytes = version.size_bytes
        resource.sha256 = version.checksum
        resource.version = version.version
        resource.updated_at = self.clock.now()

    @staticmethod
    def _public_version(version: FileResourceVersion) -> dict[str, Any]:
        return {
            "version_id": version.version_id,
            "resource_id": version.resource_id,
            "version_number": version.version,
            "size_bytes": version.size_bytes,
            "checksum": version.checksum,
            "mime_type": version.mime_type,
            "status": version.status.value,
            "created_at": version.created_at.isoformat(),
        }

    async def _record_delete_pending(self, resource: FileResource, version_id: str | None) -> None:
        payload: dict[str, Any] = {
            "tenant_id": resource.tenant_id,
            "biz_domain": resource.biz_domain,
            "resource_id": resource.resource_id,
        }
        if version_id is not None:
            payload["version_id"] = version_id
        await self.reconciliation.record(
            f"file-delete:{resource.resource_id}:{version_id or 'all'}",
            "FILE_DELETE_PENDING",
            payload,
        )

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

    async def _ensure_upload_active(self, upload: FileUploadSession) -> None:
        try:
            upload.ensure_active(self.clock.now())
        except InvalidStateTransition:
            if upload.status is UploadSessionStatus.EXPIRED and self.file_uploads is not None:
                await self.file_uploads.save(upload)
            raise

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
