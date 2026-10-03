"""UTC millisecond serialization. Event update policy belongs to each capability."""

from datetime import datetime, timezone


def utc_milliseconds(value: datetime | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("An aware datetime is required")
    result = value.astimezone(timezone.utc)
    return result.isoformat(timespec="milliseconds").replace("+00:00", "Z")
