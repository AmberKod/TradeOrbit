"""E01 heartbeat only. No trading, exchange connections, or strategy execution."""

import argparse
import asyncio
import os
import signal
from datetime import UTC, datetime

import structlog
from redis.asyncio import Redis

from app.core.logging import configure_logging

HEARTBEAT_KEY = "tradeorbit:worker:foundation:heartbeat"


async def run(check: bool = False) -> None:
    redis = Redis.from_url(
        os.environ["TRADEORBIT_REDIS_URL"], socket_connect_timeout=3, socket_timeout=3
    )
    try:
        if check:
            if not await redis.exists(HEARTBEAT_KEY):
                raise SystemExit(1)
            return
        configure_logging()
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
        log = structlog.get_logger()
        log.info("worker.started", stage="E01")
        while not stop.is_set():
            try:
                await redis.set(HEARTBEAT_KEY, datetime.now(UTC).isoformat(), ex=30)
            except Exception as exc:
                log.error("worker.heartbeat_failed", error_type=type(exc).__name__)
            try:
                await asyncio.wait_for(stop.wait(), timeout=10)
            except TimeoutError:
                pass
        await redis.delete(HEARTBEAT_KEY)
        log.info("worker.stopped")
    finally:
        await redis.aclose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    asyncio.run(run(parser.parse_args().check))


if __name__ == "__main__":
    main()
