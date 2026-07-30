from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

T = TypeVar("T")


class MinIOExecutor:
    def __init__(self, max_workers: int) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="dcs-minio")
        self._semaphore = asyncio.Semaphore(max_workers)

    async def run(self, func: Callable[[], T]) -> T:
        loop = asyncio.get_running_loop()
        async with self._semaphore:
            return await loop.run_in_executor(self._executor, func)

    async def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)
