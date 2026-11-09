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
    sizes = [{"file_id": "a", "width": 90, "height": 90, "file_size": 1000},
             {"file_id": "b", "width": 1280, "height": 960, "file_size": 200_000},
             {"file_id": "c", "width": 4000, "height": 3000, "file_size": 3_000_000}]
    assert m.best_photo(sizes)["file_id"] == "b"


def test_telegram_request_error_does_not_print_token(capsys):
    import importlib.util

    import httpx

    spec = importlib.util.spec_from_file_location("pull", "tools/pull_telegram_photos.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    token = "test-secret-token"
    url = f"https://api.telegram.org/bot{token}/getUpdates"

    class Client:
        def get(self, request_url, **kwargs):
            request = httpx.Request("GET", request_url)
            return httpx.Response(500, request=request)

    assert m.telegram_get(Client(), url) is None
    output = capsys.readouterr()
    assert token not in output.out + output.err
    assert "HTTP 500" in output.err


def test_photo_puller_does_not_print_caption(capsys, monkeypatch, tmp_path):
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("pull", "tools/pull_telegram_photos.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    caption = "Private caption text"
    monkeypatch.setenv("TG_TOKEN", "test-secret-token")
    monkeypatch.setattr(sys, "argv", ["pull_telegram_photos.py", "--out", str(tmp_path)])
    monkeypatch.setattr(m, "known_chats", lambda: {123})

    class Response:
        status_code = 200

        def __init__(self, payload=None, content=b""):
            self.payload = payload
            self.content = content

        def json(self):
            return self.payload

        def raise_for_status(self):
            pass

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, **kwargs):
            if url.endswith("/getUpdates"):
                return Response({"result": [{
                    "update_id": 1,
                    "message": {
                        "chat": {"id": 123},
                        "photo": [{"file_id": "photo-id", "file_size": 100, "width": 10, "height": 10}],
                        "caption": caption,
                        "message_id": 7,
                    },
                }]})
            if url.endswith("/getFile"):
                return Response({"result": {"file_path": "photos/photo.jpg"}})
            return Response(content=b"photo bytes")

    monkeypatch.setattr(m.httpx, "Client", Client)
    assert m.main() == 0

    output = capsys.readouterr()
    assert caption not in output.out + output.err
    assert "saved photo" in output.out
    assert (tmp_path / "photo-7.jpg").read_bytes() == b"photo bytes"


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


def test_theshop_graph_file():
    """The demo venue file: top-level aliases + sign_hints shape, normalised by the loader."""
    v = Venues().get("theshop")
    assert match_banner("DASH0", v)[0] == "shop-l3-dash0-table"
    assert match_banner("Gitar", v)[0] == "shop-l3-sonar-table"
    assert match_banner("Help Yourself", v)[0] == "shop-l3-fridge"  # from the file's sign_hints
    assert match_banner("🚻", v, frm="shop-l3-stage")[0] == "shop-l3-restroom"
    assert match_banner("Floor 4", v)[0] == "shop-l4-elevator"
    assert match_banner("Roof elevator", v)[0] == "shop-roof-elevator"
    r = v.route("entrance", "dash0", step_free=True)
    assert all(v.nodes[n]["kind"] != "stairs" for n in r["path"])
    assert {n["level"] for n in v.graph()["nodes"]} == {"P", "L2", "L3", "L4", "ROOF"}
