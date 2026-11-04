"""Deterministic factory rows; never use shared deployment accounts or passwords."""


def user_row(identifier, encoded_password, *, username=None, role="agent", **overrides):
    name = username or f"test-agent-{identifier}"
    return {
        "id": identifier,
        "username": name,
        "full_name": name.title(),
        "role": role,
        "password_hash": encoded_password,
        "is_active": True,
        "must_change_password": False,
        **overrides,
    }
