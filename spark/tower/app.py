"""tower-core: live captions over WebSockets. Runs on the Spark at 127.0.0.1:8088 (Funnel in front).

WS  /ws/audio?room=X     binary frames: PCM16 LE mono 16 kHz, any frame size
WS  /ws/captions?room=X  JSON caption events
GET /healthz
GET /api/rooms

Privacy: logs carry room, counts and durations only. Audio is never written to disk.
"""

import asyncio
import hmac
import json
import logging
import os
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import (
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tower import embed, locate
from tower.alerts import Alerter, ChatRefs, Telegram
from tower.chunker import Windower, merge_overlap
from tower.store import Store, make_moment, slugify
from tower.telemetry import record_caption, tracer
from tower.timeutil import to_utc_iso, utc_now_iso
from tower.venue import Venue

ASR_URL = os.environ.get("ASR_URL", "http://127.0.0.1:8090")
MIN_SEG_S, MAX_SEG_S = 3.0, 7.0  # moment length bounds
RESOLVE_EVERY_S = 60  # re-check which scheduled talk is in the room
# Shared secret a room device must present to stream audio (?key=...). Caption reads stay public:
# captions are shown to the room's audience anyway. No key configured -> audio is refused.
AUDIO_KEY = os.environ.get("TOWER_AUDIO_KEY", "")
MAX_SOURCES_PER_ROOM = 2


def audio_key_ok(key: str | None) -> bool:
    return bool(AUDIO_KEY) and key is not None and hmac.compare_digest(key.encode(), AUDIO_KEY.encode())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03dZ %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logging.Formatter.converter = time.gmtime  # log timestamps in UTC
# httpx logs full request URLs at INFO; the Telegram URL embeds the bot token
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
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
alerter: Alerter | None = None
venue = Venue.load()


@app.on_event("startup")
async def _startup() -> None:
    global asr_client, store, alerter
    asr_client = httpx.AsyncClient(base_url=ASR_URL, timeout=10.0)
    store = Store()
    await asyncio.to_thread(store.ensure_indices)
    await asyncio.to_thread(store.index_venue, venue.geo_docs())
    alerter = Alerter(store, Telegram(os.environ.get("TG_TOKEN")), ChatRefs(), venue)
    asyncio.create_task(alerter.tg.poll(alerter.on_start))
    log.info("telegram alerts %s", "enabled" if alerter.tg.enabled else "disabled (no TG_TOKEN)")
    await asyncio.to_thread(embed.model)  # load bge-small on CUDA before the first chunk
    log.info("store + embeddings ready")


class Stream:
    """One audio source session: which talk it belongs to and where t=0 is."""

    def __init__(self, room: str):
        self.room = room
        self.started = datetime.now(UTC)
        self.talk_id = f"{room}-{self.started.strftime('%Y%m%dT%H%M%SZ')}"
        self.room_name = room
        self.offset = 0.0  # seconds from talk start to stream start
        self.talk_ends: datetime | None = None
        self.next_check = self.started
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

    async def resolve_talk(self) -> bool:
        """Point this stream at the scheduled talk in its room now. Returns True if it changed.

        Re-run per chunk via maybe_rotate, so a device that stays connected across back-to-back
        sessions files each moment under the right talk. t = seconds from that talk's start.
        """
        now = datetime.now(UTC)
        self.next_check = now + timedelta(seconds=RESOLVE_EVERY_S)
        talk = await asyncio.to_thread(store.current_talk, self.room, to_utc_iso(now))
        if talk:
            if talk["talk_id"] == self.talk_id:
                return False
            starts = datetime.fromisoformat(talk["starts_at"].replace("Z", "+00:00"))
            self.talk_id = talk["talk_id"]
            self.room_name = talk.get("room_name") or self.room
            self.offset = (self.started - starts).total_seconds()
            self.talk_ends = datetime.fromisoformat(talk["ends_at"].replace("Z", "+00:00"))
            return True
        if self.talk_ends is not None and now >= self.talk_ends:
            # scheduled talk is over and nothing follows: start an unscheduled block
            self.talk_id = f"{self.room}-{now.strftime('%Y%m%dT%H%M%SZ')}"
            self.room_name = self.room
            self.offset = (self.started - now).total_seconds()
            self.talk_ends = None
            return True
        return False

    async def maybe_rotate(self):
        """If a re-check is due and the talk changed, return the open segment under the old talk."""
        now = datetime.now(UTC)
        if now < self.next_check and (self.talk_ends is None or now < self.talk_ends):
            return None
        old_id, old_offset = self.talk_id, self.offset
        seg = None
        if await self.resolve_talk():
            seg = self.flush()
        return (seg, old_id, old_offset) if seg else None

    def wall(self, t: float) -> str:
        return to_utc_iso(self.started + timedelta(seconds=t))


async def index_chunk(
    stream: "Stream", text: str, t_start: float, t_end: float, talk_id: str, offset: float
) -> None:
    attrs = {"room": stream.room, "talk_id": talk_id, "moment.chars": len(text)}
    try:
        with tracer.start_as_current_span("embed", attributes=attrs):
            vec = await asyncio.to_thread(embed.embed_passage, text)
        doc = make_moment(
            talk_id=talk_id, room=stream.room,
            t_start=offset + t_start, t_end=offset + t_end,
            timestamp=stream.wall(t_start), text=text, embedding=vec,
        )
        with tracer.start_as_current_span("index", attributes=attrs):
            await asyncio.to_thread(store.index_moment, doc)
        with tracer.start_as_current_span("percolate", attributes=attrs) as span:
            sent = await alerter.check(doc, stream.room_name)
            span.set_attribute("alerts.sent", sent)
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


class SearchIn(BaseModel):
    q: str = Field(max_length=200)
    size: int = Field(default=10, ge=1, le=25)


# POST, not GET: a query string would end up in HTTP span attributes and access logs.
@app.post("/api/search")
async def search(body: SearchIn):
    q, size = body.q.strip(), body.size
    if not q:
        return {"hits": []}
    vec = await asyncio.to_thread(embed.embed_query, q)
    hits = await asyncio.to_thread(store.search, q, vec, size)
    return {"hits": hits}


class InterestIn(BaseModel):
    chat_ref: str = Field(min_length=4, max_length=32)
    query: str = Field(min_length=2, max_length=120)


@app.post("/api/interests", status_code=201)
async def add_interest(body: InterestIn):
    interest_id = await asyncio.to_thread(alerter.add_interest, body.chat_ref, body.query.strip())
    if interest_id is None:
        raise HTTPException(status_code=404, detail="unknown Telegram code; message the bot /start")
    log.info("interest stored id=%s query_len=%d", interest_id, len(body.query))
    return {"id": interest_id}


# --- venue: wayfinding inside the Salt Palace + Hyatt (KubeCon NA 2026 test venue)
@app.get("/api/venue/nodes")
async def venue_nodes():
    return {"nodes": venue.public_nodes()}


class RouteIn(BaseModel):
    from_: str = Field(alias="from", min_length=1, max_length=80)
    to: str = Field(min_length=1, max_length=80)
    step_free: bool = False


@app.post("/api/route")
async def route(body: RouteIn):
    try:
        with tracer.start_as_current_span("route", attributes={"step_free": body.step_free}) as span:
            r = venue.route(body.from_, body.to, step_free=body.step_free)
            span.set_attribute("route.steps", len(r["steps"]))
            span.set_attribute("route.seconds", r["total_seconds"])
        return r
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown place") from None
    except ValueError:
        raise HTTPException(status_code=422, detail="no route") from None


@app.get("/api/venue/nearest")
async def venue_nearest(kind: str, from_: str = Query(alias="from"), step_free: bool = False):
    """Candidates from ES geo_distance on the venue index, then the shortest walk via the graph."""
    try:
        src = venue.resolve(from_)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown place") from None
    n = venue.nodes[src]
    cands = await asyncio.to_thread(store.venue_candidates, kind, n["y"] / 1000, n["x"] / 1000)
    best = None
    for c in cands:
        try:
            r = venue.route(src, c, step_free=step_free)
        except (KeyError, ValueError):
            continue
        if best is None or r["total_seconds"] < best["total_seconds"]:
            best = {"node": c, "name": venue.nodes[c]["name"],
                    "total_seconds": r["total_seconds"], "route": r}
    if best is None:  # ES down or no geo hit: pure graph search
        try:
            best = venue.nearest(kind, src, step_free=step_free)
        except (KeyError, ValueError):
            raise HTTPException(status_code=404, detail="nothing of that kind reachable") from None
    return best


@app.post("/api/locate")
async def locate_from_sign(image: Annotated[UploadFile, File()]):
    """Photo of a room sign -> venue node. The image lives in memory for this request only."""
    if image.content_type not in ("image/jpeg", "image/jpg", "image/png"):
        raise HTTPException(status_code=415, detail="send a JPEG or PNG")
    data = await image.read(locate.MAX_IMAGE_BYTES + 1)
    try:
        if len(data) > locate.MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="image must be 2 MB or smaller")
        t0 = time.monotonic()
        with tracer.start_as_current_span("locate", attributes={"image.bytes": len(data)}) as span:
            try:
                sign = await locate.read_sign(asr_client, data, image.content_type)
            except httpx.HTTPError as e:
                log.warning("locate vlm error type=%s", type(e).__name__)
                raise HTTPException(status_code=503, detail="sign reader unavailable") from None
            node, conf = locate.match_sign(sign, venue.public_nodes()) if sign else (None, 0.0)
            latency = time.monotonic() - t0
            span.set_attribute("locate.latency_s", round(latency, 3))
            span.set_attribute("locate.matched", node is not None)
        log.info("locate bytes=%d latency_s=%.2f matched=%s", len(data), latency, node is not None)
        return {"node": node, "name": venue.nodes[node]["name"] if node else None, "confidence": conf}
    finally:
        del data  # never stored
        await image.close()


