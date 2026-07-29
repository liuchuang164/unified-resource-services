from data_control_service.adapters.base import ControlledInMemoryAdapter
from data_control_service.contracts.enums import DataTarget, Operation


class MilvusAdapter(ControlledInMemoryAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="milvus",
            target=DataTarget.MILVUS,
            operations=frozenset(
                {Operation.CREATE, Operation.UPSERT, Operation.SEARCH, Operation.DELETE}
            ),
            supports_transactions=False,
            supports_cursor_pagination=False,
        )
