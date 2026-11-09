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
 │   :8090 (whisper.cpp  CUDA   moments/talks  percolator  (topic+room+link)│
 │   for lang=auto)            :9200                                        │
 │   vLLM Qwen3-4B :8000 (minute titles, translation flag)                  │
 │   OpenTelemetry ─────────────────────────────────────────► Dash0         │
 └──────────────────────────────────────────────────────────────────────────┘
        ▲ /api/* proxy
 ┌──────┴──────── team cluster (app/, Argo CD) ─────┐
 │  Express :8080  /healthz /readyz, caption page,  │
 │  Dash0 RUM (no session replay), Node OTel         │
 │  https://tower.cnh.radarhq.io                     │
 └───────────────────────────────────────────────────┘
```

## Run it

### Spark half (`spark/`)

_Filled in as the services land: `spark/docker-compose.yml` + `spark/run.sh` (tmux)._

```bash
set -a; source ~/cnh-prep/.env; set +a      # secrets stay outside the repo
cd spark && ruff check . && pytest -q
```

### Cluster half (`app/`)

Push to `main`: the `build-and-deploy` Action builds an amd64 image to GHCR and Argo CD syncs
namespace `team-tower`. Runtime tokens come from Kubernetes Secret `app-credentials`, created by a
human, never committed.

## Privacy

See [.gitar/documents/privacy.md](.gitar/documents/privacy.md). In short: no caption text, interest
strings or chat IDs in logs, traces, metrics or exceptions; raw audio never persisted; inference
services call only localhost; no face detection or recognition; all timestamps UTC ISO-8601.

## How we built it

Every feature is a small PR reviewed by Gitar (rules in `.gitar/`). Build log: [docs/BUILD_LOG.md](docs/BUILD_LOG.md).
Starter template notes: [docs/STARTER.md](docs/STARTER.md).

**AI tools used: Claude Code, Codex CLI, OpenCode — disclosed per the rules.**
