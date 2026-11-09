from tower.locate import match_sign, parse_sign

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


def test_match_sign():
    assert match_sign("255 EF", NODES)[0] == "salt-palace-level-2-255-ef"
    assert match_sign("255EF", NODES)[0] == "salt-palace-level-2-255-ef"
    assert match_sign("CAPITOL REEF", NODES)[0] == "hyatt-regency-level-5-capitol-reef"
    node, conf = match_sign("Zzzz", NODES)
    assert node is None and conf < 0.6
