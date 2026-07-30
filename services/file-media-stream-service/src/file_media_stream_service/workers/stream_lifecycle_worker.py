import asyncio
import logging
from contextlib import suppress

from file_media_stream_service.application.ports.protocols import TransactionManager
from file_media_stream_service.application.use_cases import StreamLifecycleService

logger = logging.getLogger(__name__)


class StreamLifecycleWorker:
    """Single independently deployed lifecycle loop; never runs inside FastAPI."""

    def __init__(
        self,
        lifecycle: StreamLifecycleService,
        interval_seconds: float = 30.0,
        transactions: TransactionManager | None = None,
    ) -> None:
        self.lifecycle = lifecycle
        self.interval_seconds = interval_seconds
        self.transactions = transactions
        self._shutdown = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._shutdown.clear()
        self._task = asyncio.create_task(self._run())

    async def shutdown(self) -> None:
        self._shutdown.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def run_once(self) -> None:
        try:
            await self.lifecycle.reconcile_all()
            if self.transactions is not None:
                await self.transactions.commit()
        except Exception:
            if self.transactions is not None:
                await self.transactions.rollback()
            raise
        finally:
            if self.transactions is not None:
                await self.transactions.close()

    async def _run(self) -> None:
        while not self._shutdown.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("stream lifecycle worker cycle failed")
            try:
                await asyncio.wait_for(self._shutdown.wait(), self.interval_seconds)
            except TimeoutError:
                continue
