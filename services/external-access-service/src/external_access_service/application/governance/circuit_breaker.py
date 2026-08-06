from dataclasses import dataclass
from enum import StrEnum
from time import monotonic

from external_access_service.domain.errors import CircuitOpen, DomainError
from external_access_service.domain.models import ProviderCode


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass(slots=True)
class Circuit:
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    opened_at: float | None = None


class CircuitBreakerService:
    def __init__(self, failure_threshold: int = 2, recovery_seconds: float = 30) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._circuits: dict[ProviderCode, Circuit] = {}

    async def before_call(self, provider: ProviderCode) -> None:
        circuit = self._circuits.setdefault(provider, Circuit())
        if circuit.state == CircuitState.OPEN:
            if (
                circuit.opened_at is not None
                and monotonic() - circuit.opened_at >= self.recovery_seconds
            ):
                circuit.state = CircuitState.HALF_OPEN
                return
            raise CircuitOpen("Provider circuit is open", {"provider": provider.value})

    async def record_success(self, provider: ProviderCode) -> None:
        self._circuits[provider] = Circuit()

    async def record_failure(self, provider: ProviderCode, error: DomainError) -> None:
        if not error.retryable:
            return
        circuit = self._circuits.setdefault(provider, Circuit())
        circuit.failure_count += 1
        if (
            circuit.state == CircuitState.HALF_OPEN
            or circuit.failure_count >= self.failure_threshold
        ):
            circuit.state = CircuitState.OPEN
            circuit.opened_at = monotonic()

    def state(self, provider: ProviderCode) -> CircuitState:
        return self._circuits.setdefault(provider, Circuit()).state
