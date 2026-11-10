"""Venue graph for the Salt Palace + Hyatt Regency: lookup, routing and nearest-POI queries.

The graph lives in ``spark/venue/saltpalace.json`` (nodes + undirected edges, seconds of walking).
Vertical transport is modelled as one node per level per shaft (e.g. ``elevator-255-l1``), so
routing is plain Dijkstra; step-free routing simply drops non-step-free edges and nodes.
"""

from __future__ import annotations

import heapq
import json
import math
import os
import re
from pathlib import Path
from typing import Any

VENUE_DIR = Path(__file__).resolve().parent.parent / "venue"
DEFAULT_PATH = VENUE_DIR / "saltpalace.json"
DEFAULT_VENUE = os.environ.get("TOWER_VENUE", "theshop")  # demo venue; falls back to saltpalace
_VENUE_NAME_RE = re.compile(r"^[a-z0-9-]{1,40}$")
SHAFT_KINDS = ("elevator", "escalator", "stairs")
_SHAFT_RE = re.compile(r"^(?P<shaft>.+)-l(?P<level>\d+)$")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.strip().lower()).strip("-")


def level_label(level: Any) -> str:
    """Display label: 3 -> L3, "L3" -> L3, "ROOF" -> ROOF, "P" -> P."""
    s = norm_level(level).upper()
    return f"L{s}" if s.isdigit() else s


def short_name(name: str) -> str:
    """'Kitchen counter, sodas and food pickup (floor 3)' -> 'Kitchen counter'."""
    s = re.sub(r"\s*\([^)]*\)", "", name).strip()
    s = s.split(",")[0].strip()
    s = re.split(r"\s+(?:behind|by the|next to)\s+", s)[0].strip()
    return s or name


def clip_words(text: str, n: int) -> str:
    words = text.split()
    return text if len(words) <= n else " ".join(words[:n])


def level_rank(level: Any) -> float:
    """Order levels for up/down: P/ground < 1 < 2 ... < roof (strings like "L3" don't compare)."""
    s = norm_level(level)
    if s.isdigit():
        return float(s)
    return {"p": 0.0, "g": 0.0, "ground": 0.0, "roof": 1000.0}.get(s, 500.0)


def norm_level(level: Any) -> str:
    """2, "2", "L2", "l2" -> "2"; "Roof" -> "roof"."""
    s = str(level).strip().lower()
    return s[1:] if re.fullmatch(r"l\d+", s) else s


