from collections.abc import Mapping
from typing import Any


class InMemoryEventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, event_name: str, payload: Mapping[str, Any]) -> None:
        self.events.append((event_name, dict(payload)))
