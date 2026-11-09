# TOWER

Live captions for conference rooms. Every caption chunk becomes a searchable **moment** in
Elasticsearch, and you get a Telegram alert when something you care about comes up in another room.
All inference runs locally on a DGX Spark.

**No face recognition, no audio stored, all inference local.**

## Architecture

```
 room laptop / phone (mic mode)                 viewers (phones, screens)
        │  WS /ws/audio?room=X                        ▲  WS /ws/captions?room=X
        ▼                                             │
 ┌──────────────── DGX Spark (spark/) ─────────────────────────────────────┐
 │  Tailscale Funnel https://spark-6771.tail626e79.ts.net → :8088          │
 │                                                                          │
 │  tower-core (FastAPI :8088)                                              │
 │   chunk ─► ASR ─► embed ─► index ─► percolate ─► broadcast caption       │
 │            │        │        │          │                                │
 │   Parakeet v2   bge-small  Elasticsearch  interests ─► Telegram alert    │
 │   :8090       CUDA   moments/talks/slides percolator (topic+room+link)│
 │                             :9200                                        │
 │   Qwen3-VL-4B (vLLM :8001): reads room signs + banners -> venue node     │
 │   venue graphs (theshop, saltpalace) -> step-free routes, SVG level map  │
 │   OpenTelemetry ─────────────────────────────────────────► Dash0         │
 └──────────────────────────────────────────────────────────────────────────┘
        ▲ /api/* proxy
 ┌──────┴──────── team cluster (app/, Argo CD) ─────┐
 │  Express :8080  /healthz /readyz, caption page,  │
 │  Dash0 RUM (no session replay), Node OTel         │
 │  https://tower.cnh.radarhq.io                     │
 └───────────────────────────────────────────────────┘
```

## KubeCon NA 2026 is the test venue

> KubeCon captions the room you're in; Tower is for the rooms you're not in.

KubeCon + CloudNativeCon North America 2026 (Salt Lake City) is where we test it:

- **Schedule:** `spark/seed_schedule.py` fetches the public Sessionize feed at runtime (Monday Nov 9, Mountain → UTC)
  into a `talks` index, so rooms and talk titles are real. The JSON is never committed.
- **Venue graph:** `spark/venue/saltpalace.json` is 121 places and 127 walkable links across Salt Palace L1–L3 and
  Hyatt Regency L1–L5: rooms, foyers, entrances, escalators, elevators, stairs, POIs (quiet rooms, first aid,
  all-gender restrooms, prayer room, mothers' room) and a few sponsor booths. We hand-built it from the official venue
  map and the event's accessibility page. Coordinates are rough (0–100), and walking times are estimates.
- **Wayfinding:** `POST /api/route {from, to, step_free}` runs Dijkstra over the graph. Step-free mode only uses
  elevators and step-free links. `GET /api/venue/nearest?kind=quiet&from=...` picks candidates from the ES `venue`
  index (geo_point) and the shortest walk from the graph. Alerts stay topic + room + link only (no location in Telegram); the moment page
  prefills "Take me to" with that room and reads your saved "Where am I" from the browser.
- **Where am I:** pick from the list, or photograph the nearest **room sign**. Qwen3-VL-4B (local, :8001) reads only
  the sign's text and we fuzzy-match it to a venue node.

## The Shop is the demo venue

The live demo runs at The Shop Workspace (Salt Lake City), where the hackathon is: `spark/venue/theshop.json`
(levels P, L2, L3, L4, roof; sponsor tables on L3). `GET /api/venue/graph?venue=theshop|saltpalace` returns either
graph in the same shape; the page draws the current level as an inline SVG with the route animated on it and level
tabs. Point the camera at a banner or sign: "Dash0", "Radar", "Sonar"/"Gitar", "Elastic" find that table,
"Restroom"/🚻 finds the nearest one on your level, "Floor 3" or an elevator panel finds that level's elevator.

Search also covers the speakers' published slide decks, page by page (`spark/seed_slides.py`), next to live moments.

## Run it

### Spark half (`spark/`)

Prereqs on the Spark: Docker with GPU (CDI), the `cnh-asr:ready` image (NeMo + Parakeet v2 `.nemo` mounted from
`~/ssd/GB10_ARSENAL/models/speech`), `vllm/vllm-openai:v0.27.1` with `~/models/qwen3-vl-4b`, Elasticsearch
start-local on :9200, a Python 3.12 venv with `spark/` deps, and an env file outside the repo (see `.env.example`;
`TOWER_AUDIO_KEY` is the room-device key).

```bash
cd spark
./run.sh --vision                        # ASR (+ Qwen3-VL) in Docker, tower-core in tmux under opentelemetry-instrument
set -a; source ~/cnh-prep/.env; set +a
python seed_schedule.py                  # 78 Monday talks -> talks index
tailscale funnel --bg 8088               # public https://spark-6771.tail626e79.ts.net
python tools/send_wav.py some16k.wav --room salt-palace-level-2-255-ef   # latency probe
ruff check . && pytest -q
```

tower-core also serves the caption page at `/`, so the Spark URL works without the cluster.

### Cluster half (`app/`)

Push to `main`: the `build-and-deploy` Action builds an amd64 image to GHCR and Argo CD syncs
namespace `team-tower`. Runtime tokens come from Kubernetes Secret `app-credentials`, created by a
human, never committed.

## Privacy

See [.gitar/documents/privacy.md](.gitar/documents/privacy.md). In short:

- No caption text, interest strings or chat IDs in logs, traces, metrics or exceptions.
- Raw audio is never persisted.
- Inference services call only localhost.
- No face detection or recognition.
- All timestamps are UTC ISO-8601.
- **Locating uses room signs, never faces or GPS.** The sign photo is held in memory for one request and dropped.
  It is never written to disk or logged, and spans carry only its byte size and latency. The model is asked only for
  the sign's text.
- Telegram chat IDs live only in a local 0600 file on the Spark, keyed by an opaque code. A last-known location is
  kept in memory only.

## How we built it

Every feature is a small PR reviewed by Gitar (rules in `.gitar/`). Build log: [docs/BUILD_LOG.md](docs/BUILD_LOG.md).
Starter template notes: [docs/STARTER.md](docs/STARTER.md).

**AI tools used: Claude Code, Codex CLI, OpenCode — disclosed per the rules.**
