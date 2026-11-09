"""Sliding-window chunking of a PCM16 stream and de-duplication of overlapping transcripts."""

import re

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2


class Windower:
    """Accumulates PCM16 bytes and yields (window_bytes, t_start, t_end) windows.

    window_s=1.5, overlap_s=0.5 -> a new 1.5 s window every 1.0 s of audio.
    t_start/t_end are seconds from the start of this stream.
    """

    def __init__(self, window_s: float = 1.5, overlap_s: float = 0.5):
        self.win = int(window_s * SAMPLE_RATE) * BYTES_PER_SAMPLE
        self.hop = int((window_s - overlap_s) * SAMPLE_RATE) * BYTES_PER_SAMPLE
        self.buf = bytearray()
        self.offset_bytes = 0  # stream position of buf[0]

    def feed(self, data: bytes):
        self.buf.extend(data)
        while len(self.buf) >= self.win:
            window = bytes(self.buf[: self.win])
            t_start = self.offset_bytes / (SAMPLE_RATE * BYTES_PER_SAMPLE)
            t_end = t_start + self.win / (SAMPLE_RATE * BYTES_PER_SAMPLE)
            del self.buf[: self.hop]
            self.offset_bytes += self.hop
            yield window, t_start, t_end


_norm = re.compile(r"[^\w']+")


def _words(s: str) -> list[str]:
    return [w for w in _norm.sub(" ", s.lower()).split() if w]


def merge_overlap(prev: str, new: str, max_overlap: int = 6) -> str:
    """Return the part of `new` that isn't a repeat of the tail of `prev`.

    The 0.5 s overlap means the start of a window often repeats the last word or two of the
    previous one. Find the longest suffix of prev (<= max_overlap words) that matches a prefix of
    new (case/punctuation-insensitive) and drop it from new.
    """
    if not prev or not new:
        return new.strip()
    pw, nw_raw = _words(prev), new.split()
    nw = [_norm.sub("", w.lower()) for w in nw_raw]
    best = 0
    for k in range(min(max_overlap, len(pw), len(nw)), 0, -1):
        if pw[-k:] == nw[:k]:
            best = k
            break
    return " ".join(nw_raw[best:]).strip()
