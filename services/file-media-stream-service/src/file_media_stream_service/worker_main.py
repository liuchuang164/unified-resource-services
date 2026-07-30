import asyncio
import signal

from file_media_stream_service.bootstrap import ProductionContainer, build_container
from file_media_stream_service.config import Settings


async def run_worker() -> None:
    container = build_container(Settings())
    if not isinstance(container, ProductionContainer):
        raise RuntimeError("Stream lifecycle worker requires production infrastructure")
    if container.lifecycle_worker is None:
        raise RuntimeError("Stream lifecycle worker is not configured")
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_name, stopped.set)
    await container.lifecycle_worker.start()
    try:
        await stopped.wait()
    finally:
        await container.lifecycle_worker.shutdown()
        await container.transaction.close()


if __name__ == "__main__":
    asyncio.run(run_worker())
