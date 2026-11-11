"""Optional Google Cloud Translation v2; text is sent only on an explicit request."""

import asyncio
import html
import json
import urllib.error
import urllib.request

from app.core.errors import ApiException
from app.schemas.contracts import ErrorCode
from app.utils.ticket_text import validate_english


def call_provider(text, key):
    request = urllib.request.Request(
        "https://translation.googleapis.com/language/translate/v2",
        data=json.dumps({"q": text, "source": "vi", "target": "en", "format": "text"}).encode(),
        headers={"Content-Type": "application/json", "X-Goog-Api-Key": key},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        value = json.loads(response.read(65536))
    translated = html.unescape(value["data"]["translations"][0]["translatedText"]).strip()
    if not translated or len(translated) > 2000:
        raise ValueError("Invalid translation length")
    validate_english(translated)
    return translated


async def translate(text, settings):
    if not settings.google_translate_api_key:
        raise ApiException(
            ErrorCode.SERVICE_BUSY,
            message="Automatic translation is not configured. Use Open Google Translate instead.",
        )
    try:
        return await asyncio.to_thread(
            call_provider, text, settings.google_translate_api_key.get_secret_value()
        )
    except (OSError, urllib.error.URLError, ValueError, KeyError, IndexError, TypeError):
        raise ApiException(
            ErrorCode.SERVICE_BUSY,
            message="Translation is unavailable. Retry or use Open Google Translate.",
        ) from None
