"""Index published slide decks (one doc per page) into the `slides` index.

    python seed_slides.py ~/cnh-prep/data/slides/slides.json [--sessionize kubecon_sessionize.json]

slides.json comes from the out-of-repo fetcher (pdftotext per page). Deck URLs come from the
Sessionize "slides" answer, fetched at runtime unless a local copy is given. Nothing is committed.
"""

import argparse
import json
import sys

import httpx
from elasticsearch.helpers import bulk

from seed_schedule import SESSIONIZE_URL
from tower import embed
from tower.store import SLIDES, Store, make_slide_page
from tower.timeutil import mountain_to_utc_iso, utc_now_iso

SLIDES_QUESTION_ID = 137003
MIN_PAGE_CHARS = 20


def slide_urls(sessionize: dict) -> dict[str, str]:
    out = {}
    for s in sessionize.get("sessions", []):
        for a in s.get("questionAnswers", []):
            v = a.get("answerValue") or ""
            if a.get("questionId") == SLIDES_QUESTION_ID and v.startswith("https://"):
                out[f"s{s['id']}"] = v
    return out


def slide_docs(records: list[dict], urls: dict[str, str], embed_fn, now: str) -> list[dict]:
    pages = [(r, p) for r in records if r["talk_id"] in urls
             for p in r.get("pages", []) if len(p["text"]) >= MIN_PAGE_CHARS]
    vecs = embed_fn([p["text"] for _, p in pages])
    return [
        make_slide_page(
            talk_id=r["talk_id"], title=r["title"], room_name=r.get("room") or "TBD",
            starts_at=mountain_to_utc_iso(r["starts_at_mt"]), page=p["page"],
            url=urls[r["talk_id"]], text=p["text"], embedding=v, timestamp=now,
        )
        for (r, p), v in zip(pages, vecs, strict=True)
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slides_json")
    ap.add_argument("--sessionize", help="local Sessionize JSON (default: fetch)")
    a = ap.parse_args()
    records = json.load(open(a.slides_json))
    if a.sessionize:
        sessionize = json.load(open(a.sessionize))
    else:
        sessionize = httpx.get(SESSIONIZE_URL, timeout=30).raise_for_status().json()
    docs = slide_docs(records, slide_urls(sessionize), embed.embed_passages, utc_now_iso())
    store = Store()
    store.ensure_indices((SLIDES,))
    actions = ({"_index": SLIDES, "_id": f"{d['talk_id']}-p{d['page']}", "_source": d} for d in docs)
    ok, _ = bulk(store.es, actions, chunk_size=200, request_timeout=120)
    print(f"talks={len({d['talk_id'] for d in docs})} pages={ok}", file=sys.stderr)


if __name__ == "__main__":
    main()
