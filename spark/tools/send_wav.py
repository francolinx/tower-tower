"""Stream a 16 kHz mono WAV to tower-core in real time and print caption latency.

    python tools/send_wav.py ~/cnh-prep/asr_test_16k.wav --room test [--url ws://127.0.0.1:8088]
"""

import argparse
import asyncio
import json
import statistics
import time

import soundfile as sf
import websockets


async def main(path: str, room: str, url: str, frame_ms: int) -> None:
    audio, sr = sf.read(path, dtype="int16")
    assert sr == 16000 and audio.ndim == 1, "need 16 kHz mono"
    latencies: list[float] = []

    async def listen():
        async with websockets.connect(f"{url}/ws/captions?room={room}") as ws:
            async for msg in ws:
                m = json.loads(msg)
                latencies.append(m["latency_s"])
                print(f"[{m['t_start']:5.1f}-{m['t_end']:5.1f}] {m['latency_s']*1000:6.0f} ms  {m['text']}")

    listener = asyncio.create_task(listen())
    await asyncio.sleep(0.3)
    step = sr * frame_ms // 1000
    async with websockets.connect(f"{url}/ws/audio?room={room}") as ws:
        t0 = time.monotonic()
        for i in range(0, len(audio), step):
            await ws.send(audio[i : i + step].tobytes())
            target = t0 + (i + step) / sr
            await asyncio.sleep(max(0.0, target - time.monotonic()))
        await asyncio.sleep(1.5)
    listener.cancel()
    if latencies:
        q = sorted(latencies)
        print(
            f"\nchunks={len(q)} p50={statistics.median(q)*1000:.0f} ms "
            f"p95={q[int(0.95 * (len(q) - 1))]*1000:.0f} ms max={q[-1]*1000:.0f} ms"
        )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("wav")
    p.add_argument("--room", default="test")
    p.add_argument("--url", default="ws://127.0.0.1:8088")
    p.add_argument("--frame-ms", type=int, default=100)
    a = p.parse_args()
    asyncio.run(main(a.wav, a.room, a.url, a.frame_ms))
