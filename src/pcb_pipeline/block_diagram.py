"""Block diagram of the board, drawn from design/spec.yaml for the dashboard.

Everything comes from the spec, nothing is drawn by hand:
- one box per block on a grid; columns follow `connects_to` from the entry blocks (the
  blocks that own a connector with a power input), rows are ordered to limit crossings;
- each connector on the board edge, next to the block that owns it (`parts[].block`),
  with its off-board side (`purpose`) outside the frame;
- power lines from the rails (source part's block to each load's block, input connector
  for external rails), communication lines from the buses (controller block to each
  device block), protection lines from the ESD block to the protected connectors, and the
  remaining `connects_to` links.

Lines are orthogonal: they leave a box sideways, run in the vertical channels between
columns and the horizontal channels between rows, each on its own lane.
"""

from __future__ import annotations

import html
import re
import textwrap
from collections import defaultdict

BW, BH = 220, 62           # block box
GX, GY = 150, 64           # gaps between columns / rows (line channels)
CW, CH = 56, 30            # connector box
XW, XH = 190, 44           # external box
EXT = 50                   # gap between the frame and the external boxes
LG = 120                   # channel between a board edge and the nearest column
TOP = 70                   # frame top margin (legend)

# one colour per rail (power lines), away from the communication / mix / protection colours
RAIL_COLOURS = ["#f76b15", "#d4a017", "#d6409f", "#2bb3a3", "#a0522d", "#ff8a80", "#9c6ade", "#8d6e63", "#4caf50", "#e91e63"]

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
    for i in ids:
        col.setdefault(i, last + (1 if col else 0))
    return col


def _lanes(spans: list[tuple[float, float, object]]) -> dict[object, int]:
    """Greedy interval colouring: (lo, hi, key) -> lane; overlapping spans get different lanes."""
    lane_end: list[float] = []
    out = {}
    for lo, hi, key in sorted(spans, key=lambda s: (s[0], s[1])):
        for i, end in enumerate(lane_end):
            if lo > end + 6:
                lane_end[i] = hi
                out[key] = i
                break
        else:
            lane_end.append(hi)
            out[key] = len(lane_end) - 1
    return out