class Venue:
    def __init__(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]],
                 sign_hints: dict[str, str] | None = None):
        self.sign_hints = {k: v for k, v in (sign_hints or {}).items() if k != "comment"}
        self.nodes: dict[str, dict[str, Any]] = {n["id"]: n for n in nodes}
        self.edges = edges
        self.adj: dict[str, list[tuple[str, int, bool]]] = {nid: [] for nid in self.nodes}
        for e in edges:
            a, b = e["a"], e["b"]
            if a not in self.nodes or b not in self.nodes:
                raise ValueError("edge references unknown node")
            self.adj[a].append((b, int(e["seconds"]), bool(e["step_free"])))
            self.adj[b].append((a, int(e["seconds"]), bool(e["step_free"])))
        # Lookup index: ids win over aliases, aliases over names.
        self._index: dict[str, str] = {}
        for rank in ("name", "aliases", "id"):
            for nid, n in self.nodes.items():
                keys = [n["id"]] if rank == "id" else [n["name"]] if rank == "name" else n.get("aliases", [])
                for k in keys:
                    self._index[k.lower()] = nid
                    self._index[_norm(k)] = nid

    @classmethod
    def load(cls, path: str | Path | None = None) -> Venue:
        with open(path or DEFAULT_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Venue:
        """Accepts both graph shapes: per-node aliases (saltpalace) or a top-level alias map plus
        sign_hints (theshop). Missing building/poi are filled in so every venue looks the same."""
        building = data.get("venue", "venue")
        nodes = [dict(n) for n in data["nodes"]]
        by_id = {n["id"]: n for n in nodes}
        for n in nodes:
            n.setdefault("building", building)
            n["aliases"] = list(n.get("aliases", []))
            if n["kind"] in SHAFT_KINDS and "shaft" not in n:
                parts = n["id"].split("-")
                lvl = norm_level(n["level"])
                n["shaft"] = "-".join(p for p in parts if norm_level(p) != lvl) if len(parts) > 2 else None
            if n["kind"] == "poi" and not n.get("poi"):
                n["poi"] = n["id"].rsplit("-", 1)[-1]  # shop-l3-restroom -> restroom
        for alias, nid in (data.get("aliases") or {}).items():
            if nid in by_id:
                by_id[nid]["aliases"].append(alias)
        return cls(nodes, data["edges"], data.get("sign_hints"))

    # ------------------------------------------------------------------ lookup
    def resolve(self, id_or_alias: str) -> str:
        if not isinstance(id_or_alias, str):
            raise KeyError("unknown venue location")
        key = id_or_alias.strip().lower()
        nid = self._index.get(key) or self._index.get(_norm(key))
        if nid is None:
            raise KeyError("unknown venue location")
        return nid

    def shaft_of(self, nid: str) -> str | None:
        n = self.nodes[nid]
        if n["kind"] not in SHAFT_KINDS:
            return None
        if n.get("shaft"):
            return n["shaft"]
        m = _SHAFT_RE.match(nid)
        return m.group("shaft") if m else nid

    # ----------------------------------------------------------------- routing
    def _dijkstra(self, src: str, step_free: bool) -> tuple[dict[str, int], dict[str, str]]:
        dist: dict[str, int] = {src: 0}
        prev: dict[str, str] = {}
        heap: list[tuple[int, int, str]] = [(0, 0, src)]
        counter = 1
        while heap:
            d, _, u = heapq.heappop(heap)
            if d > dist.get(u, 1 << 60):
                continue
            for v, secs, sf in self.adj[u]:
                if step_free and (not sf or not self.nodes[v]["step_free_access"]):
                    continue
                nd = d + secs
                if nd < dist.get(v, 1 << 60):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(heap, (nd, counter, v))
                    counter += 1
        return dist, prev

    def _path(self, prev: dict[str, str], src: str, dst: str) -> list[str]:
        path = [dst]
        while path[-1] != src:
            path.append(prev[path[-1]])
        return path[::-1]

    def _edge_secs(self, a: str, b: str, step_free: bool) -> int:
        return min(s for v, s, sf in self.adj[a] if v == b and (sf or not step_free))

    def _compress(self, path: list[str], step_free: bool) -> tuple[list[str], dict[tuple[str, str], int]]:
        """Drop corridor waypoints from a path for step text; seconds are summed across them."""
        cp, seg, acc, via = [path[0]], {}, 0, []
        self._via: dict[tuple[str, str], str] = {}
        for a, b in zip(path, path[1:], strict=False):
            acc += self._edge_secs(a, b, step_free)
            if self.nodes[b]["kind"] == "corridor":
                via.append(self.nodes[b]["name"])
            if self.nodes[b]["kind"] != "corridor" or b == path[-1]:
                seg[(cp[-1], b)] = acc
                if via:
                    self._via[(cp[-1], b)] = max(set(via), key=via.count)
                cp.append(b)
                acc, via = 0, []
        return cp, seg

    def _steps(self, path: list[str], step_free: bool) -> list[dict[str, Any]]:
        path, seg = self._compress(path, step_free)
        steps: list[dict[str, Any]] = []
        i = 0
        while i < len(path) - 1:
            a, b = path[i], path[i + 1]
            sa, sb = self.shaft_of(a), self.shaft_of(b)
            if sa and sa == sb:
                # Collapse consecutive moves within one shaft into a single step.
                j, secs = i, 0
                while j < len(path) - 1 and self.shaft_of(path[j + 1]) == sa:
                    secs += seg[(path[j], path[j + 1])]
                    j += 1
                start, end = self.nodes[path[i]], self.nodes[path[j]]
                kind = start["kind"]
                if kind == "elevator":
                    text = (f"Take the elevator from Level {norm_level(start['level']).upper()} to "
                            f"Level {norm_level(end['level']).upper()} ({secs} s)")
                else:
                    direction = "up" if level_rank(end["level"]) > level_rank(start["level"]) else "down"
                    to_level = norm_level(end["level"]).upper()
                    text = f"Take the {kind} {direction} to Level {to_level} ({secs} s)"
                up = level_rank(end["level"]) > level_rank(start["level"])
                steps.append({"text": text, "level": end["level"], "seconds": secs, "node": path[j],
                              "from_node": path[i], "kind": kind, "turn": "up" if up else "down"})
                i = j
                continue
            secs = seg[(a, b)]
            na, nb = self.nodes[a], self.nodes[b]
            if nb["kind"] in SHAFT_KINDS:
                label = nb["name"].split(" (Level")[0]
                text = f"Walk to the {label} ({secs} s)"
            elif getattr(self, "_via", {}).get((a, b)):
                text = f"Walk along the {self._via[(a, b)]} to {nb['name']} ({secs} s)"
            elif na["kind"] == "foyer":
                text = f"Walk along {na['name']} to {nb['name']} ({secs} s)"
            elif na["kind"] in SHAFT_KINDS:
                text = f"Exit into {nb['name']} ({secs} s)" if nb["kind"] == "foyer" else \
                    f"Walk to {nb['name']} ({secs} s)"
            else:
                text = f"Walk from {na['name']} to {nb['name']} ({secs} s)"
            steps.append({"text": text, "level": nb["level"], "seconds": secs, "node": b,
                          "from_node": a, "kind": "walk"})
            i += 1
        return self._guidance(steps, path[-1])

    # ------------------------------------------------------------ turn-by-turn
    def _xy(self, nid: str) -> tuple[float, float]:
        """Plane coordinates with y pointing north (image % coords flip y; aspect-corrected)."""
        pct = getattr(self, "pct", None) or {}
        if nid in pct:
            return pct[nid][0], -pct[nid][1] * 0.813
        n = self.nodes[nid]
        return float(n["x"]), float(n["y"])

    def _guidance(self, steps: list[dict[str, Any]], dst: str) -> list[dict[str, Any]]:
        """Add kind/turn/title/detail/short names per step, plus a final "arrive" step."""
        prev_heading = None
        for st in steps:
            st["short_from"] = short_name(self.nodes[st["from_node"]]["name"])
            st["short_to"] = short_name(self.nodes[st["node"]]["name"])
            st["detail"] = re.sub(r"\s*\(\d+ s\)$", "", st["text"])
            lvl = level_label(self.nodes[st["node"]]["level"])
            if st["kind"] == "walk":
                (x1, y1), (x2, y2) = self._xy(st["from_node"]), self._xy(st["node"])
                same = (x1, y1) == (x2, y2)
                heading = prev_heading if same else math.degrees(math.atan2(y2 - y1, x2 - x1))
                turn = "straight"
                if prev_heading is not None and heading is not None:
                    delta = (heading - prev_heading + 180) % 360 - 180
                    if abs(delta) >= 35:
                        turn = "left" if delta > 0 else "right"
                st["turn"] = turn
                verb = {"straight": "Continue to", "left": "Turn left to", "right": "Turn right to"}[turn]
                st["title"] = clip_words(f"{verb} {st['short_to']}", 7)
                prev_heading = heading
            else:
                prev_heading = None  # new floor: next walk starts fresh
                if st["kind"] == "elevator":
                    st["title"] = f"Elevator to Level {lvl}"
                else:
                    st["title"] = f"Take the {st['kind']} {st['turn']} to Level {lvl}"
        if steps or dst:
            n = self.nodes[dst]
            steps.append({"text": f"You've arrived at {n['name']}", "kind": "arrive", "turn": "straight",
                          "title": "You've arrived", "detail": n["name"], "seconds": 0, "level": n["level"],
                          "node": dst, "from_node": dst, "short_from": short_name(n["name"]),
                          "short_to": short_name(n["name"])})
        return steps

    def _route_from(self, src: str, dst: str, prev: dict[str, str], dist: dict[str, int],
                    step_free: bool) -> dict[str, Any]:
        path = self._path(prev, src, dst)
        return {"from": src, "to": dst, "step_free": step_free, "total_seconds": int(dist[dst]),
                "path": path, "steps": self._steps(path, step_free)}

    def route(self, frm: str, to: str, step_free: bool = False) -> dict[str, Any]:
        src, dst = self.resolve(frm), self.resolve(to)
        if step_free and not (self.nodes[src]["step_free_access"] and self.nodes[dst]["step_free_access"]):
            raise ValueError("no step-free route")
        dist, prev = self._dijkstra(src, step_free)
        if dst not in dist:
            raise ValueError("no route")
        return self._route_from(src, dst, prev, dist, step_free)

    def nearest(self, poi_kind: str, frm: str, step_free: bool = False) -> dict[str, Any]:
        src = self.resolve(frm)
        want = _norm(poi_kind)
        candidates = {nid for nid, n in self.nodes.items() if n.get("poi") and _norm(n["poi"]) == want}
        if not candidates:
            raise KeyError("unknown point-of-interest kind")
        if step_free and not self.nodes[src]["step_free_access"]:
            raise ValueError("no step-free route")
        dist, prev = self._dijkstra(src, step_free)
        reachable = [c for c in candidates if c in dist]
        if not reachable:
            raise ValueError("no reachable point of interest")
        best = min(reachable, key=lambda c: (dist[c], c))
        return {"node": best, "name": self.nodes[best]["name"], "total_seconds": int(dist[best]),
                "route": self._route_from(src, best, prev, dist, step_free)}

    def nearest_on_level(self, poi_prefix: str, level: Any, frm: str | None = None,
                         kinds: tuple[str, ...] = ()) -> str | None:
        """Closest node on one level whose poi starts with poi_prefix (or whose kind is in kinds)."""
        lvl = norm_level(level)
        cands = [nid for nid, n in self.nodes.items() if norm_level(n["level"]) == lvl and (
            (poi_prefix and (n.get("poi") or "").startswith(poi_prefix)) or n["kind"] in kinds)]
        if not cands:
            return None
        if frm:
            try:
                dist, _ = self._dijkstra(self.resolve(frm), False)
            except KeyError:
                dist = {}
            reachable = [c for c in cands if c in dist]
            if reachable:
                return min(reachable, key=lambda c: (dist[c], c))
        return sorted(cands)[0]

    # ------------------------------------------------------------------ export
    def geo_docs(self) -> list[dict[str, Any]]:
        return [{"id": n["id"], "name": n["name"], "building": n["building"], "level": n["level"],
                 "kind": n["kind"], "poi": n.get("poi"), "step_free_access": n["step_free_access"],
                 "aliases": list(n.get("aliases", [])),
                 "location": {"lat": n["y"] / 1000, "lon": n["x"] / 1000}}
                for n in self.nodes.values()]

    def public_nodes(self) -> list[dict[str, Any]]:
        out = [{"id": n["id"], "name": n["name"], "level": n["level"], "kind": n["kind"],
                "building": n["building"], "poi": n.get("poi"), "aliases": list(n.get("aliases", []))}
               for n in self.nodes.values() if n["kind"] != "corridor"]
        return sorted(out, key=lambda n: (n["building"], n["level"], n["name"].lower()))

    def graph(self) -> dict[str, Any]:
        """Whole graph for drawing a map: nodes with coordinates + undirected edges."""
        nodes = [{"id": n["id"], "name": n["name"], "short": n.get("short"), "level": n["level"],
                  "kind": n["kind"],
                  "building": n.get("building"), "poi": n.get("poi"), "x": n["x"], "y": n["y"],
                  "step_free_access": n["step_free_access"], "aliases": list(n.get("aliases", []))}
                 for n in self.nodes.values()]
        edges = [{"a": e["a"], "b": e["b"], "seconds": int(e["seconds"]), "step_free": bool(e["step_free"])}
                 for e in self.edges]
        return {"nodes": nodes, "edges": edges}


class Venues:
    """All graphs in spark/venue/*.json, loaded on first use; ?venue=<name> picks one."""

    def __init__(self, directory: str | Path = VENUE_DIR, default: str = DEFAULT_VENUE):
        self.dir = Path(directory)
        self._cache: dict[str, Venue] = {}
        self.default = default if (self.dir / f"{default}.json").exists() else "saltpalace"

    def names(self) -> list[str]:
        return sorted(p.stem for p in self.dir.glob("*.json") if not p.stem.endswith(("_pins", "_corridors")))

    def get(self, name: str | None = None) -> Venue:
        name = name or self.default
        path = self.dir / f"{name}.json"
        if not _VENUE_NAME_RE.match(name) or not path.exists():
            raise KeyError("unknown venue")
        if name not in self._cache:
            corr, pins = self.dir / f"{name}_corridors.json", self.dir / f"{name}_pins.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            pct: dict[str, list[float]] = {}
            if corr.exists() and pins.exists():
                data, pct = apply_corridors(data, json.loads(corr.read_text(encoding="utf-8")),
                                            json.loads(pins.read_text(encoding="utf-8"))["pins"])
            v = Venue.from_dict(data)
            v.pct = pct
            self._cache[name] = v
        return self._cache[name]

    def name_of(self, name: str | None) -> str:
        return name or self.default


def apply_corridors(data: dict[str, Any], corr: dict[str, Any], pins: dict[str, list[float]]
                    ) -> tuple[dict[str, Any], dict[str, list[float]]]:
    """Replace the venue's walking edges with a corridor network traced on the venue map image.

    Pinned rooms snap to the nearest corridor waypoint on their level; Hyatt (off-image) keeps its
    own edges; other unpinned nodes become leaves on their nearest pinned node, so they can't be
    shortcuts. Returns (graph data, image coordinates {node id: [x%, y%]})."""
    aspect, k = corr.get("aspect", 1.0), corr.get("m_per_pct", 1.2) * corr.get("s_per_m", 1.3)
    pins = {**pins, **corr.get("extra_pins", {})}
    nodes = {n["id"]: dict(n) for n in data["nodes"]}

    def dist(p, q):
        return math.hypot(p[0] - q[0], (p[1] - q[1]) * aspect)

    def secs(p, q):
        return max(3, round(dist(p, q) * k))

    pct: dict[str, list[float]] = {nid: list(xy) for nid, xy in pins.items() if nid in nodes}
    wp_at: dict[tuple, str] = {}
    edges: list[dict[str, Any]] = []
    for c in corr["corridors"]:
        pts: list[list[float]] = []
        for a, b in zip(c["points"], c["points"][1:], strict=False):
            n = max(1, math.ceil(dist(a, b) / 3.0))
            pts += [[a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n] for i in range(n)]
        pts.append(c["points"][-1])
        prev = None
        for i, p in enumerate(pts):
            key = (c["level"], round(p[0], 2), round(p[1], 2))
            wid = wp_at.get(key)
            if wid is None:
                wid = wp_at[key] = f"wp-{c['id']}-{i}"
                nodes[wid] = {"id": wid, "name": c["name"], "building": "salt-palace",
                              "level": c["level"], "kind": "corridor", "x": p[0], "y": p[1],
                              "step_free_access": True, "aliases": []}
                pct[wid] = p
            if prev:
                edges.append({"a": prev, "b": wid, "seconds": secs(pct[prev], p), "step_free": True})
            prev = wid
    by_level: dict[Any, list[str]] = {}
    for wid in wp_at.values():
        by_level.setdefault(nodes[wid]["level"], []).append(wid)

    def nearest_wp(level, p):
        return min(by_level.get(level, []), key=lambda w: dist(pct[w], p), default=None)

    for vt in corr.get("verticals", []):
        prev = None
        for st in vt["stops"]:
            sid = f"{vt['id']}-l{st['level']}"
            nodes[sid] = {"id": sid, "name": f"{vt['name']} (Level {st['level']})", "building": "salt-palace",
                          "level": st["level"], "kind": vt["kind"], "shaft": vt["id"], "x": st["at"][0],
                          "y": st["at"][1], "step_free_access": bool(vt["step_free"]), "aliases": []}
            pct[sid] = st["at"]
            w = nearest_wp(st["level"], st["at"])
            if w:
                edges.append({"a": sid, "b": w, "seconds": secs(st["at"], pct[w]), "step_free": True})
            if prev:
                edges.append({"a": prev, "b": sid, "seconds": int(vt["seconds_per_level"]),
                              "step_free": bool(vt["step_free"])})
            prev = sid
    for nid, xy in pins.items():
        if nid in nodes:
            w = nearest_wp(nodes[nid]["level"], xy)
            if w:
                edges.append({"a": nid, "b": w, "seconds": secs(xy, pct[w]), "step_free": True})
    # Hyatt and other non-Salt-Palace edges stay; unpinned Salt Palace nodes hang off a pinned node.
    old = data["edges"]
    sp = {nid for nid, n in nodes.items() if n.get("building") == "salt-palace"}
    edges += [e for e in old if e["a"] not in sp and e["b"] not in sp]
    adj: dict[str, list[tuple[str, int]]] = {}
    for e in old:
        adj.setdefault(e["a"], []).append((e["b"], int(e["seconds"])))
        adj.setdefault(e["b"], []).append((e["a"], int(e["seconds"])))
    linked = {e["a"] for e in edges} | {e["b"] for e in edges}
    for nid in [n for n in sp if n not in linked and n in adj]:
        seen, frontier = {nid: 0}, [(0, nid)]
        while frontier:
            d, u = heapq.heappop(frontier)
            if u != nid and u in pct and nodes[u]["kind"] != "corridor":
                edges.append({"a": nid, "b": u, "seconds": max(3, d),
                              "step_free": bool(nodes[nid].get("step_free_access", True))})
                break
            for v, w in adj.get(u, []):
                if v not in seen or seen[v] > d + w:
                    seen[v] = d + w
                    heapq.heappush(frontier, (d + w, v))
    return {**data, "nodes": list(nodes.values()), "edges": edges}, pct
