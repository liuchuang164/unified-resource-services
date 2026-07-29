from data_control_service.adapters.base import ControlledInMemoryAdapter
from data_control_service.contracts.enums import DataTarget, Operation


class TimescaleDBAdapter(ControlledInMemoryAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="timescaledb",
            target=DataTarget.TIMESCALEDB,
            operations=frozenset(
                {Operation.CREATE, Operation.BATCH, Operation.LIST, Operation.SEARCH}
            ),
            supports_transactions=True,
            supports_cursor_pagination=True,
        )
