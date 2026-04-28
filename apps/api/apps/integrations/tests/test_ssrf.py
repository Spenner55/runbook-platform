import pytest
from django.core.exceptions import ValidationError

from apps.integrations.ssrf import validate_outbound_url


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/webhook",
        "file:///etc/passwd",
        "https://localhost/webhook",
        "https://127.0.0.1/webhook",
        "https://10.0.0.1/webhook",
        "https://172.16.0.1/webhook",
        "https://192.168.1.10/webhook",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/webhook",
        "https://[fe80::1]/webhook",
        "https://ops.local/webhook",
        "https://metadata.google.internal/computeMetadata/v1",
        "https://user:pass@example.com/webhook",
        "https://example.com:5432/webhook",
    ],
)
def test_ssrf_validator_blocks_private_metadata_local_urls(url):
    with pytest.raises(ValidationError):
        validate_outbound_url(url)


def test_safe_https_url_passes():
    assert validate_outbound_url("https://example.com/webhook") == (
        "https://example.com/webhook"
    )
