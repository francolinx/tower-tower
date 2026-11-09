"""Download photos sent to the TOWER bot, for testing the sign locator on real venue shots.

    set -a; source ~/cnh-prep/.env; set +a
    python tools/pull_telegram_photos.py [--out ~/cnh-prep/data/theshop_photos] [--ack]

Saves each photo as <out>/<caption-slug>.jpg (0600, outside the repo). Only photos from chats that
already ran /start (in ~/.tower/chats.json) are kept. Delete the folder when testing is done.

Telegram lets one getUpdates reader at a time: run tower-core with TOWER_TG_POLL=0 while pulling,
or it will consume the photo updates first. Without --ack the updates stay queued for tower-core.
The bot token is never printed; httpx request logging is silenced because its URLs contain it.
"""

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

CHATS_FILE = Path.home() / ".tower" / "chats.json"
MAX_BYTES = 2 * 1024 * 1024  # the locator's limit


def slug(caption: str | None, fallback: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (caption or "").lower()).strip("-")[:60]
    return s or fallback


def known_chats() -> set[int]:
    try:
        return {int(v) for v in json.loads(CHATS_FILE.read_text()).values()}
    except (OSError, ValueError):
        return set()


def best_photo(sizes: list[dict]) -> dict | None:
    """Largest size that fits the locator's 2 MB limit."""
    fits = [p for p in sizes if p.get("file_size", 0) <= MAX_BYTES]
    return max(fits, key=lambda p: p.get("width", 0) * p.get("height", 0)) if fits else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path.home() / "cnh-prep" / "data" / "theshop_photos"))
    ap.add_argument("--ack", action="store_true", help="confirm the updates so they aren't returned again")
    a = ap.parse_args()
    token = os.environ.get("TG_TOKEN")
    if not token:
        print("TG_TOKEN not set (source the env file)", file=sys.stderr)
        return 1
    api, files = f"https://api.telegram.org/bot{token}", f"https://api.telegram.org/file/bot{token}"
    out = Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    chats = known_chats()
    try:
        return pull(api, files, out, chats, a.ack)
    except httpx.HTTPError as e:
        # never print the exception text: its request URL contains the bot token
        status = getattr(getattr(e, "response", None), "status_code", None)
        print(f"telegram request failed: {type(e).__name__} status={status}", file=sys.stderr)
        return 3


def pull(api: str, files: str, out: Path, chats: set[int], ack: bool) -> int:
    with httpx.Client(timeout=30) as c:
        r = c.get(f"{api}/getUpdates", params={"timeout": 0, "allowed_updates": '["message"]'})
        if r.status_code == 409:
            print("another getUpdates reader is active: restart tower-core with TOWER_TG_POLL=0",
                  file=sys.stderr)
            return 2
        r.raise_for_status()
        updates = r.json().get("result", [])
        saved = skipped = 0
        for u in updates:
            msg = u.get("message") or {}
            photo = best_photo(msg.get("photo") or [])
            if not photo:
                continue
            if msg.get("chat", {}).get("id") not in chats:
                skipped += 1
                continue
            path = c.get(f"{api}/getFile", params={"file_id": photo["file_id"]}).raise_for_status()
            data = c.get(f"{files}/{path.json()['result']['file_path']}").raise_for_status().content
            name = slug(msg.get("caption"), f"photo-{msg.get('message_id')}")
            dest, n = out / f"{name}.jpg", 2
            while dest.exists() and dest.read_bytes() != data:
                dest, n = out / f"{name}-{n}.jpg", n + 1
            if dest.exists():  # already pulled on an earlier run
                continue
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            saved += 1
            print(f"saved photo {saved} ({len(data) // 1024} KB)")  # caption-derived names stay off stdout
        if ack and updates:
            c.get(f"{api}/getUpdates", params={"offset": updates[-1]["update_id"] + 1, "timeout": 0})
    print(f"updates={len(updates)} saved={saved} skipped_unknown_chat={skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