class LocationIn(BaseModel):
    chat_ref: str = Field(min_length=4, max_length=32)
    node: str = Field(min_length=1, max_length=80)


@app.post("/api/me/location", status_code=204)
async def set_location(body: LocationIn):
    try:
        ok = alerter.set_location(body.chat_ref, body.node)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown place") from None
    if not ok:
        raise HTTPException(status_code=404, detail="unknown Telegram code")
    return Response(status_code=204)


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
    with tracer.start_as_current_span(
        "caption.chunk",
        attributes={"room": room, "talk_id": stream.talk_id, "audio.bytes": len(pcm)},
    ) as chunk_span:
        await _process_window(stream, chunk_span, pcm, t_start, t_end, t_recv)


async def _process_window(stream, chunk_span, pcm, t_start, t_end, t_recv) -> None:
    room = stream.room
    try:
        with tracer.start_as_current_span("asr", attributes={"room": room, "model": "parakeet-tdt-0.6b-v2"}):
            text = await transcribe(pcm)
    except httpx.HTTPError as e:
        log.warning("asr error room=%s type=%s", room, type(e).__name__)
        chunk_span.set_attribute("error.type", type(e).__name__)
        return
    new = merge_overlap(hub.last_text.get(room, ""), text)
    if text:
        hub.last_text[room] = text
    if not new:
        return
    rotated = await stream.maybe_rotate()
    if rotated:
        (text_, s0, s1), old_id, old_off = rotated
        asyncio.create_task(index_chunk(stream, text_, s0, s1, old_id, old_off))
    latency = time.monotonic() - t_recv
    record_caption(room, latency)
    chunk_span.set_attribute("caption.latency_s", round(latency, 3))
    chunk_span.set_attribute("caption.chars", len(new))
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
        asyncio.create_task(index_chunk(stream, *seg, stream.talk_id, stream.offset))


