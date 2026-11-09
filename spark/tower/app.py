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

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from tower.chunker import Windower, merge_overlap
from tower.timeutil import utc_now_iso

ASR_URL = os.environ.get("ASR_URL", "http://127.0.0.1:8090")

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


@app.on_event("startup")
async def _startup() -> None:
    global asr_client
    asr_client = httpx.AsyncClient(base_url=ASR_URL, timeout=10.0)


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
    return {
        "rooms": [
            {"room": r, "live": hub.sources.get(r, 0) > 0, "viewers": len(hub.subs.get(r, ()))}
            for r in sorted(names)
        ]
    }


async def transcribe(pcm: bytes) -> str:
    r = await asr_client.post("/transcribe", content=pcm)
    r.raise_for_status()
    return r.json()["text"]


async def process_window(room: str, pcm: bytes, t_start: float, t_end: float, t_recv: float) -> None:
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
            "t_start": round(t_start, 2),
            "t_end": round(t_end, 2),
            "@timestamp": utc_now_iso(),
            "latency_s": round(latency, 3),
        },
    )
    log.info("caption room=%s t=%.1f-%.1f chars=%d latency_s=%.3f", room, t_start, t_end, len(new), latency)


@app.websocket("/ws/audio")
async def ws_audio(ws: WebSocket, room: str):
    await ws.accept()
    hub.sources[room] += 1
    windower = Windower(1.5, 0.5)
    queue: asyncio.Queue = asyncio.Queue(maxsize=8)

    async def worker():
        while True:
            item = await queue.get()
            if item is None:
                return
            await process_window(room, *item)

    task = asyncio.create_task(worker())
    log.info("audio source connected room=%s", room)
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
        log.info("audio source disconnected room=%s", room)


@app.websocket("/ws/captions")
async def ws_captions(ws: WebSocket, room: str):
    await ws.accept()
    hub.subs[room].add(ws)
    try:
        while True:
            await ws.receive_text()  # keepalive pings from the page; content ignored
    except WebSocketDisconnect:
        pass
    finally:
        hub.subs[room].discard(ws)
