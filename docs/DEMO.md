# TOWER — 2-minute demo

Setup: laptop A is the room device for **255 EF** (`?room=salt-palace-level-2-255-ef`, mic mode on). Phone B is
an attendee with an interest saved ("eBPF security") and Telegram open. Dash0 and Radar tabs open.

| Time | Beat | What to show / say |
|---|---|---|
| 0:00–0:15 | Problem | "KubeCon captions the room you're in; Tower is for the rooms you're not in." |
| 0:15–0:40 | Live captions | Pitch into laptop A; captions on phone B within a second. "Parakeet on a DGX Spark. No audio stored, nothing leaves the box." |
| 0:40–1:00 | Alert → "you're at 150" → step-free route | Teammate says "eBPF security" in room B. Phone B buzzes: *"eBPF security" just came up in 255 EF* + link (topic, room, link — never your location). Tap it: the page already knows you're at 150 D-F (saved on the phone, not the server) and shows the step-free route to 255 EF — numbered steps, elevator never escalator; **Speak** reads them out. |
| 1:00–1:10 | Where am I, by sign | 📷 Sign → photo of a room sign → picker fills in ("255 EF, 100% match"). "Signs only, never faces or GPS." |
| 1:10–1:25 | Search the moment | Search "the eBPF security bit" → hybrid hit (BM25 + vectors, RRF) with room + talk + timestamp → jump to the moment. |
| 1:25–1:40 | Operate it | Dash0: caption latency p50/p95 per room, SLO `captions.within_slo / captions.total` ≥ 95 % green; a trace (`caption.chunk` → `asr` → `embed` → `index` → `percolate`) with no transcript text in it. |
| 1:40–2:00 | Built with review + Radar | Every PR Gitar-reviewed (it caught a bot-token log leak and an unauthenticated audio socket). Radar: timeline of releases, the AI investigation and what we changed, Checks before/after. |

Fallback if the room is noisy: stream the recorded clip with `spark/tools/send_wav.py <clip.wav> --room salt-palace-level-2-255-ef --url wss://spark-6771.tail626e79.ts.net`.