@app.websocket("/ws/audio")
async def ws_audio(ws: WebSocket, room: str, key: str | None = None):
    room = slugify(room)
    if not audio_key_ok(key):
        log.warning("audio source rejected room=%s reason=key", room)
        await ws.close(code=4401)
        return
    if hub.sources[room] >= MAX_SOURCES_PER_ROOM:
        log.warning("audio source rejected room=%s reason=busy", room)
        await ws.close(code=4429)
        return
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
            await index_chunk(stream, *seg, stream.talk_id, stream.offset)
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


# --- Fallback: serve the caption page straight from the Spark (same files as app/public).
# The team-cluster gateway is the primary host; this keeps the Spark URL usable on its own.
PAGE_DIR = Path(__file__).resolve().parents[2] / "app" / "public"
DASH0_JS = PAGE_DIR.parent / "node_modules" / "@dash0" / "sdk-web" / "dist" / "dash0.js"


@app.get("/config.js", include_in_schema=False)
async def page_config(request: Request):
    host = request.headers.get("host", "127.0.0.1:8088")
    local = host.startswith(("127.0.0.1", "localhost"))
    cfg = {"version": "spark", "sparkWs": f"{'ws' if local else 'wss'}://{host}", "rum": None}
    return Response(
        f"window.TOWER_CONFIG = {json.dumps(cfg)};\n",
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/vendor/dash0.js", include_in_schema=False)
async def dash0_js():
    if not DASH0_JS.exists():
        return Response("", media_type="application/javascript")
    return FileResponse(DASH0_JS, media_type="application/javascript")


if PAGE_DIR.exists():
    app.mount("/", StaticFiles(directory=PAGE_DIR, html=True), name="page")
