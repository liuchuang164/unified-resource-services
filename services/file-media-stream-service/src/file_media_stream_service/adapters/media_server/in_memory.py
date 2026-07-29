from datetime import datetime


class InMemoryMediaServer:
    def __init__(self) -> None:
        self.sessions: dict[str, bool] = {}

    async def create_session(
        self, protocol: str, direction: str, lease_expires_at: datetime
    ) -> str:
        reference = f"media-ref:{protocol}:{direction}:{lease_expires_at.timestamp()}"
        self.sessions[reference] = True
        return reference

    async def close_session(self, endpoint_reference: str) -> None:
        self.sessions[endpoint_reference] = False
