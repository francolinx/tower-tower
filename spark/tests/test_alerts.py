import asyncio

import pytest

from tower import alerts
from tower.alerts import Alerter, ChatRefs, Cooldown, Telegram, alert_text, interest_query, moment_link


def test_cooldown_one_alert_per_10_minutes():
    t = [0.0]
    c = Cooldown(600, clock=lambda: t[0])
    assert c.ready("i1")
    c.mark("i1")
    t[0] = 599
    assert not c.ready("i1")
    assert c.ready("i2")
    c.mark("i2")
    t[0] = 601
    assert c.ready("i1")


def test_alert_text_has_topic_room_link_only():
    link = moment_link("room-101", "s42", 12.34)
    msg = alert_text("eBPF security", "Room 101", link)
    assert "eBPF security" in msg and "Room 101" in msg and link in msg
    assert link.endswith("#moment=s42@12.3")


def test_interest_query_short_is_and():
    assert interest_query("ebpf security")["bool"]["must"][0]["match"]["text"]["operator"] == "and"
    long_q = interest_query("how to cut kubernetes alert noise")["bool"]["must"][0]["match"]["text"]
    assert long_q["minimum_should_match"] == "70%"


def test_chat_refs_persist_0600(tmp_path):
    p = tmp_path / "chats.json"
    refs = ChatRefs(p)
    r = refs.ref_for(12345)
    assert refs.ref_for(12345) == r
    assert ChatRefs(p).chat_id(r.upper()) == 12345
    assert oct(p.stat().st_mode & 0o777) == "0o600"


def test_chat_ref_collision_retries(monkeypatch, tmp_path):
    refs = ChatRefs(tmp_path / "chats.json")
    refs.by_ref["abcdef"] = 999
    generated = iter(["abcdef", "123456"])
    monkeypatch.setattr(alerts.secrets, "token_hex", lambda _: next(generated))

    assert refs.ref_for(12345) == "123456"
    assert refs.chat_id("abcdef") == 999
    assert refs.chat_id("123456") == 12345


def test_failed_alert_does_not_start_cooldown(tmp_path):
    class FakeTelegram:
        def __init__(self):
            self.outcomes = [False, True]
            self.calls = 0

        async def send(self, chat_id, text):
            self.calls += 1
            return self.outcomes.pop(0)

    refs = ChatRefs(tmp_path / "chats.json")
    refs.by_ref["abcdef"] = 12345
    telegram = FakeTelegram()
    alerter = Alerter(None, telegram, refs)
    hit = {"id": "interest1", "chat_ref": "abcdef", "label": "topic"}
    alerter.percolate = lambda moment: [hit]
    moment = {"room": "room-1", "talk_id": "talk-1", "t_start": 1.0}

    assert asyncio.run(alerter.check(moment, "Room 1")) == 0
    assert alerter.cooldown.ready("interest1")
    assert asyncio.run(alerter.check(moment, "Room 1")) == 1
    assert not alerter.cooldown.ready("interest1")
    assert asyncio.run(alerter.check(moment, "Room 1")) == 0
    assert telegram.calls == 2


def test_poll_waits_on_non_ok_response(monkeypatch):
    class PollFinished(BaseException):
        pass

    class Response:
        status_code = 429

        @staticmethod
        def json():
            return {"ok": False, "parameters": {"retry_after": 7}}

    class FakeClient:
        async def get(self, *args, **kwargs):
            return Response()

    sleeps = []

    async def stop_after_sleep(seconds):
        sleeps.append(seconds)
        raise PollFinished

    monkeypatch.setattr(asyncio, "sleep", stop_after_sleep)
    telegram = Telegram("token")
    telegram.client = FakeClient()

    with pytest.raises(PollFinished):
        asyncio.run(telegram.poll(lambda chat_id: None))
    assert sleeps == [7]
