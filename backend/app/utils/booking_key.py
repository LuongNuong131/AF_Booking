def require_canonical_storage_key(value: str) -> str:
    """Storage invariant; full/partial parsing and lookup belong to the booking service."""
    if (
        not value
        or not value.isascii()
        or value != value.upper()
        or any(c.isspace() for c in value)
    ):
        raise ValueError("Stored booking keys must be uppercase ASCII without whitespace")
    return value
