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


def test_alert_route_line_step_free(tmp_path):
    from tower.alerts import Alerter
    from tower.venue import Venue

    refs = ChatRefs(tmp_path / "c.json")
    ref = refs.ref_for(7)
    a = Alerter(store=None, telegram=None, refs=refs, venue=Venue.load())
    assert a.set_location(ref, "150-d-f")
    line = a.route_line(ref, "salt-palace-level-2-255-ef")
    assert line.startswith("You're at 150 D-F.") and "step-free" in line
    assert "from=150-d-f&to=salt-palace-level-2-255-ef&step_free=1#route" in line
    assert "escalator" not in line.lower()
    # unknown location -> default north-foyer; unknown room -> no route line
    assert a.route_line("nobody", "salt-palace-level-2-255-ef").startswith("You're at North Foyer")
    assert a.route_line(ref, "main") == ""


def test_chat_ref_no_collision(tmp_path, monkeypatch):
    import tower.alerts as al

    seq = iter(["aaaaaa", "aaaaaa", "bbbbbb"])
    monkeypatch.setattr(al.secrets, "token_hex", lambda n: next(seq))
    refs = ChatRefs(tmp_path / "c.json")
    assert refs.ref_for(1) == "aaaaaa"
    assert refs.ref_for(2) == "bbbbbb"
    assert refs.chat_id("aaaaaa") == 1


def test_cooldown_ready_mark_split():
    t = [0.0]
    c = Cooldown(600, clock=lambda: t[0])
    assert c.ready("i") and c.ready("i")  # checking alone doesn't consume it
    c.mark("i")
    assert not c.ready("i")
