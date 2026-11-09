import json

import pytest

from seed_schedule import talks_from_sessionize
from tower.store import MAPPINGS_DIR, make_moment, rrf_query, slugify


def test_make_moment_requires_fields_and_utc():
    doc = make_moment(talk_id="t1", room="main", t_start=1.234, t_end=2.5,
                      timestamp="2026-11-09T21:00:00.000Z", text="hi", embedding=[0.0] * 384)
    for f in ("talk_id", "room", "t_start", "t_end", "@timestamp"):
        assert f in doc
    with pytest.raises(ValueError):
        make_moment(talk_id="", room="main", t_start=0, t_end=1,
                    timestamp="2026-11-09T21:00:00.000Z", text="x", embedding=[])
    with pytest.raises(ValueError):
        make_moment(talk_id="t", room="main", t_start=0, t_end=1,
                    timestamp="2026-11-09T14:00:00-07:00", text="x", embedding=[])


def test_mappings_are_strict_and_384d():
    m = json.loads((MAPPINGS_DIR / "moments.json").read_text())["mappings"]
    assert m["dynamic"] == "strict"
    assert m["properties"]["embedding"]["dims"] == 384
    for f in ("talk_id", "room", "t_start", "t_end", "@timestamp"):
        assert f in m["properties"]


def test_rrf_query_has_bm25_and_knn():
    q = rrf_query("ebpf security", [0.1] * 384)
    kinds = [list(r)[0] for r in q["retriever"]["rrf"]["retrievers"]]
    assert kinds == ["standard", "knn"]


def test_slugify():
    assert slugify("Ballroom A / B") == "ballroom-a-b"


def test_talks_from_sessionize_converts_to_utc():
    data = {
        "rooms": [{"id": 1, "name": "Room 101"}],
        "speakers": [{"id": "a", "fullName": "Jane Doe"}],
        "categories": [{"title": "All Sessions", "items": [{"id": 9, "name": "Observability"}]}],
        "sessions": [
            {"id": "42", "title": "eBPF", "startsAt": "2026-11-09T14:00:00", "endsAt": "2026-11-09T14:30:00",
             "roomId": 1, "speakers": ["a"], "categoryItems": [9]},
            {"id": "43", "title": "Tue", "startsAt": "2026-11-10T09:00:00", "endsAt": "2026-11-10T09:30:00",
             "roomId": 1, "speakers": [], "categoryItems": []},
        ],
    }
    talks = talks_from_sessionize(data, "2026-11-09")
    assert len(talks) == 1
    t = talks[0]
    assert t["talk_id"] == "s42" and t["room"] == "room-101" and t["track"] == "Observability"
    assert t["starts_at"] == "2026-11-09T21:00:00.000Z"
    assert t["speakers"] == ["Jane Doe"]
