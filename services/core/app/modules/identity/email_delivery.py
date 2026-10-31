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
                "Lumi | Thư mời thiết lập tài khoản nhân sự",
                "/staff/invitation",
                "Thiết lập tài khoản Lumi",
                "Nhà trường trân trọng mời Quý vị hoàn tất thiết lập tài khoản nhân sự trên "
                "hệ thống Lumi để phục vụ công tác quản lý và giảng dạy theo phân công.",
            )
        if delivery.purpose == TokenPurpose.PASSWORD_RESET:
            return (
                "Lumi | Hướng dẫn đặt lại mật khẩu",
                "/reset-password",
                "Đặt lại mật khẩu",
                "Chúng tôi nhận được yêu cầu đặt lại mật khẩu cho tài khoản Lumi liên kết "
                "với địa chỉ email này. Nếu Quý vị là người gửi yêu cầu, vui lòng tiếp tục.",
            )
        raise AppError(400, "Email chỉ được gửi cho các luồng tài khoản nhân sự đã được hỗ trợ.")

    def _message(self, delivery: TokenDelivery) -> EmailMessage:
        if not delivery.recipient:
            raise AppError(400, "Tài khoản nhân sự chưa có địa chỉ email hợp lệ.")
        subject, path, action, introduction = self._template(delivery)
        token = delivery.token.get_secret_value()
        link = f"{settings.public_web_url}{path}#token={quote(token, safe='')}"
        expiry = self._expiry_text(delivery)
        salutation = "Kính gửi Quý Thầy/Cô và Quý Cán bộ Nhà trường,"
        if delivery.purpose == TokenPurpose.ADMIN_INVITATION:
            fallback = (
                "Nếu nút thiết lập không mở được, Quý vị có thể truy cập trang nhận lời mời "
                "của Lumi và nhập mã xác thực bên dưới."
            )
            closing = (
                "Nếu Quý vị không mong đợi thư mời này, vui lòng bỏ qua thư và liên hệ "
                "quản trị viên nhà trường để được hỗ trợ."
            )
        else:
            fallback = (
                "Nếu nút đặt lại không mở được, Quý vị có thể truy cập trang đặt lại mật khẩu "
                "của Lumi và nhập mã xác thực bên dưới."
            )
            closing = (
                "Nếu Quý vị không yêu cầu thay đổi mật khẩu, vui lòng bỏ qua thư; mật khẩu "
                "hiện tại sẽ không thay đổi."
            )
        security_note = (
            "Liên kết và mã xác thực chỉ sử dụng được một lần, có hiệu lực đến "
            f"{expiry}. Vui lòng không chia sẻ mã này với người khác."
        )
        signature = "Bộ phận vận hành hệ thống Lumi"

        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = delivery.recipient
        message["Subject"] = subject
        message.set_content(
            f"{salutation}\n\n"
            f"{introduction}\n\n"
            f"Để tiếp tục, vui lòng mở liên kết an toàn sau:\n{action}: {link}\n\n"
            f"{fallback}\n\n"
            f"Mã xác thực dùng một lần: {token}\n"
            f"{security_note}\n\n"
            f"{closing}\n\n"
            f"Trân trọng,\n{signature}\n"
        )
        message.add_alternative(
            '<!doctype html><html lang="vi"><body style="margin:0;background:#f4f6fa;'
            'font-family:Arial,Helvetica,sans-serif;color:#1f2937">'
            '<div style="max-width:600px;margin:32px auto;padding:32px;background:#ffffff;'
            'border:1px solid #e5e7eb;border-radius:12px">'
            '<p style="margin:0 0 24px;color:#315eea;font-size:13px;font-weight:700;'
            'letter-spacing:1.4px">LUMI · TRỢ GIẢNG HỌC TẬP</p>'
            f"<p>{escape(salutation)}</p>"
            f"<p style=\"line-height:1.6\">{escape(introduction)}</p>"
            '<p style="margin:28px 0"><a '
            f'href="{escape(link, quote=True)}" '
            'style="display:inline-block;padding:13px 22px;background:#315eea;color:#ffffff;'
            'text-decoration:none;border-radius:8px;font-weight:700">'
            f"{escape(action)}</a></p>"
            f"<p style=\"line-height:1.6\">{escape(fallback)}</p>"
            '<div style="margin:20px 0;padding:16px;background:#f4f6fa;border-radius:8px">'
            f"<p style=\"margin:0 0 8px\">Mã xác thực dùng một lần:</p>"
            f"<p style=\"margin:0;font-size:18px;font-weight:700;letter-spacing:1px\">"
            f"{escape(token)}</p></div>"
            f"<p style=\"line-height:1.6;color:#4b5563\">{escape(security_note)}</p>"
            f"<p style=\"line-height:1.6\">{escape(closing)}</p>"
            '<p style="margin-top:28px">Trân trọng,<br>'
            f"{escape(signature)}</p></div></body></html>",
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
