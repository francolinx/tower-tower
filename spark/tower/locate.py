"""Sign-photo locator: Qwen3-VL (local vLLM on 127.0.0.1:8001) reads the room sign, we fuzzy-match it
against venue node names.

Privacy: the image is held in memory for one request and dropped. It is never written to disk,
logged or put on spans (bytes + latency only). The prompt asks only for the sign's text; there is
no face detection or recognition anywhere.
"""

import base64
import difflib
import json
import os
import re

import httpx

VLM_URL = os.environ.get("VLM_URL", "http://127.0.0.1:8001")
VLM_MODEL = os.environ.get("VLM_MODEL", "qwen3-vl")
MAX_IMAGE_BYTES = 2 * 1024 * 1024
PROMPT = (
    'Return only JSON {"sign": "<room number or room name on the sign, or null>"}. '
    "Read only the printed room sign. Ignore people."
)


def _norm(s: str) -> str:
    s = s.lower().replace("&", " ")
    s = re.sub(r"\blevel\s*\d+\b", " ", s)
    s = re.sub(r"\b(room|hall|level|salt palace|hyatt regency|ballroom)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def parse_sign(content: str) -> str | None:
    """Pull the "sign" value out of the model's reply (tolerates code fences / extra text)."""
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        return None
    try:
        val = json.loads(m.group(0)).get("sign")
    except (json.JSONDecodeError, AttributeError):
        return None
    if not val or str(val).strip().lower() in ("null", "none", ""):
        return None
    return str(val).strip()


def match_sign(sign: str, nodes: list[dict]) -> tuple[str | None, float]:
    """Best venue node for the sign text -> (node_id, confidence 0..1)."""
    target = _norm(sign)
    if not target:
        return None, 0.0

    scores = {}
    has_digits = any(char.isdigit() for char in target)
    for n in nodes:
        for cand in [n["id"], n.get("name", ""), *n.get("aliases", [])]:
            c = _norm(cand)
            if not c:
                continue
            if c == target:
                score = 1.0
            elif not has_digits and len(target) >= 6:
                score = difflib.SequenceMatcher(None, target, c).ratio()
            else:
                continue
            scores[n["id"]] = max(scores.get(n["id"], 0.0), score)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked:
        return None, 0.0
    best_id, best = ranked[0]
    confidence = round(best, 2)
    if best < 0.9 or (len(ranked) > 1 and best - ranked[1][1] <= 0.05):
        return None, confidence
    return best_id, confidence


async def read_sign(client: httpx.AsyncClient, image: bytes, mime: str = "image/jpeg") -> str | None:
    b64 = base64.b64encode(image).decode()
    body = {
        "model": VLM_MODEL,
        "temperature": 0,
        "max_tokens": 40,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": PROMPT},
            ],
        }],
    }
    r = await client.post(f"{VLM_URL}/v1/chat/completions", json=body, timeout=20.0)
    r.raise_for_status()
    return parse_sign(r.json()["choices"][0]["message"]["content"])
