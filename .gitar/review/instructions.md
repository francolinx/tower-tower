# Review instructions for TOWER

TOWER captions live conference talks, indexes every caption chunk as a searchable "moment" in
Elasticsearch, and sends Telegram alerts when a saved interest comes up in another room. All
inference runs locally on a DGX Spark. Speech content and chat identities are sensitive.

Read `.gitar/documents/privacy.md` before reviewing. The rules below apply to every PR.

## Privacy (Report a blocking review finding)

Report a blocking review finding when a change:

1. Puts transcript or caption **text**, interest/query strings, Telegram **chat IDs**, usernames or
   phone numbers into log lines (any level), OpenTelemetry span names, span attributes or span
   events, metric names or metric labels, RUM/browser telemetry, or exception messages.
   Allowed instead: lengths, counts, durations, byte sizes, `room`, `talk_id`, model names, opaque
   hashes.
2. Persists **raw audio** anywhere (disk, ES, object storage, temp files, debug dumps). Audio lives
   in memory only long enough to transcribe.
3. Makes an inference service (ASR, LLM, embeddings) call anything other than `localhost` /
   `127.0.0.1`, or loads a model without `local_files_only=True` / `HF_HUB_OFFLINE=1`
   (NeMo: `ASRModel.restore_from(<local .nemo>)`).
4. Adds any face detection or face recognition library, model or code path, anywhere.
5. Commits a secret, token, password, API key, kubeconfig or a real `.env` file, or prints one.
6. Enables Dash0 RUM session replay.

## UTC timestamps (Report a blocking review finding)

Report a blocking review finding when a change writes a timestamp that is not UTC ISO-8601 with a
trailing `Z` (e.g. `2026-11-09T21:05:13.250Z`): naive `datetime.now()`, `datetime.utcnow()`,
local time, `+00:00` suffixes, or epoch numbers in stored documents. Sessionize schedule times are
naive America/Denver and must be converted with `zoneinfo.ZoneInfo("America/Denver")` at ingestion.

## Data conventions

- Every moment indexed to Elasticsearch carries `talk_id`, `room`, `t_start`, `t_end` and
  `@timestamp`. Flag code that indexes one without all five.
- Index mappings live only in `spark/es/mappings/*.json`. Flag inline mapping dicts in code,
  `dynamic: true` on the moments index, or reliance on dynamic mapping.
- Embedding dims are fixed at 384 (bge-small-en-v1.5, cosine). A change in dims needs a new index
  and a reindex.
- The Sessionize schedule JSON is fetched at runtime and must never be committed.

## Process

- One small feature per PR. Point out unrelated changes that should be split.
- Telegram alerts carry topic + room + a moment link only, at most one per interest per 10 minutes.
- Don't approve changes that break the Kubernetes deployment contract: the app listens on `$PORT`
  (8080) and serves `/healthz` and `/readyz`; Service `app` port 80 stays.
- When you flag something, quote the line and propose the compliant alternative.
