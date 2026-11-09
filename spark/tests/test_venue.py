from collections import deque

import pytest

from tower.venue import SHAFT_KINDS, Venue

SCHEDULE_SLUGS = [
    "salt-palace-level-1-151",
    "salt-palace-level-1-grand-ballroom-h",
    "salt-palace-level-1-grand-ballroom-ace",
    "salt-palace-level-1-grand-ballroom-bdf",
    "salt-palace-level-1-grand-ballroom-j",
    "salt-palace-200-south-entrance-south",
    "salt-palace-level-2-250-a-c",
    "salt-palace-level-2-254",
    "salt-palace-level-2-255-a",
    "salt-palace-level-2-255-bc",
    "salt-palace-level-2-255-ef",
    "salt-palace-level-2-east-registration",
    "hyatt-regency-level-4-regency-ballroom-b-d",
    "hyatt-regency-level-5-capitol-reef",
]


@pytest.fixture(scope="module")
def venue():
    return Venue.load()


def _reachable(venue, src, step_free):
    seen, todo = {src}, deque([src])
    while todo:
        u = todo.popleft()
        for v, _, sf in venue.adj[u]:
            if step_free and (not sf or not venue.nodes[v]["step_free_access"]):
                continue
            if v not in seen:
                seen.add(v)
                todo.append(v)
    return seen


def test_step_free_route_uses_elevator(venue):
    r = venue.route("150-d-f", "255-ef", step_free=True)
    assert r["total_seconds"] > 0
    assert r["to"] == "salt-palace-level-2-255-ef"
    assert any("elevator" in s["text"] for s in r["steps"])
    kinds = {venue.nodes[n]["kind"] for n in r["path"]}
    assert "escalator" not in kinds and "stairs" not in kinds
    assert sum(s["seconds"] for s in r["steps"]) == r["total_seconds"]


def test_default_route_prefers_255_core_escalator(venue):
    r = venue.route("150-d-f", "255-ef")
    assert r["total_seconds"] > 0
    assert "escalator-255-l1" in r["path"]
    assert r["total_seconds"] <= venue.route("150-d-f", "255-ef", step_free=True)["total_seconds"]


def test_vertical_moves_collapse(venue):
    r = venue.route("150-d-f", "355-d", step_free=True)
    texts = [s["text"] for s in r["steps"]]
    assert any("from Level 1 to Level 3" in t for t in texts)


def test_nearest_quiet_room(venue):
    res = venue.nearest("quiet", "upper-concourse")
    assert res["node"] == "260-a"
    assert res["route"]["to"] == "260-a"


def test_graph_connected_and_edges_valid(venue):
    for e in venue.edges:
        assert e["a"] in venue.nodes and e["b"] in venue.nodes
        assert e["seconds"] > 0
    assert _reachable(venue, "north-foyer", step_free=False) == set(venue.nodes)


def test_everything_reachable_step_free(venue):
    reach = _reachable(venue, "north-foyer", step_free=True)
    missing = [nid for nid, n in venue.nodes.items() if n["kind"] not in SHAFT_KINDS and nid not in reach]
    assert missing == []


def test_schedule_slugs_and_aliases(venue):
    for slug in SCHEDULE_SLUGS:
        assert slug in venue.nodes
    assert venue.resolve("255-ef") == "salt-palace-level-2-255-ef"
    assert venue.resolve("255 EF") == "salt-palace-level-2-255-ef"
    assert venue.resolve("Grand-Ballroom-H") == "salt-palace-level-1-grand-ballroom-h"
    assert venue.resolve("capitol-reef") == "hyatt-regency-level-5-capitol-reef"
    assert venue.resolve("quiet-260a") == "260-a"
    with pytest.raises(KeyError):
        venue.resolve("no-such-room")


def test_aliases_are_unambiguous(venue):
    owner = {}
    for nid, n in venue.nodes.items():
        for k in [nid, *n["aliases"]]:
            assert owner.setdefault(k.lower(), nid) == nid, k


def test_parents_exist(venue):
    for n in venue.nodes.values():
        if "parent" in n:
            assert n["parent"] in venue.nodes


def test_booth_to_hyatt_via_badge_pickup(venue):
    r = venue.route("booth-dash0", "hyatt-regency-level-5-capitol-reef", step_free=True)
    assert "badge-pickup" in r["path"]
    assert r["steps"][-1]["node"] == "hyatt-regency-level-5-capitol-reef"
    assert r["steps"][-1]["level"] == 5


def test_no_step_free_route_from_escalator(venue):
    with pytest.raises(ValueError):
        venue.route("escalator-north-l1", "north-foyer", step_free=True)


def test_exports(venue):
    docs = venue.geo_docs()
    assert len(docs) == len(venue.nodes)
    assert all(-90 <= d["location"]["lat"] <= 90 and -180 <= d["location"]["lon"] <= 180 for d in docs)
    pub = venue.public_nodes()
    keys = [(p["building"], p["level"], p["name"].lower()) for p in pub]
    assert keys == sorted(keys)
