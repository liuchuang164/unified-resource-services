from datetime import UTC, datetime
from uuid import uuid4


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidIdentifierFactory:
    def new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid4().hex}"
