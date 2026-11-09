"""UTC time helpers. Every timestamp TOWER writes is UTC ISO-8601 with a trailing Z."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

MOUNTAIN = ZoneInfo("America/Denver")


def to_utc_iso(dt: datetime) -> str:
    """Format an aware datetime as UTC ISO-8601 with millisecond precision and a Z suffix."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime; attach a timezone first")
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def utc_now_iso() -> str:
    return to_utc_iso(datetime.now(UTC))


def mountain_to_utc_iso(naive_local: str) -> str:
    """Convert a naive Sessionize time (America/Denver), e.g. '2026-11-09T09:00:00', to UTC Z."""
    dt = datetime.fromisoformat(naive_local)
    if dt.tzinfo is not None:
        return to_utc_iso(dt)
    return to_utc_iso(dt.replace(tzinfo=MOUNTAIN))
