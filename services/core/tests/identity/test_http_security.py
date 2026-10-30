import smtplib
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import Request, Response
from pydantic import SecretStr

from app.common.config import Settings, settings
from app.common.errors import AppError
from app.modules.identity.email_delivery import SMTPTokenSender
from app.modules.identity.http_security import client_identity, verify_cookie_origin
from app.modules.identity.idempotency import IdempotencyStore
from app.modules.identity.models import TokenPurpose
from app.modules.identity.rate_limit import RateLimiter
from app.modules.identity.service import TokenDelivery


def request(headers):
    return Request(
        {
            "type": "http",
            "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
            "client": ("127.0.0.1", 12345),
        }
    )


@pytest.mark.parametrize(
    "headers,allowed",
    [
        ({"Origin": "https://app.example.com"}, True),
        ({"Referer": "https://app.example.com/settings?tab=profile"}, True),
        ({"Origin": "https://app.example.com:443"}, True),
        ({}, False),
        ({"Origin": "null"}, False),
        ({"Origin": "https://app.example.com.attacker.com"}, False),
        ({"Origin": "https://app.example.com/path"}, False),
        ({"Origin": "https://app.example.com:8443"}, False),
        ({"Origin": "http://app.example.com"}, False),
        ({"Origin": "https://app.example.com:bad"}, False),
        ({"Origin": "https://attacker.com", "Referer": "https://app.example.com"}, False),
        ({"Referer": "https://app.example.com@attacker.com/path"}, False),
    ],
)
def test_origin_validation(monkeypatch, headers, allowed):
    monkeypatch.setattr(settings, "cors_origins", ["https://app.example.com"])
    if allowed:
        verify_cookie_origin(request(headers))
    else:
        with pytest.raises(AppError) as raised:
            verify_cookie_origin(request(headers))
        assert raised.value.status_code == 403


def test_client_ip_does_not_trust_forwarded_headers():
    assert client_identity(request({"X-Forwarded-For": "attacker", "X-Real-IP": "attacker"})) == (
        "127.0.0.1"
    )


def test_login_limiter_counts_failures_by_ip_and_email():
    now = [0.0]
    limiter = RateLimiter(lambda: now[0])
    for _ in range(5):
        with pytest.raises(AppError), limiter.login_attempt("ip1", "student@example.com"):
            raise AppError(401)
    for ip, email in (("ip1", "other@example.com"), ("ip2", "student@example.com")):
        with pytest.raises(AppError) as raised, limiter.login_attempt(ip, email):
            pass
        assert raised.value.status_code == 429
        assert raised.value.headers["Retry-After"] == "60"
    now[0] = 60.0
    with limiter.login_attempt("ip1", "student@example.com"):
        pass


def test_success_and_infrastructure_error_do_not_count_as_bad_login():
    limiter = RateLimiter()
    for _ in range(8):
        with limiter.login_attempt("ip", "email"):
            pass
        with pytest.raises(AppError), limiter.login_attempt("ip", "email"):
            raise AppError(503)


def test_request_limit_expiry_and_capacity(monkeypatch):
    now = [0.0]
    limiter = RateLimiter(lambda: now[0])
    for _ in range(3):
        limiter.consume("register", "ip", 3, 3600)
    with pytest.raises(AppError) as raised:
        limiter.consume("register", "ip", 3, 3600)
    assert raised.value.status_code == 429
    monkeypatch.setattr(settings, "auth_rate_limit_max_keys", 1)
    with pytest.raises(AppError) as raised:
        limiter.consume("register", "another-ip", 3, 3600)
    assert raised.value.status_code == 503
    now[0] = 3600.0
    limiter.consume("register", "another-ip", 3, 3600)


def test_idempotency_replay_conflict_expiry_and_capacity(monkeypatch):
    now = [0.0]
    store = IdempotencyStore(lambda: now[0])
    key = uuid4()
    operation = Mock(return_value=Response(status_code=204, headers={"Set-Cookie": "test-cookie"}))
    payload = {"password": SecretStr("test-only-password")}
    first = store.run("actor", "/operation", key, payload, operation)
    second = store.run("actor", "/operation", key, payload, operation)
    assert first.raw_headers == second.raw_headers
    operation.assert_called_once()
    assert "test-only-password" not in repr(store.entries)
    with pytest.raises(AppError) as raised:
        store.run("actor", "/operation", key, {"password": SecretStr("different")}, operation)
    assert raised.value.status_code == 409
    monkeypatch.setattr(settings, "auth_idempotency_max_keys", 1)
    with pytest.raises(AppError) as raised:
        store.run("another-actor", "/operation", uuid4(), payload, operation)
    assert raised.value.status_code == 503
    now[0] = 24 * 60 * 60
    store.run("actor", "/operation", key, payload, operation)
    assert operation.call_count == 2


