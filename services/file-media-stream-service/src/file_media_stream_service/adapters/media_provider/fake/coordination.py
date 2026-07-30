from file_media_stream_service.application.ports.media_provider import StreamLease


class InMemoryStreamCoordination:
    def __init__(self) -> None:
        self.leases: dict[tuple[str, str, str], StreamLease] = {}
        self._fencing = 0

    async def acquire_stream_lease(
        self, tenant_id: str, biz_domain: str, session_id: str
    ) -> StreamLease | None:
        key = (tenant_id, biz_domain, session_id)
        if key in self.leases:
            return None
        self._fencing += 1
        lease = StreamLease(tenant_id, biz_domain, session_id, self._fencing)
        self.leases[key] = lease
        return lease

    async def heartbeat_stream(self, lease: StreamLease) -> bool:
        return self.leases.get((lease.tenant_id, lease.biz_domain, lease.session_id)) == lease

    async def release_stream(self, lease: StreamLease) -> bool:
        key = (lease.tenant_id, lease.biz_domain, lease.session_id)
        if self.leases.get(key) != lease:
            return False
        del self.leases[key]
        return True
