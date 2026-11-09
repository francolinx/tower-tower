import asyncio
from datetime import UTC, datetime, timedelta

import tower.app as core
from tower.timeutil import to_utc_iso


class FakeStore:
    def __init__(self):
        self.talk = None

    def current_talk(self, room, now_iso):
        return self.talk


def test_stream_rotates_to_next_talk(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(core, "store", fake)
    now = datetime.now(UTC)
    fake.talk = {"talk_id": "s1", "starts_at": to_utc_iso(now - timedelta(minutes=5)),
                 "ends_at": to_utc_iso(now + timedelta(minutes=25)), "room_name": "Room 1"}
    st = core.Stream("room-1")
    assert asyncio.run(st.resolve_talk())
    assert st.talk_id == "s1" and 299 < st.offset < 301
    st.add("first talk words", 0.0, 1.5)
    fake.talk = {"talk_id": "s2", "starts_at": to_utc_iso(now),
                 "ends_at": to_utc_iso(now + timedelta(minutes=30))}
    st.next_check = now  # force the periodic re-check
    rotated = asyncio.run(st.maybe_rotate())
    assert rotated is not None
    (text, _, _), old_id, _ = rotated
    assert text == "first talk words" and old_id == "s1"
    assert st.talk_id == "s2"


def test_resolve_talk_survives_no_schedule(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(core, "store", fake)
    st = core.Stream("room-x")
    assert not asyncio.run(st.resolve_talk())
    assert st.talk_id.startswith("room-x-")