@pytest.mark.parametrize("security", ["starttls", "tls"])
def test_smtp_delivery_uses_tls_and_keeps_token_out_of_errors(monkeypatch, security):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from", "sender@example.com")
    monkeypatch.setattr(settings, "public_web_url", "https://lumi.example.com")
    monkeypatch.setattr(settings, "smtp_username", "test-user")
    monkeypatch.setattr(settings, "smtp_password", SecretStr("test-only-smtp-password"))
    monkeypatch.setattr(settings, "smtp_security", security)
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.send_message.return_value = {}
    constructor = Mock(return_value=client)
    monkeypatch.setattr(smtplib, "SMTP" if security == "starttls" else "SMTP_SSL", constructor)
    token = SecretStr("test-only-verification-token")
    delivery = TokenDelivery(
        "lecturer@example.com",
        TokenPurpose.ADMIN_INVITATION,
        token,
        datetime.now(UTC) + timedelta(hours=24),
    )
    sender = SMTPTokenSender()
    sender.send(delivery)
    email = client.send_message.call_args.args[0]
    plain = email.get_body(preferencelist=("plain",)).get_content()
    html = email.get_body(preferencelist=("html",)).get_content()
    assert email["To"] == "lecturer@example.com"
    assert email["Subject"] == "Lumi | Mời bạn thiết lập tài khoản"
    assert token.get_secret_value() in plain
    assert "https://lumi.example.com/staff/invitation#token=" in plain
    assert "Quản trị viên nhà trường đã tạo tài khoản nhân sự" in plain
    assert "Nếu không mở được liên kết" in plain
    assert "Mã xác thực dùng một lần" in plain
    assert 'href="https://lumi.example.com/staff/invitation#token=' in html
    assert "Trân trọng" in plain and "Đội ngũ Lumi" in plain
    if security == "starttls":
        context = client.starttls.call_args.kwargs["context"]
    else:
        context = constructor.call_args.kwargs["context"]
    assert context.check_hostname
    client.login.assert_called_once_with("test-user", "test-only-smtp-password")
    client.send_message.side_effect = smtplib.SMTPException("private provider detail")
    with pytest.raises(AppError) as raised:
        sender.send(delivery)
    assert raised.value.status_code == 503
    assert "private" not in str(raised.value)


def test_staff_password_reset_email_links_to_existing_reset_page(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from", "sender@example.com")
    monkeypatch.setattr(settings, "smtp_username", None)
    monkeypatch.setattr(settings, "smtp_password", None)
    monkeypatch.setattr(settings, "public_web_url", "https://lumi.example.com")
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.send_message.return_value = {}
    monkeypatch.setattr(smtplib, "SMTP", Mock(return_value=client))
    delivery = TokenDelivery(
        "admin@example.com",
        TokenPurpose.PASSWORD_RESET,
        SecretStr("test-only-reset-token"),
        datetime.now(UTC) + timedelta(minutes=60),
    )

    SMTPTokenSender().send(delivery)

    email = client.send_message.call_args.args[0]
    plain = email.get_body(preferencelist=("plain",)).get_content()
    assert email["Subject"] == "Lumi | Đặt lại mật khẩu"
    assert "https://lumi.example.com/reset-password#token=" in plain
    assert "Mã xác thực dùng một lần" in plain
    assert "Trân trọng" in plain and "Đội ngũ Lumi" in plain
    assert "mật khẩu hiện tại sẽ không thay đổi" in plain


@pytest.mark.parametrize(
    "purpose",
    [
        TokenPurpose.EMAIL_VERIFICATION,
        TokenPurpose.STUDENT_ACTIVATION,
        TokenPurpose.STUDENT_PASSWORD_RESET,
    ],
)
def test_student_and_legacy_tokens_are_never_sent_by_smtp(monkeypatch, purpose):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from", "sender@example.com")
    monkeypatch.setattr(settings, "smtp_username", None)
    monkeypatch.setattr(settings, "smtp_password", None)
    monkeypatch.setattr(settings, "public_web_url", "https://lumi.example.com")
    smtp = Mock()
    monkeypatch.setattr(smtplib, "SMTP", smtp)
    delivery = TokenDelivery(
        "student@example.com",
        purpose,
        SecretStr("test-only-student-token"),
        datetime.now(UTC) + timedelta(hours=1),
    )

    with pytest.raises(AppError) as raised:
        SMTPTokenSender().send(delivery)

    assert raised.value.status_code == 400
    smtp.assert_not_called()


def test_unconfigured_email_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", None)
    delivery = TokenDelivery(
        "student@example.com",
        TokenPurpose.PASSWORD_RESET,
        SecretStr("test-only-token"),
        datetime.now(UTC) + timedelta(minutes=5),
    )
    with pytest.raises(AppError) as raised:
        SMTPTokenSender().send(delivery)
    assert raised.value.status_code == 503


def test_blank_smtp_from_is_treated_as_unconfigured():
    assert Settings(smtp_from="", _env_file=None).smtp_from is None
