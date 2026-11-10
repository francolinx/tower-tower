"""Seed the `talks` index with Monday Nov 9 sessions from Sessionize, fetched at runtime.

    python seed_schedule.py [--date 2026-11-09]

Sessionize times are naive America/Denver; they're converted to UTC (Z) here.
The JSON is never written to disk or committed.
"""

import argparse

import httpx
from elasticsearch.helpers import bulk

from tower.store import TALKS, Store, slugify
from tower.timeutil import mountain_to_utc_iso, utc_now_iso

SESSIONIZE_URL = "https://sessionize.com/api/v2/svi82w6c/view/All"


def talks_from_sessionize(data: dict, date: str) -> list[dict]:
    rooms = {r["id"]: r["name"] for r in data.get("rooms", [])}
    speakers = {s["id"]: s.get("fullName", "") for s in data.get("speakers", [])}
    items = {}
    for group in data.get("categories", []):
        if group.get("title") == "All Sessions":
            items = {i["id"]: i["name"] for i in group.get("items", [])}
    now = utc_now_iso()
    out = []
    for s in data.get("sessions", []):
        if not s.get("startsAt") or (date != "all" and not s["startsAt"].startswith(date)):
            continue
        room_name = rooms.get(s.get("roomId"), "TBD")
        track = next((items[c] for c in s.get("categoryItems", []) if c in items), None)
        out.append({
            "talk_id": f"s{s['id']}",
            "title": s["title"],
            "room": slugify(room_name),
            "room_name": room_name,
            "starts_at": mountain_to_utc_iso(s["startsAt"]),
            "ends_at": mountain_to_utc_iso(s["endsAt"]),
            "speakers": [speakers[x] for x in s.get("speakers", []) if x in speakers],
            "track": track,
            "@timestamp": now,
        })
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--date", default="2026-11-09", help='YYYY-MM-DD or "all"')
    p.add_argument("--sessionize", help="local Sessionize JSON (default: fetch)")
    a = p.parse_args()
    if a.sessionize:
        import json
        with open(a.sessionize, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = httpx.get(SESSIONIZE_URL, timeout=30).raise_for_status().json()
    talks = talks_from_sessionize(data, a.date)
    store = Store()
    store.ensure_indices()
    actions = ({"_index": TALKS, "_id": t["talk_id"], "_source": t} for t in talks)
    ok, _ = bulk(store.es, actions, refresh=True)
    rooms = sorted({t["room"] for t in talks})
    print(f"indexed {ok} talks for {a.date} across {len(rooms)} rooms")


if __name__ == "__main__":
    main()
