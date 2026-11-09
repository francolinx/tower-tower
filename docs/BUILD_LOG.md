# TOWER build log (2026-11-09, times MT)

| Time | What | PR | Gitar | Dash0 / Radar |
|---|---|---|---|---|
| 12:10 | Repo `francolinx/tower-tower` from `skyhook-io/cnh-starter`, `setup.sh tower` pushed to main | — | — | — |
| 12:20 | Gitar review instructions + rules, privacy doc, CI (ruff + pytest + image build), README skeleton | #1 | Approved, no findings; flagged Mountain→UTC DST edge as the medium-risk area; 2 rules not applicable | — |
| 12:25 | Parakeet v2 ASR service (stdlib HTTP in `cnh-asr:ready`, :8090) + tower-core `/ws/audio` → `/ws/captions`. 10.65 s WAV: p50 **36 ms**, p95 **47 ms** caption latency | #2 | _pending_ | — |
| 12:35 | Caption page (≥28 px resizable, 42ch, 3 lines, ~18:1 contrast), mic mode (AudioWorklet → PCM16 16 kHz), Express gateway `/api/*` → Spark, Dash0 RUM (no replay), Node OTel auto-instrumentation, `app-credentials` Secret ref (optional) | #3 | _pending_ | — |

## Blockers hit
- 12:20 Tailscale Funnel: nodeAttr + operator present, but HTTPS certificates not enabled for the tailnet (`CertDomains` empty) → `tailscale funnel --bg 8088` hangs. Needs admin console → DNS → HTTPS Certificates.

