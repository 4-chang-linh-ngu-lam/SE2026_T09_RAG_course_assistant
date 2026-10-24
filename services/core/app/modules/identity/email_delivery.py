import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import quote

from app.common.config import settings
from app.common.errors import AppError
from app.modules.identity.models import TokenPurpose
from app.modules.identity.service import TokenDelivery


class SMTPTokenSender:
    def __init__(self):
        if not settings.smtp_host or not settings.smtp_from:
            raise AppError(503, "Email delivery unavailable")
        if bool(settings.smtp_username) != bool(settings.smtp_password):
            raise AppError(503, "Email delivery unavailable")

    def send(self, delivery: TokenDelivery) -> None:
        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = delivery.recipient
        message["Subject"] = {
            TokenPurpose.EMAIL_VERIFICATION: "Verify your RAG Course Assistant email",
            TokenPurpose.PASSWORD_RESET: "Reset your password",
            TokenPurpose.ADMIN_INVITATION: "Set your RAG Course Assistant password",
        }[delivery.purpose]
        route = {
            TokenPurpose.ADMIN_INVITATION: "/staff/invitation",
            TokenPurpose.PASSWORD_RESET: "/reset-password",
        }.get(delivery.purpose)
        if route is not None:
            if not settings.web_origin:
                raise AppError(503, "Email delivery unavailable")
            token = quote(delivery.token.get_secret_value(), safe="")
            # A fragment is never part of the HTTP request or Referer. Web reads
            # it into memory and removes it before the user submits a password.
            link = f"{settings.web_origin}{route}#token={token}"
            heading = (
                "Bạn được mời sử dụng Lumi. Mở liên kết dưới đây để thiết lập mật khẩu:"
                if delivery.purpose == TokenPurpose.ADMIN_INVITATION
                else "Mở liên kết dưới đây để đặt lại mật khẩu Lumi:"
            )
            message.set_content(
                f"{heading}\n\n{link}\n\n"
                f"Liên kết chỉ dùng một lần, hết hạn lúc: {delivery.expires_at.isoformat()}\n"
                "Nếu bạn không yêu cầu thao tác này, hãy bỏ qua email."
            )
        else:
            # Legacy email verification has no approved Web page. Registration
            # remains blocked; do not invent a route for that separate purpose.
            message.set_content(
                f"Your one-time token: {delivery.token.get_secret_value()}\n"
                f"Expires at: {delivery.expires_at.isoformat()}\n"
                "If you did not request this, ignore this email."
            )
        context = ssl.create_default_context()
        try:
            if settings.smtp_security == "tls":
                client = smtplib.SMTP_SSL(
                    settings.smtp_host,
                    settings.smtp_port,
                    timeout=settings.smtp_timeout_seconds,
                    context=context,
                )
            else:
                client = smtplib.SMTP(
                    settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
                )
            with client:
                if settings.smtp_security == "starttls":
                    client.starttls(context=context)
                if settings.smtp_username and settings.smtp_password:
                    client.login(settings.smtp_username, settings.smtp_password.get_secret_value())
                refused = client.send_message(message)
                if refused:
                    raise AppError(503, "Email delivery unavailable")
        except (smtplib.SMTPException, OSError) as exc:
            raise AppError(503, "Email delivery unavailable") from exc


def get_token_sender() -> SMTPTokenSender:
    return SMTPTokenSender()
