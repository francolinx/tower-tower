"""tower-core: live captions over WebSockets. Runs on the Spark at 127.0.0.1:8088 (Funnel in front).

WS  /ws/audio?room=X     binary frames: PCM16 LE mono 16 kHz, any frame size
WS  /ws/captions?room=X  JSON caption events
GET /healthz
GET /api/rooms

Privacy: logs carry room, counts and durations only. Audio is never written to disk.
"""

import asyncio
import json
import logging
import os
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from tower import embed
from tower.chunker import Windower, merge_overlap
from tower.store import Store, make_moment, slugify
from tower.timeutil import to_utc_iso, utc_now_iso

ASR_URL = os.environ.get("ASR_URL", "http://127.0.0.1:8090")
MIN_SEG_S, MAX_SEG_S = 3.0, 7.0  # moment length bounds

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("tower-core")

app = FastAPI(title="tower-core")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://tower.cnh.radarhq.io", "http://localhost:8080"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class Hub:
    """Caption subscribers per room, plus per-room stream state."""

    def __init__(self):
        self.subs: dict[str, set[WebSocket]] = defaultdict(set)
        self.sources: dict[str, int] = defaultdict(int)  # active audio sources per room
        self.last_text: dict[str, str] = {}

    async def broadcast(self, room: str, msg: dict) -> None:
        data = json.dumps(msg)
        dead = []
        for ws in list(self.subs[room]):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.subs[room].discard(ws)


hub = Hub()
asr_client: httpx.AsyncClient | None = None
store: Store | None = None


@app.on_event("startup")
async def _startup() -> None:
    global asr_client, store
    asr_client = httpx.AsyncClient(base_url=ASR_URL, timeout=10.0)
    store = Store()
    await asyncio.to_thread(store.ensure_indices)
    await asyncio.to_thread(embed.model)  # load bge-small on CUDA before the first chunk
    log.info("store + embeddings ready")


class Stream:
    """One audio source session: which talk it belongs to and where t=0 is."""

    def __init__(self, room: str):
        self.room = room
        self.started = datetime.now(UTC)
        self.talk_id = f"{room}-{self.started.strftime('%Y%m%dT%H%M%SZ')}"
        self.offset = 0.0  # seconds from talk start to stream start
        self.seg_text: list[str] = []
        self.seg_start: float | None = None
        self.seg_end = 0.0

    def add(self, text: str, t_start: float, t_end: float) -> tuple[str, float, float] | None:
        """Group captions into ~6 s moments; return a finished segment when one closes."""
        if self.seg_start is None:
            self.seg_start = t_start
        self.seg_text.append(text)
        self.seg_end = t_end
        dur = self.seg_end - self.seg_start
        if dur >= MAX_SEG_S or (dur >= MIN_SEG_S and text.rstrip()[-1:] in ".?!"):
            return self.flush()
        return None

    def flush(self) -> tuple[str, float, float] | None:
        if self.seg_start is None or not self.seg_text:
            return None
        seg = (" ".join(self.seg_text), self.seg_start, self.seg_end)
        self.seg_text, self.seg_start = [], None
        return seg

    async def resolve_talk(self) -> None:
        talk = await asyncio.to_thread(store.current_talk, self.room, to_utc_iso(self.started))
        if talk:
            self.talk_id = talk["talk_id"]
            starts = datetime.fromisoformat(talk["starts_at"].replace("Z", "+00:00"))
            self.offset = max(0.0, (self.started - starts).total_seconds())

    def wall(self, t: float) -> str:
        return to_utc_iso(self.started + timedelta(seconds=t))


async def index_chunk(stream: "Stream", text: str, t_start: float, t_end: float) -> None:
    try:
        vec = await asyncio.to_thread(embed.embed_passage, text)
        doc = make_moment(
            talk_id=stream.talk_id, room=stream.room,
            t_start=stream.offset + t_start, t_end=stream.offset + t_end,
            timestamp=stream.wall(t_start), text=text, embedding=vec,
        )
        await asyncio.to_thread(store.index_moment, doc)
    except Exception as e:
        log.warning("index failed room=%s type=%s", stream.room, type(e).__name__)


