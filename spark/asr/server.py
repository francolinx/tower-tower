"""Parakeet v2 ASR service. Runs inside the cnh-asr:ready container on 127.0.0.1:8090.

Stdlib HTTP only (the image has NeMo but no web framework, and must not hit the network).

POST /transcribe   body: raw PCM, 16-bit little-endian, mono, 16 kHz
                   -> {"text": str, "audio_s": float, "asr_s": float}
GET  /healthz      -> {"ok": true, "model": "parakeet-tdt-0.6b-v2"}

Privacy: audio stays in memory and is dropped after each request. Nothing is written to disk.
Logs carry durations and byte counts only, never transcript text.
"""

import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("HF_HUB_OFFLINE", "1")

import nemo.collections.asr as nemo_asr  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402

NEMO_PATH = os.environ.get(
    "NEMO_PATH", "/speech/parakeet-tdt-0.6b-v2/parakeet-tdt-0.6b-v2.nemo"
)
HOST = os.environ.get("ASR_HOST", "127.0.0.1")
PORT = int(os.environ.get("ASR_PORT", "8090"))
SAMPLE_RATE = 16000
MAX_BYTES = SAMPLE_RATE * 2 * 30  # 30 s cap per request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03dZ %(levelname)s asr %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logging.Formatter.converter = time.gmtime  # log timestamps in UTC
log = logging.getLogger("asr")

t0 = time.time()
MODEL = nemo_asr.models.ASRModel.restore_from(NEMO_PATH, map_location="cuda").eval()
LOCK = threading.Lock()
log.info("model loaded in %.1fs", time.time() - t0)


def transcribe(pcm: bytes) -> tuple[str, float, float]:
    audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    audio_s = len(audio) / SAMPLE_RATE
    if audio_s < 0.1:
        return "", audio_s, 0.0
    s = time.time()
    with LOCK, torch.inference_mode():
        out = MODEL.transcribe([audio], batch_size=1, verbose=False)
    asr_s = time.time() - s
    hyp = out[0]
    text = hyp.text if hasattr(hyp, "text") else str(hyp)
    return text.strip(), audio_s, asr_s


# warm up so the first real chunk isn't a cold start
transcribe(np.zeros(SAMPLE_RATE, dtype="<i2").tobytes())
log.info("warm")


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path == "/healthz":
            self._json(200, {"ok": True, "model": "parakeet-tdt-0.6b-v2"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path != "/transcribe":
            self._json(404, {"error": "not found"})
            return
        n = int(self.headers.get("Content-Length", "0"))
        if n <= 0 or n > MAX_BYTES or n % 2:
            self._json(400, {"error": "bad length"})
            return
        pcm = self.rfile.read(n)
        try:
            text, audio_s, asr_s = transcribe(pcm)
        except Exception as e:  # message may not carry content; log type only
            log.error("transcribe failed: %s", type(e).__name__)
            self._json(500, {"error": "asr failed"})
            return
        finally:
            del pcm
        log.info("chunk audio_s=%.2f asr_s=%.3f chars=%d", audio_s, asr_s, len(text))
        self._json(200, {"text": text, "audio_s": audio_s, "asr_s": asr_s})

    def log_message(self, fmt, *args):  # silence default access log
        pass


if __name__ == "__main__":
    log.info("listening on %s:%d", HOST, PORT)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
