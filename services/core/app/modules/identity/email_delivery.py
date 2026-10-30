import smtplib
import ssl
from datetime import UTC
from email.message import EmailMessage
from html import escape
from urllib.parse import quote
from zoneinfo import ZoneInfo

from app.common.config import settings
from app.common.errors import AppError
from app.modules.identity.models import TokenPurpose
from app.modules.identity.service import TokenDelivery


class SMTPTokenSender:
    def _ensure_configuration(self) -> None:
        if not settings.smtp_host or not settings.smtp_from:
            raise AppError(503, "Chưa thể gửi email lúc này. Vui lòng thử lại sau.")
        if bool(settings.smtp_username) != bool(settings.smtp_password):
            raise AppError(503, "Chưa thể gửi email lúc này. Vui lòng thử lại sau.")
        if not settings.public_web_url:
            raise AppError(
                503,
                "Chưa cấu hình địa chỉ trang Lumi để tạo liên kết an toàn. Vui lòng liên hệ bộ phận vận hành.",
            )

    @staticmethod
    def _expiry_text(delivery: TokenDelivery) -> str:
        expires_at = delivery.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        local = expires_at.astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))
        return local.strftime("%H:%M ngày %d/%m/%Y (giờ Việt Nam)")

    @staticmethod
    def _template(delivery: TokenDelivery) -> tuple[str, str, str, str]:
        if delivery.purpose == TokenPurpose.ADMIN_INVITATION:
            return (
                "Lumi | Mời bạn thiết lập tài khoản",
                "/staff/invitation",
                "Thiết lập tài khoản",
                "Quản trị viên nhà trường đã tạo tài khoản nhân sự cho bạn trên Lumi.",
            )
        if delivery.purpose == TokenPurpose.PASSWORD_RESET:
            return (
                "Lumi | Đặt lại mật khẩu",
                "/reset-password",
                "Đặt lại mật khẩu",
                "Chúng tôi nhận được yêu cầu đặt lại mật khẩu cho tài khoản Lumi của bạn.",
            )
        raise AppError(400, "Email chỉ được gửi cho các luồng tài khoản nhân sự đã được hỗ trợ.")

    def _message(self, delivery: TokenDelivery) -> EmailMessage:
        if not delivery.recipient:
            raise AppError(400, "Tài khoản nhân sự chưa có địa chỉ email hợp lệ.")
        subject, path, action, introduction = self._template(delivery)
        token = delivery.token.get_secret_value()
        link = f"{settings.public_web_url}{path}#token={quote(token, safe='')}"
        expiry = self._expiry_text(delivery)
        if delivery.purpose == TokenPurpose.ADMIN_INVITATION:
            fallback = (
                "Nếu không mở được liên kết, hãy nhập mã xác thực bên dưới tại trang nhận lời mời."
            )
            closing = "Nếu bạn không mong đợi lời mời này, hãy bỏ qua email và liên hệ quản trị viên nhà trường."
        else:
            fallback = "Nếu không mở được liên kết, hãy nhập mã xác thực bên dưới tại trang đặt lại mật khẩu."
            closing = "Nếu bạn không yêu cầu đặt lại mật khẩu, hãy bỏ qua email; mật khẩu hiện tại sẽ không thay đổi."

        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = delivery.recipient
        message["Subject"] = subject
        message.set_content(
            f"Xin chào,\n\n"
            f"{introduction}\n\n"
            f"Để tiếp tục, hãy mở liên kết an toàn sau:\n{link}\n\n"
            f"{fallback}\nMã xác thực dùng một lần: {token}\n\n"
            f"Liên kết chỉ dùng một lần và có hiệu lực đến {expiry}.\n\n"
            f"{closing}\n\n"
            "Trân trọng,\nĐội ngũ Lumi\n"
        )
        message.add_alternative(
            '<!doctype html><html lang="vi"><body>'
            f"<p>Xin chào,</p><p>{escape(introduction)}</p>"
            f'<p><a href="{escape(link, quote=True)}">{escape(action)}</a></p>'
            f"<p>{escape(fallback)}</p>"
            f"<p>Mã xác thực dùng một lần: <strong>{escape(token)}</strong></p>"
            f"<p>Liên kết chỉ dùng một lần và có hiệu lực đến {escape(expiry)}.</p>"
            f"<p>{escape(closing)}</p><p>Trân trọng,<br>Đội ngũ Lumi</p>"
            "</body></html>",
            subtype="html",
        )
        return message

    def send(self, delivery: TokenDelivery) -> None:
        self._ensure_configuration()
        message = self._message(delivery)
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
                    raise AppError(503, "Chưa thể gửi email lúc này. Vui lòng thử lại sau.")
        except (smtplib.SMTPException, OSError) as exc:
            raise AppError(503, "Chưa thể gửi email lúc này. Vui lòng thử lại sau.") from exc


def get_token_sender() -> SMTPTokenSender:
    return SMTPTokenSender()
