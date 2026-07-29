from typing import Protocol

from data_control_service.contracts.enums import DataTarget
from data_control_service.domain.policies import ResourceMapping


class ResourceMappingRepository(Protocol):
    def get_mapping(
        self,
        *,
        tenant_id: str,
        biz_domain: str,
        target: DataTarget,
        resource_type: str,
        logical_name: str,
    ) -> ResourceMapping | None: ...

    async def health(self) -> dict[str, str]: ...
