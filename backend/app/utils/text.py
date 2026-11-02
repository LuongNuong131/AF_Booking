import unicodedata


def clean_note(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = "".join(
        c for c in value if c in "\n\t" or unicodedata.category(c) not in {"Cc", "Cf"}
    )
    return cleaned if cleaned.strip() else None
