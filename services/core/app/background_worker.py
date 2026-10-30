"""Core one-shot/polling runner for independent background module workers."""

import argparse
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
    parser = argparse.ArgumentParser(description="Xử lý thông báo và email tài khoản trong nền")
    parser.add_argument("--once", action="store_true", help="Xử lý một lượt rồi dừng")
    parser.add_argument("--batch-size", type=int, default=100, help="Số mục xử lý mỗi lượt")
    parser.add_argument("--poll-seconds", type=float, default=2, help="Số giây chờ giữa các lượt")
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= 1000 or args.poll_seconds <= 0:
        parser.error("Số mục mỗi lượt cần từ 1 đến 1000 và thời gian chờ phải lớn hơn 0.")
    stop = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        result = run_batch(args.batch_size)
        if result["notification_events"] or result["credential_attempted"]:
            logger.info(
                "Đã xử lý một lượt thông báo và email: %s thông báo; thử gửi %s email, "
                "gửi thành công %s, đang chờ %s, đã hủy %s, cần cấp lại %s.",
                result["notification_events"],
                result["credential_attempted"],
                result["credential_delivered"],
                result["credential_pending"],
                result["credential_cancelled"],
                result["credential_needs_reissue"],
            )
        if args.once:
            break
        stop.wait(args.poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
