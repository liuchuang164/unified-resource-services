from collections.abc import Mapping
from typing import Any


class InMemoryProcessor:
    def __init__(self) -> None:
        self.submissions: list[tuple[str, str, dict[str, Any]]] = []

    async def submit(
        self, processor_type: str, input_resource_id: str, options: Mapping[str, Any]
    ) -> None:
        self.submissions.append((processor_type, input_resource_id, dict(options)))
