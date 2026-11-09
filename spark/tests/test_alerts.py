from tower.alerts import ChatRefs, Cooldown, alert_text, interest_query, moment_link


def test_cooldown_one_alert_per_10_minutes():
    t = [0.0]
    c = Cooldown(600, clock=lambda: t[0])
    assert c.allow("i1")
    t[0] = 599
    assert not c.allow("i1")
    assert c.allow("i2")
    t[0] = 601
    assert c.allow("i1")


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
