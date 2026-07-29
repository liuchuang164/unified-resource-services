from data_control_service.adapters.base import ControlledInMemoryAdapter
from data_control_service.contracts.enums import DataTarget, Operation


class PostgreSQLAdapter(ControlledInMemoryAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="postgresql",
            target=DataTarget.POSTGRESQL,
            operations=frozenset(
                {
                    Operation.GET,
                    Operation.LIST,
                    Operation.CREATE,
                    Operation.UPDATE,
                    Operation.UPSERT,
                    Operation.DELETE,
                    Operation.BATCH,
                }
            ),
            supports_transactions=True,
            supports_cursor_pagination=True,
        )
