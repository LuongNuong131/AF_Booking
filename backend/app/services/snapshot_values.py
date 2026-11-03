"""Shared snapshot derivation for moderation and integrity repair. No invoice changes."""


def note_snapshot(identifier, agent_id, status_id, position, created_at, text, is_done):
    present = identifier is not None
    done = bool(is_done) if present else False
    return {
        "last_note_id": identifier,
        "last_agent_id": agent_id if present else None,
        "last_status_id": status_id if present else None,
        "last_position": position if present else None,
        "last_note_preview": text[:255] if present and text else None,
        "is_done": done,
        "done_at": created_at if done else None,
    }


def apply_snapshot(booking, values):
    for name, value in values.items():
        setattr(booking, name, value)
