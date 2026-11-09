"""Venue graph for the Salt Palace + Hyatt Regency: lookup, routing and nearest-POI queries.

The graph lives in ``spark/venue/saltpalace.json`` (nodes + undirected edges, seconds of walking).
Vertical transport is modelled as one node per level per shaft (e.g. ``elevator-255-l1``), so
routing is plain Dijkstra; step-free routing simply drops non-step-free edges and nodes.
"""

from __future__ import annotations

import heapq
import json
import re
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "venue" / "saltpalace.json"
SHAFT_KINDS = ("elevator", "escalator", "stairs")
_SHAFT_RE = re.compile(r"^(?P<shaft>.+)-l(?P<level>\d+)$")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.strip().lower()).strip("-")


class Venue:
    def __init__(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]):
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
        return cls(data["nodes"], data["edges"])

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

    def _steps(self, path: list[str], step_free: bool) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        i = 0
        while i < len(path) - 1:
            a, b = path[i], path[i + 1]
            sa, sb = self.shaft_of(a), self.shaft_of(b)
            if sa and sa == sb:
                # Collapse consecutive moves within one shaft into a single step.
                j, secs = i, 0
                while j < len(path) - 1 and self.shaft_of(path[j + 1]) == sa:
                    secs += self._edge_secs(path[j], path[j + 1], step_free)
                    j += 1
                start, end = self.nodes[path[i]], self.nodes[path[j]]
                kind = start["kind"]
                if kind == "elevator":
                    text = f"Take the elevator from Level {start['level']} to Level {end['level']} ({secs} s)"
                else:
                    direction = "up" if end["level"] > start["level"] else "down"
                    text = f"Take the {kind} {direction} to Level {end['level']} ({secs} s)"
                steps.append({"text": text, "level": end["level"], "seconds": secs, "node": path[j]})
                i = j
                continue
            secs = self._edge_secs(a, b, step_free)
            na, nb = self.nodes[a], self.nodes[b]
            if nb["kind"] in SHAFT_KINDS:
                label = nb["name"].split(" (Level")[0]
                text = f"Walk to the {label} ({secs} s)"
            elif na["kind"] == "foyer":
                text = f"Walk along {na['name']} to {nb['name']} ({secs} s)"
            elif na["kind"] in SHAFT_KINDS:
                text = f"Exit into {nb['name']} ({secs} s)" if nb["kind"] == "foyer" else \
                    f"Walk to {nb['name']} ({secs} s)"
            else:
                text = f"Walk from {na['name']} to {nb['name']} ({secs} s)"
            steps.append({"text": text, "level": nb["level"], "seconds": secs, "node": b})
            i += 1
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
               for n in self.nodes.values()]
        return sorted(out, key=lambda n: (n["building"], n["level"], n["name"].lower()))
