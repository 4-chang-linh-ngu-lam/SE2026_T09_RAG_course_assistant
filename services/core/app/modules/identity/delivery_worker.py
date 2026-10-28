"""Retry pending staff verification and password-reset email deliveries.

Run once per invocation; Cloud Scheduler owns cadence. The worker never logs
token material, recipient addresses, or SMTP/provider error text.
"""

import argparse
import json
import logging
import signal
from collections import Counter
from datetime import UTC, datetime
from threading import Event

from sqlalchemy.orm import Session, sessionmaker

from app.common.db import SessionLocal
from app.modules.identity.email_delivery import get_token_sender
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.service import IdentityService

logger = logging.getLogger(__name__)


def drain_pending_deliveries(
    *,
    batch_size: int = 100,
    session_factory: sessionmaker[Session] = SessionLocal,
    sender=None,
) -> dict[str, int]:
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    sender = sender or get_token_sender()
    with session_factory() as session:
        token_ids = IdentityRepository(session).due_credential_delivery_ids(
            datetime.now(UTC), batch_size
        )

    outcomes: Counter[str] = Counter()
    for token_id in token_ids:
        with session_factory() as session:
            status = IdentityService(session).attempt_token_delivery(token_id, sender.send)
        outcomes[status.lower()] += 1
    return {
        "attempted": len(token_ids),
        "delivered": outcomes["delivered"],
        "pending": outcomes["pending"],
        "cancelled": outcomes["cancelled"],
        "needs_reissue": outcomes["needs_reissue"],
        "untracked": outcomes["untracked"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Retry due credential email deliveries once")
    parser.add_argument("--once", action="store_true", help="Run one batch and exit")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--poll-seconds", type=float, default=900)
    args = parser.parse_args(argv)
    if args.poll_seconds <= 0:
        parser.error("poll-seconds must be positive")
    stop = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        result = drain_pending_deliveries(batch_size=args.batch_size)
        if result["attempted"]:
            logger.info(
                "Credential delivery batch completed: %s", json.dumps(result, sort_keys=True)
            )
        if args.once:
            break
        stop.wait(args.poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
