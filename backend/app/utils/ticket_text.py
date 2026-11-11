"""Shared ticket wording. Language validation is a guard, not a language detector."""

import re
import unicodedata

TITLES = {
    "contract": "AF_Non-standard process_Contract issue",
    "cannot_send_rejection_letters": "AF_System Issues_Cannot send rejection letters",
}
REJECTION_MESSAGE = (
    "Please check these invoice which cannot send the rejection letter on TIM Tool - "
    "we had to send manually the rejection letter via Billing Email section, "
    "and force it from the Parking tab to Rejection tab"
)
VIETNAMESE = re.compile("[ăâđêôơưĂÂĐÊÔƠƯ\u1ea0-\u1ef9]")


def validate_english(value):
    normalized = unicodedata.normalize("NFC", value)
    if VIETNAMESE.search(normalized) or not re.search("[a-zA-Z]{2}", normalized):
        raise ValueError(
            "Write the ticket content in English. Use the optional translation helper."
        )


def ticket_title(issue_type, key):
    return f"{TITLES[issue_type]} - {key}" if issue_type else key
