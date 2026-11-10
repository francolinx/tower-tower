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
LANDMARKS = (
    "skeleton", "communal table", "kitchen counter", "bar stools", "fridge", "blue wall", "yellow stairs",
    "stairs", "elevator", "projector", "screen", "stage", "reception desk", "glass meeting room",
    "phone booth", "rooftop", "terrace", "outdoor", "Dash0 banner", "Radar banner", "Sonar banner",
    "Elastic banner",
)
PROMPT = (
    'Return only JSON {"sign": "<room number or room name on a printed sign, or null>", '
    '"text": "<other printed text on signs or banners, or null>", '
    '"landmarks": [<zero or more of: ' + ", ".join(f'"{w}"' for w in LANDMARKS) + '>]}. '
    "Only list landmarks you can clearly see. Read printed signs and objects only. Ignore people."
)
# landmark -> node id, or "@stairs"/"@elevator" = that shaft on the current level
LANDMARK_TARGETS = {
    "skeleton": "shop-l3-skeleton", "yellow stairs": "@stairs", "stairs": "@stairs", "elevator": "@elevator",
    "kitchen counter": "shop-l3-kitchen", "bar stools": "shop-l3-kitchen", "projector": "shop-l3-stage",
    "screen": "shop-l3-stage", "rooftop": "shop-roof-door", "terrace": "shop-roof-door",
    "outdoor": "shop-roof-door", "phone booth": "shop-l3-nw", "glass meeting room": "shop-l3-glassroom",
}
# Banner text -> venue node (sponsor tables at the demo venue). Earliest mention in the text wins.
# Targets are tried as node ids, then as venue aliases (theshop: "dash0" -> shop-l3-dash0-table).
BANNERS = (
    (re.compile(r"dash\s?0", re.I), ("dash0-table", "dash0")),
    (re.compile(r"\bradar\b", re.I), ("radar-table", "radar")),
    (re.compile(r"\b(sonar|gitar)\b", re.I), ("sonar-table", "sonar")),
    (re.compile(r"\belastic", re.I), ("elastic-table", "elastic")),
)


def _resolve_any(venue, names) -> str | None:
    for name in names:
        if name in venue.nodes:
            return name
        try:
            return venue.resolve(name)
        except KeyError:
            continue
    return None


def _hint_rules(venue):
    """The venue file's own sign_hints (words only; floor digits and "nearest:" are handled below)."""
    for word, target in getattr(venue, "sign_hints", {}).items():
        if len(word) > 1 and not target.startswith("nearest:") and target in venue.nodes:
            yield re.compile(rf"\b{re.escape(word)}", re.I), (target,)
RESTROOM_RE = re.compile(r"restroom|toilet|washroom|\bwc\b|🚻", re.I)
FLOOR_RES = (
    re.compile(r"\b(?:floor|level|fl\.?)\s*(\d{1,2})\b", re.I),
    re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+floor\b", re.I),
)
LIFT_RE = re.compile(r"elevator|lift", re.I)


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


def parse_landmarks(content: str) -> list[str]:
    """Landmarks from the reply, kept only if they're on our list (model output is untrusted)."""
    m = re.search(r"\{.*\}", content, re.S)
    try:
        items = json.loads(m.group(0)).get("landmarks") if m else None
    except (json.JSONDecodeError, AttributeError):
        return []
    allowed = {w.lower(): w for w in LANDMARKS}
    return [allowed[str(x).strip().lower()] for x in (items or []) if str(x).strip().lower() in allowed]


def match_landmarks(landmarks: list[str], venue, frm: str | None = None) -> tuple[str | None, str | None]:
    """First landmark that resolves in this venue -> (node, landmark)."""
    level = None
    if frm:
        try:
            level = venue.nodes[venue.resolve(frm)]["level"]
        except KeyError:
            level = None
    for lm in landmarks:
        target = LANDMARK_TARGETS.get(lm.lower())
        if target in ("@stairs", "@elevator"):
            node = venue.nearest_on_level("", level, frm, kinds=(target[1:],)) if level is not None else None
        elif target and target in venue.nodes:
            node = target
        else:
            base = re.sub(r"\s+(banner|desk|counter)$", "", lm, flags=re.I)
            node = _resolve_any(venue, [lm, base, base.lower()])
            if node is None:
                node = next((t for w, t in getattr(venue, "sign_hints", {}).items()
                             if w.lower() == base.lower() and t in venue.nodes), None)
        if node:
            return node, lm
    return None, None


def parse_reading(content: str) -> tuple[str | None, str | None]:
    """(sign, text) from the model's JSON reply; either may be None."""
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        return None, None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None, None
    if not isinstance(d, dict):
        return None, None

    def clean(v):
        return None if not v or str(v).strip().lower() in ("null", "none", "") else str(v).strip()

    return clean(d.get("sign")), clean(d.get("text"))


def floor_level(text: str) -> str | None:
    """'Floor 3' / '3rd floor' / an elevator panel '3' / 'Roof' near Floor or elevator -> level."""
    for rx in FLOOR_RES:
        m = rx.search(text)
        if m:
            return m.group(1)
    near_lift = LIFT_RE.search(text) or re.search(r"\bfloor\b", text, re.I)
    if near_lift and re.search(r"\broof\b", text, re.I):
        return "roof"
    if LIFT_RE.search(text):
        m = re.search(r"\b(\d{1,2})\b", text)
        if m:
            return m.group(1)
    return None


def match_banner(text: str, venue, frm: str | None = None) -> tuple[str | None, float, str | None]:
    """Banner/sign rules -> (node, confidence, rule). Rules: banner, restroom, floor."""
    if not text:
        return None, 0.0, None
    hits = []
    for rx, targets in (*_hint_rules(venue), *BANNERS):
        m = rx.search(text)
        node = _resolve_any(venue, targets) if m else None
        if node:
            hits.append((m.start(), node))
    if hits:
        return min(hits)[1], 0.95, "banner"
    level = None
    if frm:
        try:
            level = venue.nodes[venue.resolve(frm)]["level"]
        except KeyError:
            level = None
    if RESTROOM_RE.search(text) and level is not None:
        node = venue.nearest_on_level("restroom", level, frm)
        if node:
            return node, 0.9, "restroom"
    lvl = floor_level(text)
    if lvl is not None:
        node = venue.nearest_on_level("", lvl, frm, kinds=("elevator",))
        if node:
            return node, 0.9, "floor"
    return None, 0.0, None


async def read_sign(
    client: httpx.AsyncClient, image: bytes, mime: str = "image/jpeg"
) -> tuple[str | None, str | None, list[str]]:
    b64 = base64.b64encode(image).decode()
    body = {
        "model": VLM_MODEL,
        "temperature": 0,
        "max_tokens": 160,
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
    content = r.json()["choices"][0]["message"]["content"]
    return (*parse_reading(content), parse_landmarks(content))
