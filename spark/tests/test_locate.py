from fastapi.testclient import TestClient

import tower.app as app_module
from tower.locate import MAX_IMAGE_BYTES, match_sign, parse_sign

NODES = [
    {"id": "salt-palace-level-2-255-ef", "name": "Salt Palace | Level 2 | 255 EF", "aliases": ["255-ef"]},
    {"id": "salt-palace-level-2-255-a", "name": "Salt Palace | Level 2 | 255 A", "aliases": ["255-a"]},
    {"id": "260-a", "name": "260 A (quiet room)", "aliases": []},
    {"id": "hyatt-regency-level-5-capitol-reef", "name": "Capitol Reef", "aliases": ["capitol-reef"]},
]


def test_parse_sign_variants():
    assert parse_sign('{"sign": "255 EF"}') == "255 EF"
    assert parse_sign('```json\n{"sign": "Capitol Reef"}\n```') == "Capitol Reef"
    assert parse_sign('{"sign": null}') is None
    assert parse_sign("no json here") is None


def test_locate_accepts_raw_image_body_and_enforces_size_limit(monkeypatch):
    received = {}

    async def read_sign(client, image, mime):
        received["image"] = image
        received["mime"] = mime
        return None, None

    monkeypatch.setattr(app_module.locate, "read_sign", read_sign)
    client = TestClient(app_module.app)
    response = client.post("/api/locate", content=b"jpeg bytes", headers={"content-type": "image/jpeg"})
    assert response.status_code == 200
    assert received == {"image": b"jpeg bytes", "mime": "image/jpeg"}

    response = client.post(
        "/api/locate",
        content=b"x" * (MAX_IMAGE_BYTES + 1),
        headers={"content-type": "image/jpeg"},
    )
    assert response.status_code == 413


def test_match_sign():
    assert match_sign("255 EF", NODES)[0] == "salt-palace-level-2-255-ef"
    assert match_sign("255EF", NODES)[0] == "salt-palace-level-2-255-ef"
    assert match_sign("CAPITOL REEF", NODES)[0] == "hyatt-regency-level-5-capitol-reef"
    node, conf = match_sign("Zzzz", NODES)
    assert node is None and conf == 0.0


def test_numeric_signs_require_an_exact_room_match():
    assert match_sign("255 A", NODES)[0] == "salt-palace-level-2-255-a"
    for sign in ("255 B", "255", "255 E"):
        assert match_sign(sign, NODES)[0] is None


def test_fuzzy_text_match_requires_a_clear_long_match():
    assert match_sign("Capitol Reefs", NODES)[0] == "hyatt-regency-level-5-capitol-reef"
    ambiguous_nodes = [
        {"id": "reef", "name": "Capitol Reef", "aliases": []},
        {"id": "reefs", "name": "Capitol Reefs", "aliases": []},
    ]
    assert match_sign("Capitol Ree", ambiguous_nodes)[0] is None


def test_saltpalace_nearest_uses_selected_venue_for_graph_fallback(monkeypatch):
    class EmptyStore:
        def venue_candidates(self, *args):
            return []

    monkeypatch.setattr(app_module, "store", EmptyStore())
    client = TestClient(app_module.app)
    response = client.get(
        "/api/venue/nearest",
        params={"kind": "restroom-all-gender", "from": "255-ef", "venue": "saltpalace"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["node"]
    assert result["route"]["from"] == "salt-palace-level-2-255-ef"
    assert result["route"]["to"] == result["node"]
