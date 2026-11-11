import json
from io import BytesIO
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import ApiException
from app.schemas.workflow import WorkTaskCreate
from app.services.ticket_translation import translate


def test_language_guard_allows_english_and_rejects_vietnamese_and_blank():
    for message in ["", "   ", "12345", "Không thể gửi thư từ chối", "Không thể gửi thư"]:
        with pytest.raises(ValidationError):
            WorkTaskCreate(
                message=message,
                issue_type="contract",
                client_request_id="00000000-0000-4000-8000-000000000000",
            )
    assert (
        WorkTaskCreate(
            message="Please check this contract.",
            issue_type="contract",
            client_request_id="00000000-0000-4000-8000-000000000000",
        ).message
        == "Please check this contract."
    )


async def test_translation_uses_official_api_and_returns_reviewable_text():
    payload = json.dumps(
        {
            "data": {
                "translations": [
                    {"translatedText": "Cannot send the rejection letter &amp; invoice."}
                ]
            }
        }
    ).encode()
    with patch("urllib.request.urlopen", return_value=BytesIO(payload)) as request:
        result = await translate(
            "Không thể gửi thư", Settings(google_translate_api_key="test-only")
        )
    assert result == "Cannot send the rejection letter & invoice."
    sent = request.call_args.args[0]
    assert sent.full_url == "https://translation.googleapis.com/language/translate/v2"
    assert json.loads(sent.data)["target"] == "en"
    assert request.call_args.kwargs["timeout"] == 8


async def test_translation_is_optional_and_handles_provider_failure():
    with pytest.raises(ApiException):
        await translate("Nội dung", Settings())
    with (
        patch("urllib.request.urlopen", side_effect=OSError("offline")),
        pytest.raises(ApiException),
    ):
        await translate("Nội dung", Settings(google_translate_api_key="test-only"))
