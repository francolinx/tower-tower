from datetime import datetime, timedelta, timezone

import pytest

from tower.timeutil import mountain_to_utc_iso, to_utc_iso, utc_now_iso


def test_utc_now_has_z_suffix():
    s = utc_now_iso()
    assert s.endswith("Z")
    assert "+00:00" not in s


def test_to_utc_converts_offsets():
    dt = datetime(2026, 11, 9, 14, 0, tzinfo=timezone(timedelta(hours=-7)))
    assert to_utc_iso(dt) == "2026-11-09T21:00:00.000Z"


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        to_utc_iso(datetime(2026, 11, 9, 14, 0))  # noqa: DTZ001 (naive on purpose)


def test_sessionize_mountain_time_november_is_mst():
    # Nov 9 2026 is after the DST change: MST = UTC-7
    assert mountain_to_utc_iso("2026-11-09T09:00:00") == "2026-11-09T16:00:00.000Z"
