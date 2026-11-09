import pytest

from seed_slides import slide_docs, slide_urls
from tower.store import make_slide_page


def fake_embed(texts):
    return [[0.0] * 384 for _ in texts]


SESSIONIZE = {"sessions": [
    {"id": "111", "questionAnswers": [{"questionId": 137003, "answerValue": "https://static.sched.com/a.pdf"}]},
    {"id": "222", "questionAnswers": [{"questionId": 137003, "answerValue": "not a url"}]},
]}
RECORDS = [
    {"talk_id": "s111", "title": "eBPF at scale", "room": "Salt Palace | Level 2 | 255 EF",
     "starts_at_mt": "2026-11-09T11:00:00", "pages": [
         {"page": 1, "text": "eBPF security observability at scale with Cilium"},
         {"page": 2, "text": "thanks"}]},
    {"talk_id": "s222", "title": "No deck", "room": "x", "starts_at_mt": "2026-11-09T11:00:00",
     "pages": [{"page": 1, "text": "this talk has no https slide url so it is skipped"}]},
]


def test_slide_urls_https_only():
    assert slide_urls(SESSIONIZE) == {"s111": "https://static.sched.com/a.pdf"}


def test_slide_docs_utc_and_page_link():
    docs = slide_docs(RECORDS, slide_urls(SESSIONIZE), fake_embed, "2026-11-09T22:00:00.000Z")
    assert len(docs) == 1  # short page and url-less talk dropped
    d = docs[0]
    assert d["starts_at"] == "2026-11-09T18:00:00.000Z"  # 11:00 MST -> 18:00Z
    assert d["page"] == 1 and d["room"] == "salt-palace-level-2-255-ef"
    assert len(d["embedding"]) == 384


def test_make_slide_page_rejects_naive_time():
    with pytest.raises(ValueError):
        make_slide_page(talk_id="s1", title="t", room_name="r", starts_at="2026-11-09T11:00:00",
                        page=1, url="https://x/a.pdf", text="x", embedding=[],
                        timestamp="2026-11-09T22:00:00Z")
