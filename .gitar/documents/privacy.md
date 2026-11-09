# TOWER privacy model

## What we handle

| Data | Where it lives | Never goes to |
|---|---|---|
| Raw audio (16 kHz PCM / WebM-Opus chunks from a room device) | Process memory on the Spark, for one 1–1.5 s window | Disk, Elasticsearch, logs, telemetry |
| Caption text | Elasticsearch `moments` index on the Spark (localhost only), WebSocket broadcast to viewers | Logs, spans, metrics, RUM, exceptions |
| Interest queries ("alert me about…") | Elasticsearch `interests` percolator index | Logs, spans, metrics, Telegram message text beyond the topic label |
| Telegram chat IDs | Server-side lookup table keyed by an opaque `chat_ref` | ES documents, logs, spans, metrics |

## Rules

1. **No content in telemetry.** Logs, span attributes, span events, metric labels and exception
   messages carry only: lengths, counts, durations, byte sizes, `room`, `talk_id`, model names,
   flag values, opaque hashes.
2. **No raw audio persisted.** Audio buffers are dropped after transcription. A temp file is only
   acceptable if it is deleted in a `finally` and never leaves the box; prefer in-memory decoding.
3. **Local inference only.** ASR (Parakeet v2 in `cnh-asr:ready`, whisper.cpp fallback),
   embeddings (bge-small via sentence-transformers) and the LLM (vLLM Qwen3-4B) are called on
   `127.0.0.1`. Models load from local paths with `local_files_only=True` / `HF_HUB_OFFLINE=1`.
   The only outbound calls are Telegram (alerts), Sessionize (schedule seed) and the OTLP exporter
   (Dash0).
4. **No faces.** No face detection or recognition anywhere in the repo.
5. **UTC everywhere.** Timestamps we write are UTC ISO-8601 with a trailing `Z`.
6. **No session replay.** Dash0 RUM records page views, errors and timings only.
7. **Secrets** come from environment / Kubernetes Secret `app-credentials`, never from the repo.
