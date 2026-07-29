from data_control_service.adapters.base import ControlledInMemoryAdapter
from data_control_service.contracts.enums import DataTarget, Operation


class RedisAdapter(ControlledInMemoryAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="redis",
            target=DataTarget.REDIS,
            operations=frozenset(
                {
                    Operation.GET,
                    Operation.UPSERT,
                    Operation.DELETE,
                    Operation.LOCK,
                    Operation.UNLOCK,
                }
            ),
            supports_transactions=False,
            supports_cursor_pagination=False,
        )
