import json

import pytest

from tower.locate import floor_level, match_banner, parse_reading
from tower.venue import Venue, Venues, norm_level


def node(nid, level, kind="room", poi=None, x=0, y=0):
    return {"id": nid, "name": nid.replace("-", " ").title(), "building": "shop", "level": level,
            "kind": kind, "x": x, "y": y, "step_free_access": True, "aliases": [], "poi": poi}


SHOP = {
    "nodes": [
        node("lobby-l2", "L2"), node("elevator-l2", "L2", "elevator"), node("elevator-l3", "L3", "elevator"),
        node("elevator-roof", "roof", "elevator"), node("dash0-table", "L3"), node("radar-table", "L3"),
        node("sonar-table", "L3"), node("elastic-table", "L4"),
        node("restroom-l3-east", "L3", "poi", "restroom", x=90),
        node("restroom-l3-west", "L3", "poi", "restroom"),
        node("restroom-l2", "L2", "poi", "restroom"),
    ],
    "edges": [
        {"a": "lobby-l2", "b": "elevator-l2", "seconds": 10, "step_free": True},
        {"a": "elevator-l2", "b": "elevator-l3", "seconds": 20, "step_free": True},
        {"a": "elevator-l3", "b": "elevator-roof", "seconds": 30, "step_free": True},
        {"a": "elevator-l3", "b": "dash0-table", "seconds": 15, "step_free": True},
        {"a": "dash0-table", "b": "radar-table", "seconds": 10, "step_free": True},
        {"a": "radar-table", "b": "sonar-table", "seconds": 10, "step_free": True},
        {"a": "elevator-l3", "b": "restroom-l3-west", "seconds": 20, "step_free": True},
        {"a": "sonar-table", "b": "restroom-l3-east", "seconds": 5, "step_free": True},
        {"a": "lobby-l2", "b": "restroom-l2", "seconds": 5, "step_free": True},
        {"a": "elevator-l3", "b": "elastic-table", "seconds": 40, "step_free": True},
    ],
}
V = Venue(SHOP["nodes"], SHOP["edges"])


def test_norm_level():
    assert norm_level("L3") == norm_level(3) == "3" and norm_level("Roof") == "roof"


@pytest.mark.parametrize("text,want", [
    ("Welcome to the Dash0 booth", "dash0-table"),
    ("RADAR by Skyhook", "radar-table"),
    ("Gitar code review", "sonar-table"),
    ("Sonar", "sonar-table"),
    ("Elasticsearch", "elastic-table"),
    ("Radar ♥ Dash0", "radar-table"),  # earliest mention wins
])
def test_banners(text, want):
    assert match_banner(text, V)[0] == want and match_banner(text, V)[2] == "banner"


def test_restroom_nearest_on_current_level():
    assert match_banner("🚻", V, frm="sonar-table")[0] == "restroom-l3-east"
    assert match_banner("Restrooms →", V, frm="elevator-l3")[0] == "restroom-l3-west"
    assert match_banner("Restroom", V, frm="lobby-l2")[0] == "restroom-l2"
    assert match_banner("Restroom", V)[0] is None  # no current level -> don't guess


def test_floor_numbers_to_elevator():
    assert floor_level("Floor 3") == "3" and floor_level("3rd floor") == "3"
    assert floor_level("Elevator 3") == "3" and floor_level("ROOF elevator") == "roof"
    assert floor_level("Room 255") is None
    assert match_banner("FLOOR 3", V) == ("elevator-l3", 0.9, "floor")
    assert match_banner("Roof — elevator", V)[0] == "elevator-roof"


def test_parse_reading():
    assert parse_reading('{"sign": null, "text": "Dash0"}') == (None, "Dash0")
    assert parse_reading("```json\n{\"sign\": \"255 EF\", \"text\": null}\n```") == ("255 EF", None)
    assert parse_reading("nope") == (None, None)


def test_venues_registry_and_graph_shape(tmp_path):
    (tmp_path / "theshop.json").write_text(json.dumps(SHOP))
    (tmp_path / "other.json").write_text(json.dumps(SHOP))
    vs = Venues(tmp_path, default="theshop")
    assert vs.names() == ["other", "theshop"] and vs.default == "theshop"
    g = vs.get().graph()
    assert set(g) == {"nodes", "edges"} and {"id", "x", "y", "level"} <= set(g["nodes"][0])
    with pytest.raises(KeyError):
        vs.get("../etc/passwd")
    assert Venues(tmp_path, default="missing").default == "saltpalace"


def test_photo_puller_helpers():
    import importlib.util
    spec = importlib.util.spec_from_file_location("pull", "tools/pull_telegram_photos.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.slug("Dash0 table, L3!", "x") == "dash0-table-l3" and m.slug(None, "photo-7") == "photo-7"
    sizes = [{"file_id": "a", "width": 90, "height": 90, "file_size": 1000},
             {"file_id": "b", "width": 1280, "height": 960, "file_size": 200_000},
             {"file_id": "c", "width": 4000, "height": 3000, "file_size": 3_000_000}]
    assert m.best_photo(sizes)["file_id"] == "b"


def test_nearest_saltpalace_route_uses_graph_not_query_string(monkeypatch):
    """Regression (Gitar #12): the ?venue= param shadowed the Venue object and crashed /nearest."""
    from fastapi.testclient import TestClient

    import tower.app as app_module

    class NoGeo:
        def venue_candidates(self, *a):
            return []

    monkeypatch.setattr(app_module, "store", NoGeo())
    client = TestClient(app_module.app)
    params = {"kind": "quiet", "from": "north-foyer", "venue": "saltpalace"}
    r = client.get("/api/venue/nearest", params=params)
    assert r.status_code == 200 and r.json()["node"]
    assert client.get("/api/venue/graph", params={"venue": "nope"}).status_code == 404
