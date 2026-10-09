"""Workflow graph helpers shared by validation and the engine: adjacency, back edges (bounded wait loops), SCCs."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Edge:
    index: int
    src: str
    dst: str
    branch: str | None = None
    condition: dict[str, Any] | None = None


@dataclass
class Graph:
    nodes: dict[str, dict[str, Any]]                     # key -> {key, type, config, label, position}
    edges: list[Edge]
    out_edges: dict[str, list[Edge]] = field(default_factory=lambda: defaultdict(list))
    in_edges: dict[str, list[Edge]] = field(default_factory=lambda: defaultdict(list))
    trigger: str | None = None
    back_edges: set[int] = field(default_factory=set)

    @classmethod
    def build(cls, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> Graph:
        nmap = {str(n["key"]): n for n in nodes if n.get("key")}
        es = [Edge(i, str(e.get("from") or e.get("from_node_key") or ""), str(e.get("to") or e.get("to_node_key") or ""),
                   e.get("branch") or None, e.get("condition")) for i, e in enumerate(edges)]
        g = cls(nodes=nmap, edges=es)
        for e in es:
            if e.src in nmap and e.dst in nmap:
                g.out_edges[e.src].append(e)
                g.in_edges[e.dst].append(e)
        triggers = [k for k, n in nmap.items() if str(n.get("type", "")).startswith("trigger.")]
        g.trigger = triggers[0] if len(triggers) == 1 else None
        g._find_back_edges()
        return g

    def _find_back_edges(self) -> None:
        """Iterative DFS from the trigger (then any unvisited node) in key order; an edge to a node on the stack is a
        back edge. Removing back edges leaves a DAG."""
        color: dict[str, int] = {}
        roots = ([self.trigger] if self.trigger else []) + sorted(self.nodes)
        for root in roots:
            if root in color:
                continue
            stack: list[tuple[str, int]] = [(root, 0)]
            color[root] = 1
            while stack:
                node, i = stack[-1]
                outs = sorted(self.out_edges.get(node, []), key=lambda e: (e.dst, e.branch or "", e.index))
                if i < len(outs):
                    stack[-1] = (node, i + 1)
                    e = outs[i]
                    c = color.get(e.dst, 0)
                    if c == 1:
                        self.back_edges.add(e.index)
                    elif c == 0:
                        color[e.dst] = 1
                        stack.append((e.dst, 0))
                else:
                    color[node] = 2
                    stack.pop()

    def forward_in(self, key: str) -> list[Edge]:
        return [e for e in self.in_edges.get(key, []) if e.index not in self.back_edges]

    def forward_out(self, key: str) -> list[Edge]:
        return [e for e in self.out_edges.get(key, []) if e.index not in self.back_edges]

    def reachable(self, start: str | None = None) -> set[str]:
        start = start or self.trigger
        if not start:
            return set()
        seen = {start}
        todo = [start]
        while todo:
            k = todo.pop()
            for e in self.out_edges.get(k, []):
                if e.dst not in seen:
                    seen.add(e.dst)
                    todo.append(e.dst)
        return seen

    def downstream(self, keys: set[str]) -> set[str]:
        """Nodes reachable from ``keys`` via forward edges (excluding ``keys`` unless re-reached)."""
        seen: set[str] = set()
        todo = list(keys)
        while todo:
            k = todo.pop()
            for e in self.forward_out(k):
                if e.dst not in seen and e.dst not in keys:
                    seen.add(e.dst)
                    todo.append(e.dst)
        return seen

    def sccs(self) -> list[set[str]]:
        """Strongly connected components (Tarjan, iterative)."""
        index: dict[str, int] = {}
        low: dict[str, int] = {}
        on: set[str] = set()
        st: list[str] = []
        out: list[set[str]] = []
        counter = 0
        for root in sorted(self.nodes):
            if root in index:
                continue
            work: list[tuple[str, int]] = [(root, 0)]
            while work:
                v, i = work[-1]
                if i == 0:
                    index[v] = low[v] = counter
                    counter += 1
                    st.append(v)
                    on.add(v)
                succ = [e.dst for e in self.out_edges.get(v, [])]
                if i < len(succ):
                    work[-1] = (v, i + 1)
                    w = succ[i]
                    if w not in index:
                        work.append((w, 0))
                    elif w in on:
                        low[v] = min(low[v], index[w])
                    continue
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[v])
                if low[v] == index[v]:
                    comp: set[str] = set()
                    while True:
                        w = st.pop()
                        on.discard(w)
                        comp.add(w)
                        if w == v:
                            break
                    out.append(comp)
        return out

    def cycles(self) -> list[set[str]]:
        """Non-trivial SCCs (size > 1, or a self loop)."""
        res = []
        for comp in self.sccs():
            if len(comp) > 1 or any(e.dst == next(iter(comp)) for e in self.out_edges.get(next(iter(comp)), [])):
                res.append(comp)
        return res

    def loop_body(self, key: str) -> set[str]:
        for comp in self.sccs():
            if key in comp:
                return comp
        return {key}
