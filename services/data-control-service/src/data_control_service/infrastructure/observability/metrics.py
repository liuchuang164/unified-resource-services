from __future__ import annotations

from collections import defaultdict
from threading import Lock


class MetricsRegistry:
    def __init__(self) -> None:
        self._counters: defaultdict[str, int] = defaultdict(int)
        self._gauges: dict[str, float] = {}
        self._lock = Lock()

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] += amount

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return {**self._counters, **self._gauges}

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()


metrics_registry = MetricsRegistry()
