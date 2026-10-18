"""Run with python -m app.modules.notification.worker [--once]."""

import argparse
import logging
import signal
from datetime import timedelta
from threading import Event

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.common.db import SessionLocal, transaction
from app.common.outbox import OutboxEvent
from app.modules.notification.events import EVENT_SCHEMAS, InvalidEvent, dedup_key, prepare_delivery
from app.modules.notification.repository import NotificationRepository

logger = logging.getLogger(__name__)


def drain_outbox(*, session_factory=SessionLocal, batch_size: int = 100) -> int:
    """One event/transaction; SKIP LOCKED permits multiple worker processes.

    Notification insert + published_at commit together. Exceptions/crashes roll
    back both, while the committed business transaction remains intact.
    """
    delivered = 0
    for _ in range(batch_size):
        event_id = None
        try:
            with session_factory() as session, transaction(session):
                event = session.scalar(
                    select(OutboxEvent)
                    .where(
                        OutboxEvent.published_at.is_(None),
                        OutboxEvent.available_at <= func.clock_timestamp(),
                        OutboxEvent.event_type.in_(EVENT_SCHEMAS),
                    )
                    .order_by(OutboxEvent.created_at, OutboxEvent.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                if event is None:
                    break
                event_id = event.id
                recipients, payload = prepare_delivery(session, event)
                repository = NotificationRepository(session)
                # Globally sorted locks prevent deadlocks between fanouts.
                for recipient_id in sorted(recipients):
                    repository.create(
                        recipient_id=recipient_id,
                        event_type=event.event_type,
                        payload=payload,
                        dedup_key=dedup_key(event, recipient_id),
                    )
                event.published_at = func.clock_timestamp()
                event.last_error_code = None
            delivered += 1
        except Exception as exc:  # noqa: BLE001 -- isolate poison events; never log raw exception data
            # Never log exception text/SQL parameters or an event's raw payload.
            code = (
                "INVALID_EVENT"
                if isinstance(exc, (InvalidEvent, ValidationError))
                else "DELIVERY_FAILED"
            )
            logger.warning("Notification delivery deferred: event_id=%s code=%s", event_id, code)
            if event_id is None:
                break  # DB unavailable; polling loop retries after its interval.
            try:
                with session_factory() as session, transaction(session):
                    event = session.scalar(
                        select(OutboxEvent)
                        .where(OutboxEvent.id == event_id, OutboxEvent.published_at.is_(None))
                        .with_for_update()
                    )
                    if event is not None:
                        event.attempts += 1
                        event.available_at = func.clock_timestamp() + timedelta(
                            seconds=min(300, 2 ** min(event.attempts, 9))
                        )
                        event.last_error_code = code
            except SQLAlchemyError:
                logger.warning("Notification retry scheduling unavailable: event_id=%s", event_id)
                break
    return delivered


def main() -> None:
    parser = argparse.ArgumentParser(description="Core in-app notification outbox worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--poll-seconds", type=float, default=2)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 1000 or args.poll_seconds <= 0:
        parser.error("batch-size must be 1..1000 and poll-seconds must be positive")
    stop = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        drain_outbox(batch_size=args.batch_size)
        if args.once:
            break
        stop.wait(args.poll_seconds)


if __name__ == "__main__":
    main()
