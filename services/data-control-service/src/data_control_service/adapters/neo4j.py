from data_control_service.adapters.base import ControlledInMemoryAdapter
from data_control_service.contracts.enums import DataTarget, Operation


class Neo4jAdapter(ControlledInMemoryAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="neo4j",
            target=DataTarget.NEO4J,
            operations=frozenset(
                {
                    Operation.GET,
                    Operation.SEARCH,
                    Operation.CREATE,
                    Operation.UPDATE,
                    Operation.DELETE,
                    Operation.BATCH,
                }
            ),
            supports_transactions=True,
            supports_cursor_pagination=True,
        )