@app.get("/healthz")
async def healthz():
    asr_ok = False
    try:
        r = await asr_client.get("/healthz", timeout=2.0)
        asr_ok = r.status_code == 200
    except httpx.HTTPError:
        pass
    return {"ok": True, "asr": asr_ok, "time": utc_now_iso()}


@app.get("/api/rooms")
async def rooms():
    names = set(hub.sources) | set(hub.subs)
    live = await asyncio.to_thread(store.live_talks, utc_now_iso())
    names |= set(live)
    return {
        "rooms": [
            {
                "room": r,
                "live": hub.sources.get(r, 0) > 0,
                "viewers": len(hub.subs.get(r, ())),
                "title": live.get(r, {}).get("title"),
                "talk_id": live.get(r, {}).get("talk_id"),
            }
            for r in sorted(names)
        ]
    }


@app.get("/api/search")
async def search(q: str, size: int = 10):
    q = q.strip()[:200]
    if not q:
        return {"hits": []}
    vec = await asyncio.to_thread(embed.embed_query, q)
    hits = await asyncio.to_thread(store.search, q, vec, min(size, 25))
    return {"hits": hits}


@app.get("/api/moments")
async def moments(talk_id: str, t: float = 0.0):
    items = await asyncio.to_thread(store.moments_around, talk_id, t)
    talk = await asyncio.to_thread(store.get_talk, talk_id)
    return {"talk": talk, "moments": items}


async def transcribe(pcm: bytes) -> str:
    r = await asr_client.post("/transcribe", content=pcm)
    r.raise_for_status()
    return r.json()["text"]


async def process_window(
    stream: Stream, pcm: bytes, t_start: float, t_end: float, t_recv: float
) -> None:
    room = stream.room
    try:
        text = await transcribe(pcm)
    except httpx.HTTPError as e:
        log.warning("asr error room=%s type=%s", room, type(e).__name__)
        return
    new = merge_overlap(hub.last_text.get(room, ""), text)
    if text:
        hub.last_text[room] = text
    if not new:
        return
    latency = time.monotonic() - t_recv
    await hub.broadcast(
        room,
        {
            "type": "caption",
            "room": room,
            "text": new,
            "talk_id": stream.talk_id,
            "t_start": round(stream.offset + t_start, 2),
            "t_end": round(stream.offset + t_end, 2),
            "@timestamp": utc_now_iso(),
            "latency_s": round(latency, 3),
        },
    )
    log.info("caption room=%s t=%.1f-%.1f chars=%d latency_s=%.3f", room, t_start, t_end, len(new), latency)
    seg = stream.add(new, t_start, t_end)
    if seg:
        asyncio.create_task(index_chunk(stream, *seg))


@app.websocket("/ws/audio")
async def ws_audio(ws: WebSocket, room: str):
    room = slugify(room)
    await ws.accept()
    stream = Stream(room)
    await stream.resolve_talk()
    hub.sources[room] += 1
    windower = Windower(1.5, 0.5)
    queue: asyncio.Queue = asyncio.Queue(maxsize=8)

    async def worker():
        while True:
            item = await queue.get()
            if item is None:
                return
            await process_window(stream, *item)

    task = asyncio.create_task(worker())
    log.info("audio source connected room=%s talk_id=%s", room, stream.talk_id)
    try:
        while True:
            data = await ws.receive_bytes()
            now = time.monotonic()
            for pcm, t0, t1 in windower.feed(data):
                if queue.full():  # ASR falling behind: drop the oldest window, keep it live
                    queue.get_nowait()
                    log.warning("dropped window room=%s", room)
                queue.put_nowait((pcm, t0, t1, now))
    except WebSocketDisconnect:
        pass
    finally:
        hub.sources[room] -= 1
        await queue.put(None)
        await task
        seg = stream.flush()
        if seg:
            await index_chunk(stream, *seg)
        log.info("audio source disconnected room=%s", room)


@app.websocket("/ws/captions")
async def ws_captions(ws: WebSocket, room: str):
    room = slugify(room)
    await ws.accept()
    hub.subs[room].add(ws)
    try:
        while True:
            await ws.receive_text()  # keepalive pings from the page; content ignored
    except WebSocketDisconnect:
        pass
    finally:
        hub.subs[room].discard(ws)
