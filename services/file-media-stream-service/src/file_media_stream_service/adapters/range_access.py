from copy import deepcopy
from datetime import UTC, datetime

from file_media_stream_service.domain.entities import RangeAccessGrant


class InMemoryRangeAccessGrantStore:
    def __init__(self) -> None:
        self.grants: dict[str, RangeAccessGrant] = {}

    async def issue(self, grant: RangeAccessGrant) -> None:
        self.grants[grant.reference_id] = deepcopy(grant)

    async def consume(self, reference_id: str) -> RangeAccessGrant | None:
        grant = self.grants.pop(reference_id, None)
        if grant is None or grant.expires_at <= datetime.now(UTC):
            return None
        return deepcopy(grant)
