"""Elasticsearch access: index setup from spark/es/mappings/*.json, moments, talks, hybrid search.

Mappings live only in the JSON files. Every moment carries talk_id, room, t_start, t_end, @timestamp.
"""

import json
import os
import re
from pathlib import Path

from elasticsearch import ApiError, Elasticsearch, NotFoundError, TransportError

ES_DOWN = (ApiError, TransportError)

MAPPINGS_DIR = Path(__file__).resolve().parent.parent / "es" / "mappings"
MOMENTS = "moments"
TALKS = "talks"
INTERESTS = "interests"
REQUIRED_MOMENT_FIELDS = ("talk_id", "room", "t_start", "t_end", "@timestamp")
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "room"


def make_moment(
    *, talk_id: str, room: str, t_start: float, t_end: float, timestamp: str, text: str,
    embedding: list[float], lang: str = "en",
) -> dict:
    doc = {
        "talk_id": talk_id,
        "room": room,
        "t_start": round(float(t_start), 2),
        "t_end": round(float(t_end), 2),
        "@timestamp": timestamp,
        "lang": lang,
        "text": text,
        "embedding": embedding,
    }
    missing = [f for f in REQUIRED_MOMENT_FIELDS if doc.get(f) in (None, "")]
    if missing:
        raise ValueError(f"moment missing fields: {missing}")
    if not timestamp.endswith("Z"):
        raise ValueError("@timestamp must be UTC with Z suffix")
    return doc


def rrf_query(q: str, q_vec: list[float], size: int = 10) -> dict:
    return {
        "retriever": {
            "rrf": {
                "retrievers": [
                    {"standard": {"query": {"match": {"text": q}}}},
                    {"knn": {"field": "embedding", "query_vector": q_vec, "k": size, "num_candidates": 50}},
                ],
                "rank_window_size": 50,
                "rank_constant": 60,
            }
        },
        "size": size,
        "_source": ["talk_id", "room", "t_start", "t_end", "text", "@timestamp"],
    }


class Store:
    def __init__(self, url: str | None = None, api_key: str | None = None):
        self.es = Elasticsearch(
            url or os.environ.get("ES_URL", "http://localhost:9200"),
            api_key=api_key or os.environ.get("ES_API_KEY"),
            request_timeout=10,
        )

    def ensure_indices(self, names=(MOMENTS, TALKS, INTERESTS)) -> None:
        for name in names:
            path = MAPPINGS_DIR / f"{name}.json"
            if not path.exists() or self.es.indices.exists(index=name):
                continue
            self.es.indices.create(index=name, body=json.loads(path.read_text()))

    # --- moments
    def index_moment(self, doc: dict) -> str:
        r = self.es.index(index=MOMENTS, document=doc)
        return r["_id"]

    def search(self, q: str, q_vec: list[float], size: int = 10) -> list[dict]:
        r = self.es.search(index=MOMENTS, body=rrf_query(q, q_vec, size))
        hits = [h["_source"] | {"id": h["_id"]} for h in r["hits"]["hits"]]
        titles = self.talk_titles({h["talk_id"] for h in hits})
        for h in hits:
            h["talk_title"] = titles.get(h["talk_id"])
        return hits

    def moments_around(self, talk_id: str, t: float, window: float = 30.0) -> list[dict]:
        r = self.es.search(
            index=MOMENTS,
            query={"bool": {"filter": [
                {"term": {"talk_id": talk_id}},
                {"range": {"t_start": {"gte": t - window, "lte": t + window}}},
            ]}},
            sort=[{"t_start": "asc"}],
            size=60,
            source=["talk_id", "room", "t_start", "t_end", "text", "@timestamp"],
        )
        return [h["_source"] for h in r["hits"]["hits"]]

    # --- talks
    def talk_titles(self, ids: set[str]) -> dict[str, str]:
        if not ids:
            return {}
        try:
            r = self.es.mget(index=TALKS, ids=list(ids), source=["title"])
        except NotFoundError:
            return {}
        return {d["_id"]: d["_source"]["title"] for d in r["docs"] if d.get("found")}

    def get_talk(self, talk_id: str) -> dict | None:
        try:
            return self.es.get(index=TALKS, id=talk_id)["_source"]
        except NotFoundError:
            return None

    def current_talk(self, room: str, now_iso: str) -> dict | None:
        try:
            r = self.es.search(
                index=TALKS,
                query={"bool": {"filter": [
                    {"term": {"room": room}},
                    {"range": {"starts_at": {"lte": now_iso}}},
                    {"range": {"ends_at": {"gte": now_iso}}},
                ]}},
                size=1,
            )
        except (NotFoundError, *ES_DOWN):
            return None
        hits = r["hits"]["hits"]
        return hits[0]["_source"] if hits else None

    def live_talks(self, now_iso: str) -> dict[str, dict]:
        try:
            r = self.es.search(
                index=TALKS,
                query={"bool": {"filter": [
                    {"range": {"starts_at": {"lte": now_iso}}},
                    {"range": {"ends_at": {"gte": now_iso}}},
                ]}},
                size=100,
            )
        except (NotFoundError, *ES_DOWN):
            return {}
        return {h["_source"]["room"]: h["_source"] for h in r["hits"]["hits"]}
