from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.api.v1.attachments import image_type
from app.core.config import Settings
from app.services.storage import create_storage, signed_request


def config(**values):
    return Settings(
        _env_file=None,
        s3_endpoint="https://example.r2.cloudflarestorage.com",
        s3_bucket="af-booking-notes",
        s3_region="auto",
        s3_access_key_id="TESTACCESS",
        s3_secret_access_key="test-secret-for-reference-only",
        **values,
    )


@pytest.mark.parametrize(
    "method,expected",
    [
        ("PUT", "47ed725c540f9bf19444c9234f5c49e72cd5008e5552d76d48fc81bc6efbda18"),
        ("GET", "adde8234732654c6fecb0be959835897f6e99baf9cfadfad5f0531695181dc8b"),
    ],
)
def test_private_s3_signatures_match_aws_botocore_reference(method, expected):
    # Fixtures independently verified against AWS botocore S3SigV4Auth, with fake
    # credentials and this fixed timestamp. The SDK is not a runtime dependency.
    request = signed_request(
        config(),
        method,
        "notes/42/test.png",
        b"image-test" if method == "PUT" else b"",
        "image/png" if method == "PUT" else None,
        now=datetime(2026, 11, 10, 10, tzinfo=UTC),
    )
    assert request.get_header("Authorization").endswith("Signature=" + expected)
    assert (
        request.full_url
        == "https://example.r2.cloudflarestorage.com/af-booking-notes/notes/42/test.png"
    )
    assert "test-secret-for-reference-only" not in repr(config())


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.com",
        "https://user:secret@example.com",
        "https://example.com/bucket",
        "https://example.com?token=x",
    ],
)
def test_storage_endpoint_requires_an_https_origin(endpoint):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, s3_endpoint=endpoint)


def test_storage_is_disabled_until_all_configuration_is_present():
    assert not create_storage(Settings(_env_file=None)).configured
    assert create_storage(config()).configured
    with pytest.raises(ValueError):
        create_storage(Settings(_env_file=None, s3_bucket="af-booking-notes"))


def test_only_raster_image_signatures_are_accepted():
    assert image_type(b"<svg onload=alert(1)></svg>") is None
    assert image_type(b"<html></html>") is None
    assert image_type(b"GIF89aimage") == "image/gif"
