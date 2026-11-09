---
title: Telemetry privacy checklist
description: Instrumentation changes must not leak captions, interests, chat identities or audio into logs, traces, metrics or RUM.
when: A PR adds or changes logging calls, OpenTelemetry spans, span attributes or events, metrics, RUM / @dash0/sdk-web config, or OTEL_* environment variables.
actions:
  - Post a checklist comment on the PR with the items below.
  - Request changes if caption text, interest strings, chat IDs or raw audio reach any telemetry sink.
---

Checklist to post:

- [ ] No caption/transcript text or interest strings in log messages, span names, span attributes, span events or exception messages (lengths and counts only).
- [ ] No Telegram chat IDs or usernames in logs, spans or metric labels.
- [ ] Metric attributes are limited to `room` (plus fixed enums like `status`); no free text, no user IDs.
- [ ] Custom metrics keep their names: `caption.latency` (histogram, seconds), `captions.total`, `captions.within_slo` (latency <= 2.0 s).
- [ ] GenAI instrumentation has content capture off (`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false`).
- [ ] RUM: session replay is not enabled; caption DOM text is not captured.
- [ ] Exporters point only at the configured `OTEL_EXPORTER_OTLP_ENDPOINT`; tokens come from env / Secret `app-credentials`.
- [ ] Timestamps in telemetry payloads we construct are UTC.
