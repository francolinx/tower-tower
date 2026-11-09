"""Interests (percolator) + Telegram alerts.

- A person messages the bot /start and gets an opaque code (chat_ref). The chat_ref -> chat_id map
  lives only in a local 0600 file on the Spark, never in Elasticsearch, logs or telemetry.
- POST /api/interests stores a percolator query under that chat_ref.
- Each new moment is percolated; a match sends topic + room + moment link, at most one alert per
  interest per 10 minutes.

Privacy: logs carry counts and interest *ids* only, never query text, caption text or chat IDs.
"""

import json
import logging
import os
import secrets
import time
from pathlib import Path

import httpx

from tower.store import INTERESTS
from tower.timeutil import utc_now_iso

log = logging.getLogger("tower-core.alerts")

COOLDOWN_S = 600
PUBLIC_APP_URL = os.environ.get("PUBLIC_APP_URL", "https://tower.cnh.radarhq.io")
CHATS_FILE = Path(os.environ.get("TOWER_CHATS_FILE", Path.home() / ".tower" / "chats.json"))


def interest_query(q: str) -> dict:
    words = q.split()
    match: dict = {"query": q}
    if len(words) <= 3:
        match["operator"] = "and"
    else:
        match["minimum_should_match"] = "70%"
    return {"bool": {"must": [{"match": {"text": match}}]}}


def alert_text(label: str, room_name: str, link: str) -> str:
    return f"🔔 “{label}” just came up in {room_name}\n{link}"


def moment_link(room: str, talk_id: str, t_start: float) -> str:
    return f"{PUBLIC_APP_URL}/?room={room}#moment={talk_id}@{t_start:.1f}"


class Cooldown:
    def __init__(self, seconds: float = COOLDOWN_S, clock=time.monotonic):
        self.seconds, self.clock, self.last = seconds, clock, {}

    def allow(self, key: str) -> bool:
        now = self.clock()
        if now - self.last.get(key, -1e18) < self.seconds:
            return False
        self.last[key] = now
        return True


class ChatRefs:
    """Opaque code <-> Telegram chat id, persisted locally with 0600 permissions."""

    def __init__(self, path: Path = CHATS_FILE):
        self.path = path
        self.by_ref: dict[str, int] = {}
        if path.exists():
            self.by_ref = json.loads(path.read_text())

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.by_ref))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def ref_for(self, chat_id: int) -> str:
        for ref, cid in self.by_ref.items():
            if cid == chat_id:
                return ref
        ref = secrets.token_hex(3)  # 6 hex chars, easy to type
        self.by_ref[ref] = chat_id
        self._save()
        return ref

    def chat_id(self, ref: str) -> int | None:
        return self.by_ref.get(ref.strip().lower())


class Telegram:
    def __init__(self, token: str | None):
        self.token = token or ""
        self.enabled = bool(self.token)
        self.client = httpx.AsyncClient(timeout=35.0)
        self.offset = 0

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    async def send(self, chat_id: int, text: str) -> bool:
        if not self.enabled:
            log.info("telegram disabled; alert dropped (dry run)")
            return False
        try:
            r = await self.client.post(self._url("sendMessage"), json={"chat_id": chat_id, "text": text})
            return r.status_code == 200
        except httpx.HTTPError as e:
            log.warning("telegram send failed type=%s", type(e).__name__)
            return False

    async def poll(self, on_start) -> None:
        """Long-poll getUpdates; answer /start with the person's code."""
        if not self.enabled:
            return
        import asyncio

        while True:
            try:
                r = await self.client.get(
                    self._url("getUpdates"), params={"timeout": 30, "offset": self.offset}
                )
                for u in r.json().get("result", []):
                    self.offset = u["update_id"] + 1
                    msg = u.get("message") or {}
                    if (msg.get("text") or "").startswith("/start") and "chat" in msg:
                        await on_start(msg["chat"]["id"])
            except Exception as e:
                log.warning("telegram poll error type=%s", type(e).__name__)
                await asyncio.sleep(5)


class Alerter:
    def __init__(self, store, telegram: Telegram, refs: ChatRefs):
        self.store, self.tg, self.refs = store, telegram, refs
        self.cooldown = Cooldown()

    async def on_start(self, chat_id: int) -> None:
        ref = self.refs.ref_for(chat_id)
        await self.tg.send(
            chat_id,
            f"Your TOWER code is {ref}\nPaste it into “Alert me about…” on {PUBLIC_APP_URL}",
        )
        log.info("telegram /start handled")

    def add_interest(self, chat_ref: str, query: str) -> str | None:
        if self.refs.chat_id(chat_ref) is None:
            return None
        doc = {
            "query": interest_query(query),
            "chat_ref": chat_ref.strip().lower(),
            "label": query,
            "@timestamp": utc_now_iso(),
        }
        r = self.store.es.index(index=INTERESTS, document=doc, refresh="wait_for")
        return r["_id"]

    def percolate(self, moment: dict) -> list[dict]:
        r = self.store.es.search(
            index=INTERESTS,
            query={"percolate": {"field": "query", "document": {
                "text": moment["text"], "room": moment["room"], "talk_id": moment["talk_id"],
            }}},
            source=["label", "chat_ref"],
            size=50,
        )
        return [{"id": h["_id"], **h["_source"]} for h in r["hits"]["hits"]]

    async def check(self, moment: dict, room_name: str) -> int:
        import asyncio

        hits = await asyncio.to_thread(self.percolate, moment)
        sent = 0
        for h in hits:
            if not self.cooldown.allow(h["id"]):
                continue
            chat_id = self.refs.chat_id(h["chat_ref"])
            if chat_id is None:
                continue
            link = moment_link(moment["room"], moment["talk_id"], moment["t_start"])
            if await self.tg.send(chat_id, alert_text(h["label"], room_name, link)):
                sent += 1
        if hits:
            log.info("percolate room=%s matches=%d alerts_sent=%d", moment["room"], len(hits), sent)
        return sent
