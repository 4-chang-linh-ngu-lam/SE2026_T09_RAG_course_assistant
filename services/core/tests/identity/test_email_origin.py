import pytest
from pydantic import ValidationError

from app.common.config import Settings


@pytest.mark.parametrize(
    "origin",
    [
        "javascript:alert(1)",
        "https://",
        "//example.com",
        "https://user:pass@example.com",
        "https://example.com/path",
        "https://example.com?",
        "https://example.com#",
        "https://example.com/#token=private",
        "https://example.com:0",
        "https://example.com:70000",
        "https://exa\nmple.com",
        "https://example.com\\evil",
        "https://%65xample.com",
    ],
)
def test_email_web_origin_rejects_unsafe_destinations(origin):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, web_origin=origin)


def test_email_web_origin_preserves_configured_port_and_normalizes_root():
    assert Settings(_env_file=None, web_origin="http://localhost:3100/").web_origin == (
        "http://localhost:3100"
    )
