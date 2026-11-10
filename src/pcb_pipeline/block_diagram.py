"""Block diagram of the board, drawn from design/spec.yaml for the dashboard.

Everything comes from the spec, nothing is drawn by hand:
- one box per block, placed in columns that follow `connects_to` from the entry blocks
  (the blocks that own a connector with a power input);
- each connector on the board edge, next to the block that owns it (`parts[].block`),
  with the off-board side (`purpose`) outside the frame;
- power lines from the rails (source part's block to each load's block, and from the
  input connector for external rails), communication lines from the buses (controller
  block to each device block), and the remaining `connects_to` links as plain lines.
"""

from __future__ import annotations

import html
from collections import defaultdict

BW, BH = 210, 64          # block box
CW, CH = 64, 30           # connector box
XW, XH = 170, 34          # external box
COL, ROW = 320, 104        # block grid pitch
PAD = 40                  # frame padding
EXT = 60                  # gap between the frame and the external boxes

SIGNAL_DIRS = {"in", "out", "bidir"}
POWER_DIRS = {"power_in", "power_out"}


def _short(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def _columns(blocks: list[dict], entry: set[str]) -> dict[str, int]:
    ids = [b["id"] for b in blocks]
    out = {b["id"]: [c for c in b.get("connects_to", []) if c in ids] for b in blocks}
    col: dict[str, int] = {}
    frontier = [i for i in ids if i in entry] or [i for i in ids if not any(i in v for v in out.values())] or ids[:1]
    for i in frontier:
        col[i] = 0
    while frontier:
        nxt = []
        for i in frontier:
            for j in out[i]:
                if j not in col:
                    col[j] = col[i] + 1
                    nxt.append(j)
        frontier = nxt
    last = max(col.values(), default=0)
    for i in ids:                       # isolated blocks (ESD, test...) go to the last column
        col.setdefault(i, last + (1 if col else 0))
    return col


def block_diagram_svg(spec: dict) -> str:
    blocks = spec.get("blocks", [])
    if not blocks:
        return ""
    parts = {p["id"]: p for p in spec.get("parts", [])}
    block_of = {pid: p.get("block") for pid, p in parts.items()}
    connectors = spec.get("connectors", [])
    rails = spec.get("power_tree", {}).get("rails", [])
    buses = spec.get("buses", [])

    entry = {block_of.get(c.get("part")) for c in connectors
             if any(p.get("direction") == "power_in" for p in c.get("pins", []))}
    col = _columns(blocks, entry)

    # block positions inside the frame
    by_col: dict[int, list[str]] = defaultdict(list)
    for b in blocks:
        by_col[col[b["id"]]].append(b["id"])
    ncol = max(by_col) + 1
    nrow = max(len(v) for v in by_col.values())
    inner_h = nrow * ROW
    pos: dict[str, tuple[float, float]] = {}
    for c, ids in by_col.items():
        top = (inner_h - len(ids) * ROW) / 2
        for r, i in enumerate(ids):
            pos[i] = (PAD + CW / 2 + c * COL, PAD + top + r * ROW)
    frame_w = PAD * 2 + CW / 2 * 2 + (ncol - 1) * COL + BW
    frame_h = PAD * 2 + inner_h - (ROW - BH)

    # connectors on the left or right edge, next to their block
    left, right = [], []
    for c in connectors:
        b = block_of.get(c.get("part"))
        y = pos[b][1] + BH / 2 if b in pos else PAD
        (left if b in col and col[b] < ncol / 2 else right).append((y, c))
    cpos: dict[str, tuple[float, float, str]] = {}
    for side, items in (("L", left), ("R", right)):
        items.sort(key=lambda t: t[0])
        last = -1e9
        for y, c in items:
            y = max(y - CH / 2, last + CH + 10, 8)
            last = y
            x = -CW / 2 if side == "L" else frame_w - CW / 2
            cpos[c["id"]] = (x, y, side)
    bottom = max([frame_h] + [y + CH + 10 for x, y, s in cpos.values()])
    frame_h = max(frame_h, bottom)

    # edges, merged per (a, b, kind)
    edges: dict[tuple[str, str, str], list[str]] = defaultdict(list)

    def add(a: str | None, b: str | None, kind: str, label: str = ""):
        if not a or not b or a == b:
            return
        key = (a, b, kind)
        if label and label not in edges[key]:
            edges[key].append(label)
        else:
            edges.setdefault(key, edges[key])

    net_conn = defaultdict(set)
    for c in connectors:
        for p in c.get("pins", []):
            if p.get("direction") == "power_in" and p.get("net"):
                net_conn[p["net"]].add("C:" + c["id"])
    rail_by_id = {r["id"]: r for r in rails}

    def rail_sources(r: dict) -> set[str]:
        src = r.get("source", {})
        if src.get("part") and block_of.get(src["part"]):
            return {"B:" + block_of[src["part"]]}
        if src.get("type") == "external":
            return net_conn.get(r.get("net"), set())
        parent = rail_by_id.get(src.get("from_rail"))
        return rail_sources(parent) if parent else set()

    for r in rails:
        label = r.get("net", r["id"]).lstrip("/")
        srcs = rail_sources(r)
        for l in r.get("loads", []):
            for s in srcs:
                add(s, "B:" + str(block_of.get(l["part"])), "power", label)
        parent = rail_by_id.get(r.get("source", {}).get("from_rail"))
        if parent and r.get("source", {}).get("part"):
            for s in rail_sources(parent):
                add(s, "B:" + str(block_of.get(r["source"]["part"])), "power", parent.get("net", parent["id"]).lstrip("/"))
    for bus in buses:
        ctrl = block_of.get(bus.get("controller"))
        for d in bus.get("devices", []):
            add("B:" + str(ctrl), "B:" + str(block_of.get(d.get("part"))), "comm", bus["id"])
    for c in connectors:
        dirs = {p.get("direction") for p in c.get("pins", [])}
        kind = "mix" if dirs & SIGNAL_DIRS and dirs & POWER_DIRS else "comm" if dirs & SIGNAL_DIRS else "power"
        add("C:" + c["id"], "B:" + str(block_of.get(c.get("part"))), kind)
        add("X:" + c["id"], "C:" + c["id"], kind)
    covered = {frozenset((a, b)) for a, b, _ in edges}
    for b in blocks:
        for t in b.get("connects_to", []):
            if frozenset(("B:" + b["id"], "B:" + t)) not in covered and t in pos:
                add("B:" + b["id"], "B:" + t, "other")
                covered.add(frozenset(("B:" + b["id"], "B:" + t)))

    # geometry of every node: (x, y, w, h)
    ox = CW / 2 + XW + EXT
    geo: dict[str, tuple[float, float, float, float]] = {}
    for i, (x, y) in pos.items():
        geo["B:" + i] = (ox + x, y + 30, BW, BH)
    for cid, (x, y, side) in cpos.items():
        geo["C:" + cid] = (ox + x, y + 30, CW, CH)
        xx = ox + x - EXT - XW + CW / 2 if side == "L" else ox + x + CW / 2 + EXT
        geo["X:" + cid] = (xx, y + 30 - (XH - CH) / 2, XW, XH)

    def side(n: str, toward: tuple[float, float]) -> int:
        x, y, w, h = geo[n]
        return 1 if toward[0] > x + w / 2 else -1

    def centre(n: str) -> tuple[float, float]:
        x, y, w, h = geo[n]
        return x + w / 2, y + h / 2

    # spread the line ends along each box side, sorted by the other end's height
    ends: dict[tuple[str, int], list[tuple[float, tuple, int]]] = defaultdict(list)
    drawn = [(k, v) for k, v in edges.items() if k[0] in geo and k[1] in geo]
    for idx, ((a, b, kind), _) in enumerate(drawn):
        ca, cb = centre(a), centre(b)
        ends[(a, side(a, cb))].append((cb[1], (idx, 0), 0))
        ends[(b, side(b, ca))].append((ca[1], (idx, 1), 0))
    point: dict[tuple[int, int], tuple[float, float, int]] = {}
    for (n, sd), items in ends.items():
        x, y, w, h = geo[n]
        items.sort(key=lambda t: t[0])
        for i, (_, key, _) in enumerate(items):
            fy = y + h * (i + 1) / (len(items) + 1)
            point[key] = (x + w if sd > 0 else x, fy, sd)

    e = html.escape
    width = ox * 2 + frame_w
    height = frame_h + 60
    out = [f'<svg class="bdiag" viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" height="{height:.0f}" '
           f'xmlns="http://www.w3.org/2000/svg">',
           '<g class="legend" transform="translate(4,12)">'
           '<line class="power" x1="0" y1="0" x2="26" y2="0"/><text x="32" y="4">power</text>'
           '<line class="comm" x1="90" y1="0" x2="116" y2="0"/><text x="122" y="4">communication</text>'
           '<line class="mix" x1="230" y1="0" x2="256" y2="0"/><text x="262" y="4">power + signals</text>'
           '<line class="other" x1="370" y1="0" x2="396" y2="0"/><text x="402" y="4">other link</text></g>',
           f'<rect class="frame" x="{ox}" y="30" width="{frame_w:.0f}" height="{frame_h:.0f}" rx="12"/>',
           f'<text class="fname" x="{ox + 12}" y="48">{e(spec.get("project", {}).get("name", "board"))}</text>']
    for idx, ((a, b, kind), labels) in enumerate(drawn):
        x1, y1, d1 = point[(idx, 0)]
        x2, y2, d2 = point[(idx, 1)]
        k = max(40, abs(x2 - x1) / 2)
        tip = e(", ".join(labels)) if labels else kind
        out.append(f'<path class="edge {kind}" d="M{x1:.0f},{y1:.0f} C{x1 + d1 * k:.0f},{y1:.0f} '
                   f'{x2 + d2 * k:.0f},{y2:.0f} {x2:.0f},{y2:.0f}"><title>{tip}</title></path>')
        if labels and kind in ("power", "comm"):
            lx = x2 + d2 * 6
            out.append(f'<text class="elabel {kind}" x="{lx:.0f}" y="{y2 - 3:.0f}" '
                       f'text-anchor="{"start" if d2 > 0 else "end"}">{e(_short(", ".join(labels), 24))}</text>')
    crit = {b["id"]: b.get("criticality", "standard") for b in blocks}
    func = {b["id"]: b.get("function", "") for b in blocks}
    for n, (x, y, w, h) in geo.items():
        kind, ident = n[0], n[2:]
        if kind == "B":
            plist = [p["mpn"] for p in parts.values() if p.get("block") == ident][:3]
            out.append(f'<g class="blk crit-{crit[ident]}" data-block="{e(ident)}"><title>{e(func[ident])}</title>'
                       f'<rect x="{x:.0f}" y="{y:.0f}" width="{w}" height="{h}" rx="8"/>'
                       f'<text class="t1" x="{x + 10:.0f}" y="{y + 21:.0f}">{e(_short(ident, 28))}</text>'
                       f'<text class="t2" x="{x + 10:.0f}" y="{y + 40:.0f}">{e(_short(", ".join(plist), 34))}</text></g>')
        elif kind == "C":
            c = next(c for c in connectors if c["id"] == ident)
            out.append(f'<g class="conn"><title>{e(c.get("purpose", ""))}</title>'
                       f'<rect x="{x:.0f}" y="{y:.0f}" width="{w}" height="{h}" rx="4"/>'
                       f'<text x="{x + w / 2:.0f}" y="{y + 19:.0f}" text-anchor="middle">{e(ident.upper())}</text></g>')
        else:
            c = next(c for c in connectors if c["id"] == ident)
            out.append(f'<g class="ext"><title>{e(c.get("purpose", ""))}</title>'
                       f'<rect x="{x:.0f}" y="{y:.0f}" width="{w}" height="{h}" rx="6"/>'
                       f'<text x="{x + 8:.0f}" y="{y + 21:.0f}">{e(_short(c.get("purpose", ident), 26))}</text></g>')
    out.append("</svg>")
    return "".join(out)
