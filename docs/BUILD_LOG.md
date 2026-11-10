# TOWER build log (2026-11-09, times MT)

| Time | What | PR | Gitar | Dash0 / Radar |
|---|---|---|---|---|
| 12:10 | Repo `francolinx/tower-tower` from `skyhook-io/cnh-starter`, `setup.sh tower` pushed to main | — | — | — |
| 12:20 | Gitar review instructions + rules, privacy doc, CI (ruff + pytest + image build), README skeleton | #1 | Approved, no findings; flagged the Mountain→UTC DST edge as the medium-risk area | — |
| 12:25 | Parakeet v2 ASR service (stdlib HTTP in `cnh-asr:ready`, :8090) + tower-core `/ws/audio` → `/ws/captions`. 10.65 s WAV: p50 **36 ms**, p95 **47 ms** caption latency | #2 | **Blocked, 2 findings → fixed:** public `/ws/audio` had no auth (anyone on the Funnel could inject captions) → shared room key + 2 sources/room; vLLM container lacked `HF_HUB_OFFLINE=1` | — |
| 12:42 | Funnel live (HTTPS certs enabled): `https://spark-6771.tail626e79.ts.net` → :8088. Same WAV over public WSS: p50 44 ms, p95 52 ms | — | — | — |
| 12:43 | Caption page (≥28 px resizable, 42ch × 3 lines, ~18:1 contrast), mic mode, Express gateway, Dash0 RUM (no replay), Node OTel | #3 | **3 findings, auto-applied:** search text leaked into RUM + Node spans via URL query (→ POST + RUM URL scrubber); 16 kHz AudioContext breaks Firefox (→ resample in worklet); PR too big | — |
| 13:45 | ES `moments` (strict, 384-d) + `talks` (78 Monday sessions, 15 real rooms, Mountain→UTC), bge-small on CUDA, RRF search, jump-to-moment | #4 | **3 findings + 1 auto-fix:** search query in uvicorn access log (→ POST, `--no-access-log`); talk resolved only at connect (→ re-resolve per chunk); ES outage → 500 (→ tolerate) | — |
| 13:55 | Interests percolator + Telegram `/start` codes + alerts (topic + room + link, 10-min cooldown) | #5 | **5 findings, fixed:** httpx INFO logs printed the **bot token** on every poll; poll loop spun on 401/409/429; `chats.json` briefly world-readable; code collisions; failed sends used up the cooldown | — |
| 14:00 | OTel spans (`caption.chunk` → `asr` / `embed` → `index` → `percolate`), metrics `caption.latency`, `captions.total`, `captions.within_slo`; Spark-hosted page fallback | #6 | **1 finding, auto-applied:** the Spark-hosted page fallback was a second feature bundled in → Gitar removed it from the PR. Self-caught before review: auto-instrumentation would have put the room key (WS URL) and the Telegram token (httpx URLs) on spans → excluded | **Dash0 (15:05):** spans `caption.chunk` → `asr`, `embed`, `index`, `percolate` arriving from `tower-core` (service.namespace `tower`); 3× WAV probe → 30 captions, p50 37.5 ms / p95 92.5 ms, SLO ratio 1.0 |
| 14:10 | Venue graph (121 nodes / 127 edges, Salt Palace L1–L3 + Hyatt L1–L5), Dijkstra with step-free mode, ES `venue` geo_point, nearest quiet/first-aid/restroom, wayfinding panel + Speak | #7 | **2 findings, auto-applied:** **Gitar removed the user's location from Telegram alerts** — alerts would have sent the user's location + a route URL to Telegram (rule: topic + room + link only) → route moved to the moment page, location stays in the browser; camera UI posted to a `/api/locate` that didn't exist yet → moved to #8 | Radar: Argo CD auto-synced `a0e730e` within ~1 min of merge |
| 14:20 | Sign-photo locator: Qwen3-VL-4B (vLLM :8001, 0.20 GPU), `POST /api/locate`. Synthetic "255 EF" sign (42 KB JPEG): **0.71 s cold, 0.52 s warm** VLM; **0.48 s** server, **0.51 s** round trip over the Funnel; matched `salt-palace-level-2-255-ef` at confidence 1.0. Image never stored | #8 | **2 findings, auto-applied:** multipart upload let Starlette spool photos > 1 MB to a temp file on disk (breaks "never stored") → endpoint now streams a raw `image/jpeg` body into memory with a hard 2 MB cap; fuzzy match put "150 A" in `150-a-c` → exact match for room codes. Gitar's server change left the page still posting multipart (→ 415); we caught it before merge and switched the page to a raw body | — |
| 15:15 | **Cluster live.** Argo CD Application `app` applied via Radar MCP; Secret `app-credentials` (OTLP endpoint/headers, Dash0 token; no RUM token yet) created via Radar; rolling restart. `https://tower.cnh.radarhq.io` serves the caption page (`/version` = `cb1f95e`), `/api/*` proxies to the Spark | — | — | Radar Checks "before": 0 live issues, 4 medium posture findings on `Deployment/app` ([docs/radar-checks-before.md](radar-checks-before.md)) |
| 15:20 | End-to-end over the public Funnel (audio in via `wss://…/ws/audio`, viewer on `wss://…/ws/captions`, same path the team page uses): server latency p50 **35 ms** / p95 **50 ms**; wall clock from end of audio window to caption at the viewer ≈ **50 ms** | — | — | — |
| 15:35 | Qwen3-VL now runs from `./run.sh --vision` (compose `tower-vlm`), hand-started `vlm` container removed. Gotcha: the earlier failed `--vision` run (port 8001 taken) left `tower-vlm` created without its port; compose reused it → `--force-recreate` once. Locate over the Funnel after the switch: 0.72 s cold / 0.52 s warm, 255 EF @ 1.0 | — | — | — |
| 15:35 | Gateway telemetry: `tower-app` (Node, http + express) spans arriving in Dash0 — 698 requests / 30 min, p95 4.4 ms, 0 % errors; spans carry `http.route` only (no URL, no query) | — | — | **Dash0:** service catalog shows `tower-app` + `tower-core` |
| 15:40 | Radar Checks fixes: `automountServiceAccountToken: false`, `readOnlyRootFilesystem: true` + `emptyDir` `/tmp` (verified locally with `docker run --read-only`) | #11 | Approved, no findings | **Radar Checks after** (`a9d7d25`): **4 → 2** findings, both Security findings cleared; missingPDB + missingTopologySpread remain ([after](radar-checks-after.md)) |
| 16:05 | Slides search merged: 95 talks / 2486 slide pages indexed in 8.6 s; search returns slide pages (PDF opened at the page) next to moments | #9 | Approved, no findings | — |
| 16:15 | Switchable venue (`/api/venue/graph?venue=`), banner/restroom/floor locator rules, Telegram photo puller | #12 | **Blocked, 4 findings → fixed:** the `venue` query param shadowed the Salt Palace graph (→ `/nearest` 500); puller tracebacks would print the bot-token URL; caption text on stdout; bundling (kept, explained) | — |
| 16:28 | The Shop graph (demo default, 41 nodes / 55 edges, P–L4 + roof); loader normalises its alias-map + `sign_hints` shape; Matterport-based coordinates | #13 | **Changes requested, auto-applied:** Shop elevator/stair ids weren't recognised as shafts, so rides read as walks → fixed; we also ranked levels (P < L2 … < ROOF) for up/down | — |
| 16:34 | Inline SVG level map (rooms as boxes, animated route + moving dot, level tabs) + Matterport 3D-scan link; verified live: stage → roof NW step-free, 3 min | #14 | Approved | — |
| 16:40 | Level label fix (LL3 → L3); README final (diagram no longer shows the cut text model) | #16, #15 | — | — |
| 16:56 | The Shop coordinates from the Matterport floor plans (stair core 68,5; elevator 56,7; west corridor; NE meeting rooms, restrooms + food); deployed `8cb3e95`, stage → roof NW step-free 170 s | #17 | Approved, no findings | — |
| 17:00 | README setup steps checked against the repo (slides seeding, gateway serves the page, Secret via Radar) | #18 | — | — |
| 17:05 | README "Next": visual place recognition (100 panoramas of The Shop, outside the repo) | #19 | **Gitar review pending at freeze** (merged on green CI per the 17:05 rule) | — |
| 17:10 | **Freeze**, tag `v0.1` | — | — | — |
| — | Photo test on real venue photos: **not run** — no photos reached the bot before the freeze (puller + rules unit-tested; synthetic "255 EF" sign still 0.52 s warm, confidence 1.0) | — | — | — |

