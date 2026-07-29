from data_control_service.adapters.base import ControlledInMemoryAdapter
from data_control_service.contracts.enums import DataTarget, Operation


class MinIOAdapter(ControlledInMemoryAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="minio",
            target=DataTarget.MINIO,
            operations=frozenset(
                {Operation.GET, Operation.CREATE, Operation.DELETE, Operation.LIST}
            ),
            supports_transactions=False,
            supports_cursor_pagination=True,
        )
