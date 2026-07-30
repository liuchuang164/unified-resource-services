import asyncio
from copy import deepcopy
from typing import Any

from file_media_stream_service.domain.entities.models import (
    FileResource,
    ProcessingJob,
    StreamEvent,
    StreamSession,
)
from file_media_stream_service.domain.enums import StreamSessionStatus
from file_media_stream_service.domain.exceptions.errors import IdempotencyConflict


class InMemoryState:
    def __init__(self) -> None:
        self.files: dict[tuple[str, str, str], FileResource] = {}
        self.sessions: dict[tuple[str, str, str], StreamSession] = {}
        self.jobs: dict[tuple[str, str, str], ProcessingJob] = {}


class InMemoryFileRepository:
    def __init__(self, state: InMemoryState) -> None:
        self.state = state

    async def add(self, resource: FileResource) -> None:
        key = (resource.tenant_id, resource.biz_domain, resource.resource_id)
        self.state.files[key] = deepcopy(resource)

    async def get_by_scope_and_id(
        self, tenant_id: str, biz_domain: str, resource_id: str
    ) -> FileResource | None:
        value = self.state.files.get((tenant_id, biz_domain, resource_id))
        return deepcopy(value)

    async def delete(self, tenant_id: str, biz_domain: str, resource_id: str) -> None:
        self.state.files.pop((tenant_id, biz_domain, resource_id), None)


class InMemoryStreamSessionRepository:
    def __init__(self, state: InMemoryState) -> None:
        self.state = state

    async def add(self, session: StreamSession) -> None:
        self.state.sessions[(session.tenant_id, session.biz_domain, session.session_id)] = deepcopy(
            session
        )

    async def save(self, session: StreamSession) -> None:
        await self.add(session)

    async def get_by_scope_and_id(
        self, tenant_id: str, biz_domain: str, session_id: str
    ) -> StreamSession | None:
        value = self.state.sessions.get((tenant_id, biz_domain, session_id))
        return deepcopy(value)

    async def list_recoverable(self, tenant_id: str, biz_domain: str) -> list[StreamSession]:
        return [
            deepcopy(session)
            for (tenant, domain, _), session in self.state.sessions.items()
            if tenant == tenant_id
            and domain == biz_domain
            and session.status in {StreamSessionStatus.READY, StreamSessionStatus.ACTIVE}
        ]


class InMemoryStreamEventSink:
    def __init__(self) -> None:
        self.events: list[StreamEvent] = []

    async def write_stream_event(self, event: StreamEvent) -> None:
        self.events.append(deepcopy(event))


class InMemoryProcessingJobRepository:
    def __init__(self, state: InMemoryState) -> None:
        self.state = state

    async def add(self, job: ProcessingJob) -> None:
        self.state.jobs[(job.tenant_id, job.biz_domain, job.job_id)] = deepcopy(job)

    async def save(self, job: ProcessingJob) -> None:
        await self.add(job)

    async def get_by_scope_and_id(
        self, tenant_id: str, biz_domain: str, job_id: str
    ) -> ProcessingJob | None:
        value = self.state.jobs.get((tenant_id, biz_domain, job_id))
        return deepcopy(value)


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self.records: dict[tuple[str, ...], tuple[str, str, dict[str, Any] | None]] = {}
        self._locks: dict[tuple[str, ...], asyncio.Lock] = {}
        self._events: dict[tuple[str, ...], asyncio.Event] = {}

    async def reserve(
        self,
        scope: tuple[str, ...],
        request_hash: str,
    ) -> tuple[str, dict[str, Any] | None]:
        lock = self._locks.setdefault(scope, asyncio.Lock())
        async with lock:
            existing = self.records.get(scope)
            if existing is not None:
                old_hash, status, result = existing
                if old_hash != request_hash:
                    raise IdempotencyConflict("Idempotency key was used with another request")
                return ("COMPLETED", result) if status == "COMPLETED" else ("WAIT", None)
            self.records[scope] = (request_hash, "IN_PROGRESS", None)
            self._events[scope] = asyncio.Event()
            return ("OWNER", None)

    async def wait(self, scope: tuple[str, ...]) -> None:
        await self._events[scope].wait()

    async def complete(
        self, scope: tuple[str, ...], request_hash: str, result: dict[str, Any]
    ) -> None:
        async with self._locks[scope]:
            self.records[scope] = (request_hash, "COMPLETED", result)
            self._events[scope].set()

    async def fail(self, scope: tuple[str, ...]) -> None:
        async with self._locks[scope]:
            self.records.pop(scope, None)
            self._events[scope].set()