## Dash0 metric names (as stored, PromQL)
OTel instrument → Prometheus name in Dash0 (label `room` only, no content):
- `caption.latency` (histogram, s) → `caption_latency_seconds_bucket` / `_sum` / `_count`
- `captions.total` (counter) → `captions_total`
- `captions.within_slo` (counter, latency ≤ 2.0 s) → `captions_within_slo_total`
- Also addressable as `{otel_metric_name="captions.total"}` etc.

Queries: p95 per room `histogram_quantile(0.95, sum by (le, room) (rate(caption_latency_seconds_bucket[5m])))`;
SLO `sum(increase(captions_within_slo_total[1h])) / sum(increase(captions_total[1h]))` ≥ 0.95.

## Scope changes
- 16:32 Full `/map` page (#12b) not built; shipped the inline SVG level map on the existing page instead (#14).
- 13:50 Cut the vLLM text model (minute titles + translation flag); GPU budget moved to Qwen3-VL for the sign locator.

## Blockers hit
- 12:20 Tailscale Funnel hung: funnel nodeAttr + operator present, HTTPS certificates off (`CertDomains` empty). Fixed in the admin console at ~12:40.
- 12:28 `TG_TOKEN` empty in the env file → alerts ran in dry-run mode until the token was added.
- Team URL `https://tower.cnh.radarhq.io` returned 404 while the Argo CD Application wasn't applied (Radar MCP not yet authorised in the agent session).
- 13:52 An agent worktree folder got committed as an embedded repo on the #5 branch → untracked, `.claude/worktrees/` added to `.gitignore`.
