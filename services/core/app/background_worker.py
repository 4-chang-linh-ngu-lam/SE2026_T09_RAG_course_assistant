"""Core one-shot/polling runner for independent background module workers."""

import argparse
import json
import logging
import signal
from threading import Event

from app.modules.identity.delivery_worker import drain_pending_deliveries
from app.modules.notification.worker import drain_outbox

logger = logging.getLogger(__name__)


def run_batch(batch_size: int) -> dict[str, int]:
    published = drain_outbox(batch_size=batch_size)
    credentials = drain_pending_deliveries(batch_size=batch_size)
    return {
        "notification_events": published,
        **{f"credential_{key}": value for key, value in credentials.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run independent Core background workers")
    parser.add_argument("--once", action="store_true", help="Run one batch and exit")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--poll-seconds", type=float, default=2)
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= 1000 or args.poll_seconds <= 0:
        parser.error("batch-size must be 1..1000 and poll-seconds must be positive")
    stop = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        result = run_batch(args.batch_size)
        if result["notification_events"] or result["credential_attempted"]:
            logger.info("Core background batch completed: %s", json.dumps(result, sort_keys=True))
        if args.once:
            break
        stop.wait(args.poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