def block_diagram_svg(spec: dict) -> str:
    blocks = spec.get("blocks", [])
    if not blocks:
        return ""
    parts = {p["id"]: p for p in spec.get("parts", [])}
    block_of = {pid: p.get("block") for pid, p in parts.items()}
    connectors = spec.get("connectors", [])
    conn_by_id = {c["id"]: c for c in connectors}
    rails = spec.get("power_tree", {}).get("rails", [])
    buses = spec.get("buses", [])
    bids = {b["id"] for b in blocks}

    def conn_block(c: dict) -> str | None:
        """Owning block: explicit `block`, else a block whose function names the connector (J4, J6-J8), else the part's block."""
        if c.get("block") in bids:
            return c["block"]
        num = re.fullmatch(r"[A-Za-z]+(\d+)", c["id"])
        for b in blocks:
            for m in re.finditer(r"\b([A-Za-z]+)(\d+)(?:\s*-\s*[A-Za-z]*(\d+))?\b", b.get("function", "")):
                if num and m.group(1).lower() == re.sub(r"\d+", "", c["id"]).lower():
                    lo, hi = int(m.group(2)), int(m.group(3) or m.group(2))
                    if lo <= int(num.group(1)) <= hi:
                        return b["id"]
        return block_of.get(c.get("part"))

    cblock = {c["id"]: conn_block(c) for c in connectors}

    # ---------- logical edges, merged per (pair, kind) ----------
    edges: dict[tuple[str, str, str], list[str]] = {}

    def add(a: str, b: str, kind: str, label: str = ""):
        if a == b or a.endswith(":None") or b.endswith(":None"):
            return
        key = (*sorted((a, b)), kind)
        lst = edges.setdefault(key, [])
        if label and label not in lst:
            lst.append(label)

    net_conn = defaultdict(set)
    for c in connectors:
        for p in c.get("pins", []):
            if p.get("direction") == "power_in" and p.get("net") and cblock[c["id"]]:
                net_conn[p["net"]].add("B:" + cblock[c["id"]])
    rail_by_id = {r["id"]: r for r in rails}

    def rail_sources(r: dict, seen=()) -> set[str]:
        src = r.get("source", {})
        if src.get("part") and block_of.get(src["part"]) in bids:
            return {"B:" + block_of[src["part"]]}
        if src.get("type") == "external":
            return net_conn.get(r.get("net"), set())
        parent = rail_by_id.get(src.get("from_rail"))
        return rail_sources(parent, seen + (r["id"],)) if parent and parent["id"] not in seen else set()

    rail_colour = {r["id"]: RAIL_COLOURS[i % len(RAIL_COLOURS)] for i, r in enumerate(rails)}
    for r in rails:
        label = r.get("net", r["id"]).lstrip("/")
        kind = "power|" + r["id"]
        for s in rail_sources(r):
            for load in r.get("loads", []):
                add(s, f"B:{block_of.get(load['part'])}", kind, label)
            for child in rails:
                if child.get("source", {}).get("from_rail") == r["id"] and child.get("source", {}).get("part"):
                    add(s, f"B:{block_of.get(child['source']['part'])}", kind, label)
    for bus in buses:
        ctrl = f"B:{block_of.get(bus.get('controller'))}"
        for d in bus.get("devices", []):
            add(ctrl, f"B:{block_of.get(d.get('part'))}", "comm", bus["id"])
    esd_blocks = [b["id"] for b in blocks if "esd" in b["id"].lower() or "protection" in b["id"].lower()]
    for c in connectors:
        dirs = {p.get("direction") for p in c.get("pins", [])}
        kind = "mix" if dirs & SIGNAL_DIRS and dirs & POWER_DIRS else "comm" if dirs & SIGNAL_DIRS else "power"
        add("C:" + c["id"], f"B:{cblock[c['id']]}", kind)
        add("X:" + c["id"], "C:" + c["id"], kind)
    protected = [c["id"] for c in connectors if any(p.get("esd_protected") for p in c.get("pins", []))]
    controllers = {block_of.get(bus.get("controller")): bus["id"] for bus in buses}
    for c in connectors:
        sig = [p["signal"] for p in c.get("pins", []) if p.get("direction") in SIGNAL_DIRS]
        owner = next((b for b in blocks if b["id"] == cblock[c["id"]]), None)
        if sig and owner:
            for t in owner.get("connects_to", []):
                if t in controllers:
                    add("B:" + owner["id"], "B:" + t, "comm", "/".join(sig[:2]))
    covered = {frozenset(k[:2]) for k in edges}
    for b in blocks:
        for t in b.get("connects_to", []):
            if t in bids and frozenset(("B:" + b["id"], "B:" + t)) not in covered:
                add("B:" + b["id"], "B:" + t, "other")
                covered.add(frozenset(("B:" + b["id"], "B:" + t)))

    # ---------- a block that only holds connectors is drawn as its connector ----------
    conn_parts = {c.get("part") for c in connectors}
    collapsed: dict[str, str] = {}
    for b in blocks:
        own = [p for p in parts.values() if p.get("block") == b["id"]]
        conns = [c["id"] for c in connectors if cblock[c["id"]] == b["id"]]
        if conns and own and all(p["id"] in conn_parts for p in own):
            collapsed[b["id"]] = conns[0]
    if collapsed:
        merged: dict[tuple[str, str, str], list[str]] = {}
        for (a, b, k), labels in edges.items():
            a2 = "C:" + collapsed[a[2:]] if a.startswith("B:") and a[2:] in collapsed else a
            b2 = "C:" + collapsed[b[2:]] if b.startswith("B:") and b[2:] in collapsed else b
            if a2 == b2:
                continue
            lst = merged.setdefault((*sorted((a2, b2)), k), [])
            lst += [x for x in labels if x not in lst]
        edges = merged
    entry_conn = {"C:" + c for c in collapsed.values()}

    # ---------- grid placement ----------
    entry = {cblock[c["id"]] for c in connectors
             if any(p.get("direction") == "power_in" for p in c.get("pins", []))}
    col_all = _columns(blocks, entry)
    blocks = [b for b in blocks if b["id"] not in collapsed]
    base = min(col_all[b["id"]] for b in blocks)
    col = {b["id"]: col_all[b["id"]] - base for b in blocks}
    ncol = max(col.values()) + 1
    weight = {"comm": 4, "mix": 4, "power": 1, "other": 1}
    neigh: dict[str, dict[str, float]] = defaultdict(dict)
    row: dict[str, float] = {c: -0.5 for c in entry_conn}  # collapsed entry connectors pull their links to the top
    for a, b, k in edges:
        w = weight.get(k.split("|")[0], 1)
        if k == "comm" and (a[2:] in entry or b[2:] in entry or a in entry_conn or b in entry_conn):
            w *= 6                                       # keep the link buffer next to the board entry
        if a.startswith("B:") and b.startswith("B:"):
            neigh[a[2:]][b[2:]] = neigh[a[2:]].get(b[2:], 0) + w
            neigh[b[2:]][a[2:]] = neigh[b[2:]].get(a[2:], 0) + w
        elif a in entry_conn and b.startswith("B:"):
            neigh[b[2:]][a] = neigh[b[2:]].get(a, 0) + w
        elif b in entry_conn and a.startswith("B:"):
            neigh[a[2:]][b] = neigh[a[2:]].get(b, 0) + w
    order: dict[int, list[str]] = defaultdict(list)
    for b in blocks:
        order[col[b["id"]]].append(b["id"])
    for ids in order.values():
        for r, i in enumerate(ids):
            row[i] = r
    for _ in range(4):                                   # barycentre ordering, both directions
        for c in list(range(ncol)) + list(range(ncol - 2, -1, -1)):
            ids = order[c]
            bary = {i: (sum(row[n] * w for n, w in neigh[i].items()) / sum(neigh[i].values()) if neigh[i] else row[i])
                    for i in ids}
            ids.sort(key=lambda i: (bary[i], row[i]))
            for r, i in enumerate(ids):
                row[i] = r
    nrow = max(len(v) for v in order.values())

    FX = XW + EXT + CW / 2 + 4                           # frame left x
    X0 = FX + LG
    Y0 = TOP + GY

    def colx(c: int) -> float:
        return X0 + c * (BW + GX)

    def rowy(r: int) -> float:
        return Y0 + r * (BH + GY)

    FW = LG + ncol * BW + (ncol - 1) * GX + LG
    FH = nrow * (BH + GY) + GY
    geo: dict[str, tuple[float, float, float, float]] = {}
    for b in blocks:
        geo["B:" + b["id"]] = (colx(col[b["id"]]), rowy(row[b["id"]]), BW, BH)

    # connectors on the frame, left or right, near their block
    sides: dict[str, int] = {}
    stacks: dict[int, list[tuple[float, str]]] = {-1: [], 1: []}
    for c in connectors:
        b = cblock[c["id"]]
        g = geo.get(f"B:{b}")
        sd = -1 if (b not in col or col[b] < ncol / 2) else 1
        sides[c["id"]] = sd
        if g:
            y = g[1] + BH / 2
        else:                                            # collapsed block: height of the blocks it links to
            pts = [(geo[o][1] + BH / 2, 6 if k == "comm" else 1) for a_, b_, k in edges
                   for o in ((b_,) if a_ == "C:" + c["id"] else (a_,) if b_ == "C:" + c["id"] else ())
                   if o.startswith("B:") and o in geo]
            y = sum(v * w for v, w in pts) / sum(w for _, w in pts) if pts else Y0
        stacks[sd].append((y, c["id"]))
    for sd, items in stacks.items():
        items.sort()
        last = TOP - XH
        for y, cid in items:
            y = max(y - CH / 2, last + XH + 10)
            last = y
            x = (FX if sd < 0 else FX + FW) - CW / 2
            geo["C:" + cid] = (x, y, CW, CH)
            xx = x - EXT - XW if sd < 0 else x + CW + EXT
            geo["X:" + cid] = (xx, y + CH / 2 - XH / 2, XW, XH)
    FH = max(FH, max(y + h for (x, y, w, h) in geo.values()) - TOP + 16)

    # ---------- channels ----------
    def vchan(k: int) -> tuple[float, float]:           # right of column k; -1 = left board edge
        lo = FX + CW / 2 + 10 if k < 0 else colx(k) + BW + 10
        hi = FX + FW - CW / 2 - 10 if k >= ncol - 1 else colx(k + 1) - 10
        return lo, hi

    def hchan(r: int) -> tuple[float, float]:           # above row r (r = nrow: below the last row)
        return rowy(r) - GY + 10, rowy(r) - 10

    def node_col(n: str) -> int:
        if n.startswith("B:"):
            return col[n[2:]]
        return -1 if sides.get(n[2:], -1) < 0 else ncol

    def chan(n: str, right: bool) -> int:
        c = node_col(n)
        if c == -1:
            return -1
        if c == ncol:
            return ncol - 1
        return c if right else c - 1

    routes = []
    for (a, b, kind), labels in edges.items():
        if a not in geo or b not in geo:
            continue
        if a.startswith("X:") or b.startswith("X:"):
            x_, c_ = (a, b) if a.startswith("X:") else (b, a)
            routes.append({"kind": kind, "labels": labels, "direct": (x_, c_)})
            continue
        ca, cb = node_col(a), node_col(b)
        if ca > cb or (ca == cb and geo[a][1] > geo[b][1]):
            a, b, ca, cb = b, a, cb, ca
        if ca == cb:
            sa = sb = 1 if ca < ncol else -1
            ka = kb = chan(a, sa > 0)
        else:
            sa, sb = 1, -1
            ka, kb = chan(a, True), chan(b, False)
        routes.append({"kind": kind, "labels": labels, "a": a, "b": b, "sa": sa, "sb": sb, "ka": ka, "kb": kb})

    # anchor points spread along each box side, ordered by the other end's height
    ends = defaultdict(list)
    for i, rt in enumerate(routes):
        if "direct" in rt:
            continue
        ends[(rt["a"], rt["sa"])].append((geo[rt["b"]][1], i, "a"))
        ends[(rt["b"], rt["sb"])].append((geo[rt["a"]][1], i, "b"))
    anchor = {}
    for (n, sd), items in ends.items():
        x, y, w, h = geo[n]
        items.sort()
        for j, (_, i, which) in enumerate(items):
            anchor[(i, which)] = (x + w if sd > 0 else x, y + h * (j + 1) / (len(items) + 1))

    # horizontal channel choice and lane requests
    vreq, hreq = defaultdict(list), defaultdict(list)
    for i, rt in enumerate(routes):
        if "direct" in rt:
            continue
        (x1, y1), (x2, y2) = anchor[(i, "a")], anchor[(i, "b")]
        rt["p1"], rt["p2"] = (x1, y1), (x2, y2)
        if rt["ka"] == rt["kb"]:
            rt["h"] = None
            vreq[rt["ka"]].append((min(y1, y2), max(y1, y2), (i, "a")))
        else:
            mid = (y1 + y2) / 2
            h = min(range(nrow + 1), key=lambda r: abs(sum(hchan(r)) / 2 - mid))
            rt["h"] = h
            hm = sum(hchan(h)) / 2
            vreq[rt["ka"]].append((min(y1, hm), max(y1, hm), (i, "a")))
            vreq[rt["kb"]].append((min(y2, hm), max(y2, hm), (i, "b")))
            lo, hi = sorted((sum(vchan(rt["ka"])) / 2, sum(vchan(rt["kb"])) / 2))
            hreq[h].append((lo, hi, i))
    vx: dict[tuple[int, str], float] = {}
    hy: dict[int, float] = {}
    for k, reqs in vreq.items():
        lanes = _lanes(reqs)
        n_l = max(lanes.values()) + 1
        lo, hi = vchan(k)
        step = min(9.0, (hi - lo) / (n_l + 1))
        for _, _, key in reqs:
            vx[key] = (lo + hi) / 2 + (lanes[key] - (n_l - 1) / 2) * step
    for h, reqs in hreq.items():
        lanes = _lanes(reqs)
        n_l = max(lanes.values()) + 1
        lo, hi = hchan(h)
        step = min(8.0, (hi - lo) / (n_l + 1))
        for _, _, i in reqs:
            hy[i] = (lo + hi) / 2 + (lanes[i] - (n_l - 1) / 2) * step

    # ---------- draw ----------
    e = html.escape
    width = FX * 2 + FW
    height = TOP + FH + 20
    out = [f'<svg class="bdiag" viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" height="{height:.0f}" '
           f'xmlns="http://www.w3.org/2000/svg">',
           '<g class="legend" transform="translate(8,18)">'
           '<line class="power" x1="0" y1="0" x2="26" y2="0"/><text x="32" y="4">power pins</text>'
           '<line class="comm" x1="100" y1="0" x2="126" y2="0"/><text x="132" y="4">communication</text>'
           '<line class="mix" x1="250" y1="0" x2="276" y2="0"/><text x="282" y="4">power + signals</text>'
           '<rect class="protsw" x="400" y="-7" width="26" height="14" rx="3"/><text x="432" y="4">ESD-protected connector</text>'
           '<line class="other" x1="600" y1="0" x2="626" y2="0"/><text x="632" y="4">other link</text>'
           + "".join(f'<line class="power" style="stroke:{rail_colour[r["id"]]}" x1="{730 + k * 150}" y1="0" x2="{756 + k * 150}" y2="0"/>'
                     f'<text x="{762 + k * 150}" y="4">{e(r.get("net", r["id"]).lstrip("/"))} {r["nominal_v"]:g} V</text>'
                     for k, r in enumerate(rails)) + '</g>',
           f'<rect class="frame" x="{FX:.0f}" y="{TOP}" width="{FW:.0f}" height="{FH:.0f}" rx="12"/>',
           f'<text class="fname" x="{FX + 14:.0f}" y="{TOP + 20}">{e(spec.get("project", {}).get("name", "board"))}</text>']
    rank = {"other": 0, "prot": 1, "mix": 2, "power": 3, "comm": 4}
    for i in sorted(range(len(routes)), key=lambda i: rank.get(routes[i]["kind"].split("|")[0], 0)):
        rt = routes[i]
        base, _, rid = rt["kind"].partition("|")
        style = f' style="stroke:{rail_colour[rid]}"' if rid in rail_colour else ""
        fill = f' style="fill:{rail_colour[rid]}"' if rid in rail_colour else ""
        tip = e(", ".join(rt["labels"])) if rt["labels"] else rt["kind"]
        if "direct" in rt:
            xg, cg = geo[rt["direct"][0]], geo[rt["direct"][1]]
            y = cg[1] + cg[3] / 2
            x1, x2 = (xg[0] + xg[2], cg[0]) if xg[0] < cg[0] else (xg[0], cg[0] + cg[2])
            out.append(f'<path class="edge {base}"{style} d="M{x1:.0f},{y:.0f} H{x2:.0f}"><title>{tip}</title></path>')
            continue
        (x1, y1), (x2, y2) = rt["p1"], rt["p2"]
        if rt["h"] is None:
            d = f"M{x1:.0f},{y1:.1f} H{vx[(i, 'a')]:.1f} V{y2:.1f} H{x2:.0f}"
        else:
            d = (f"M{x1:.0f},{y1:.1f} H{vx[(i, 'a')]:.1f} V{hy[i]:.1f} H{vx[(i, 'b')]:.1f} "
                 f"V{y2:.1f} H{x2:.0f}")
        out.append(f'<path class="edge {base}"{style} d="{d}"><title>{tip}</title></path>')
        if rt["labels"] and base in ("power", "comm") and rt["b"].startswith("B:"):
            left = rt["sb"] < 0
            out.append(f'<text class="elabel {base}"{fill} x="{x2 + (-4 if left else 4):.0f}" y="{y2 - 3:.1f}" '
                       f'text-anchor="{"end" if left else "start"}">{e(_short(", ".join(rt["labels"]), 18))}</text>')
    crit = {b["id"]: b.get("criticality", "standard") for b in blocks}
    func = {b["id"]: b.get("function", "") for b in blocks}
    name = {b["id"]: b.get("name") or b["id"] for b in blocks}
    for n, (x, y, w, h) in geo.items():
        kind, ident = n[0], n[2:]
        if kind == "B":
            plist = [p["mpn"] for p in parts.values() if p.get("block") == ident][:3]
            if ident in esd_blocks and protected:
                plist = ["protects " + ", ".join(x.upper() for x in protected)]
            out.append(f'<g class="blk crit-{crit[ident]}" data-block="{e(ident)}"><title>{e(ident)}: {e(func[ident])}</title>'
                       f'<rect x="{x:.0f}" y="{y:.0f}" width="{w}" height="{h}" rx="8"/>'
                       f'<text class="t1" x="{x + 10:.0f}" y="{y + 24:.0f}">{e(_short(name[ident], 31))}</text>'
                       f'<text class="t2" x="{x + 10:.0f}" y="{y + 44:.0f}">{e(_short(", ".join(plist), 36))}</text></g>')
        elif kind == "C":
            c = conn_by_id[ident]
            out.append(f'<g class="conn{" prot" if ident in protected else ""}"><title>{e(c.get("purpose", ""))}'
                       f'{" (ESD protected)" if ident in protected else ""}</title>'
                       f'<rect x="{x:.0f}" y="{y:.0f}" width="{w}" height="{h}" rx="4"/>'
                       f'<text x="{x + w / 2:.0f}" y="{y + 20:.0f}" text-anchor="middle">{e(ident.upper())}</text></g>')
        else:
            c = conn_by_id[ident]
            wrapped = textwrap.wrap(c.get("purpose", ident), 27) or [ident]
            lines = wrapped[:2]
            if len(wrapped) > 2:
                lines[-1] = _short(lines[-1] + " " + wrapped[2], 27)
            t = "".join(f'<tspan x="{x + 8:.0f}" dy="{0 if k == 0 else 15}">{e(s)}</tspan>' for k, s in enumerate(lines))
            ty = y + (h / 2 + 4 if len(lines) == 1 else 18)
            out.append(f'<g class="ext"><title>{e(c.get("purpose", ""))}</title>'
                       f'<rect x="{x:.0f}" y="{y:.0f}" width="{w}" height="{h}" rx="6"/>'
                       f'<text x="{x + 8:.0f}" y="{ty:.0f}">{t}</text></g>')
    out.append("</svg>")
    return "".join(out)
