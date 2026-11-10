"""Read KiCad 10 schematic and board files (S-expressions) for the dashboard.

Only what the dashboard needs: the sheet hierarchy, where each symbol and footprint is
on its page (bounding box in mm, page coordinates, the same as the SVG exported by
kicad-cli), and their reference, value and MPN. Netlist and electrical data still come
from `kicad-cli sch export netlist` (see kicad_import.py).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

_TOKEN = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+')

PAPER_MM = {  # landscape width x height
    "A5": (210, 148), "A4": (297, 210), "A3": (420, 297), "A2": (594, 420), "A1": (841, 594), "A0": (1189, 841),
    "A": (279.4, 215.9), "B": (431.8, 279.4), "C": (558.8, 431.8), "D": (863.6, 558.8), "E": (1117.6, 863.6),
    "USLetter": (279.4, 215.9), "USLegal": (355.6, 215.9), "USLedger": (431.8, 279.4),
}


def parse_sexpr(text: str) -> list:
    """Parse S-expressions into nested lists of strings (quotes removed)."""
    stack: list[list] = [[]]
    for tok in _TOKEN.findall(text):
        if tok == "(":
            stack.append([])
        elif tok == ")":
            done = stack.pop()
            stack[-1].append(done)
        elif tok.startswith('"'):
            stack[-1].append(tok[1:-1].replace('\\"', '"').replace("\\\\", "\\"))
        else:
            stack[-1].append(tok)
    return stack[0][0] if stack[0] else []


def children(node: list, name: str) -> list[list]:
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == name]


def child(node: list, name: str) -> list | None:
    return next(iter(children(node, name)), None)


def prop(node: list, key: str) -> str | None:
    for p in children(node, "property"):
        if len(p) > 2 and p[1] == key:
            return p[2]
    return None


def _num(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def paper_size(root: list) -> tuple[float, float]:
    p = child(root, "paper")
    if not p:
        return PAPER_MM["A4"]
    if p[1] == "User":
        return _num(p[2], 297), _num(p[3], 210)
    w, h = PAPER_MM.get(p[1], PAPER_MM["A4"])
    return (h, w) if "portrait" in p[2:] else (w, h)


@dataclass
class Item:
    ref: str
    value: str
    mpn: str
    bbox: tuple[float, float, float, float]   # x0, y0, x1, y1 in mm, page coordinates
    side: str = ""                            # PCB: front or back
    dnp: bool = False

    def to_dict(self) -> dict:
        d = {"ref": self.ref, "value": self.value, "mpn": self.mpn, "bbox": [round(v, 3) for v in self.bbox]}
        if self.side:
            d["side"] = self.side
        if self.dnp:
            d["dnp"] = True
        return d


@dataclass
class Sheet:
    name: str                 # sheet name, "" for the root
    file: Path
    path: str                 # instance path, e.g. /root-uuid/sheet-uuid
    page: tuple[float, float]
    items: list[Item] = field(default_factory=list)


# Schematic ------------------------------------------------------------------------------

def _lib_points(lib_sym: list, unit: int) -> list[tuple[float, float]]:
    """Points of a library symbol's body and pins, in library coordinates (y up)."""
    pts: list[tuple[float, float]] = []
    for sub in children(lib_sym, "symbol"):
        m = re.search(r"_(\d+)_(\d+)$", sub[1])
        if m and int(m.group(1)) not in (0, unit):
            continue
        for g in sub[1:]:
            if not isinstance(g, list) or not g:
                continue
            if g[0] == "pin":
                at = child(g, "at")
                length = _num((child(g, "length") or [0, 0])[1])
                if at:
                    x, y, a = _num(at[1]), _num(at[2]), math.radians(_num(at[3]) if len(at) > 3 else 0)
                    pts += [(x, y), (x + length * math.cos(a), y + length * math.sin(a))]
            elif g[0] == "rectangle":
                for k in ("start", "end"):
                    c = child(g, k)
                    if c:
                        pts.append((_num(c[1]), _num(c[2])))
            elif g[0] in ("polyline", "bezier"):
                for xy in children(child(g, "pts") or [], "xy"):
                    pts.append((_num(xy[1]), _num(xy[2])))
            elif g[0] == "circle":
                c, r = child(g, "center"), _num((child(g, "radius") or [0, 0])[1])
                if c:
                    pts += [(_num(c[1]) - r, _num(c[2]) - r), (_num(c[1]) + r, _num(c[2]) + r)]
            elif g[0] == "arc":
                for k in ("start", "mid", "end"):
                    c = child(g, k)
                    if c:
                        pts.append((_num(c[1]), _num(c[2])))
    return pts


def _place(pts, x: float, y: float, angle: float, mirror: str | None):
    """Library coordinates (y up) to sheet coordinates (y down), KiCad orientation rules."""
    out = []
    a = math.radians(angle)
    ca, sa = round(math.cos(a)), round(math.sin(a))
    for px, py in pts:
        py = -py                                   # library y up, sheet y down
        if mirror == "y":
            px = -px
        elif mirror == "x":
            py = -py
        rx = px * ca + py * sa                     # rotation is counterclockwise on screen
        ry = -px * sa + py * ca
        out.append((x + rx, y + ry))
    return out


def _bbox(pts, margin: float) -> tuple[float, float, float, float] | None:
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin


def _symbol_ref(sym: list, path: str) -> tuple[str, int]:
    unit = int(_num((child(sym, "unit") or [0, 1])[1], 1))
    inst = child(sym, "instances")
    if inst:
        for project in children(inst, "project"):
            for p in children(project, "path"):
                if p[1] == path:
                    ref = child(p, "reference")
                    u = child(p, "unit")
                    return (ref[1] if ref else prop(sym, "Reference") or "?"), int(_num(u[1], unit)) if u else unit
    return prop(sym, "Reference") or "?", unit


def read_schematic(root_file: Path) -> list[Sheet]:
    """Every sheet instance of the hierarchy, with its symbols."""
    root_file = Path(root_file)
    cache: dict[Path, list] = {}

    def load(f: Path) -> list:
        if f not in cache:
            cache[f] = parse_sexpr(f.read_text(encoding="utf-8"))
        return cache[f]

    sheets: list[Sheet] = []

    def walk(f: Path, name: str, path: str, depth: int):
        if depth > 20 or not f.exists():
            return
        tree = load(f)
        sheet = Sheet(name, f, path, paper_size(tree))
        libs = {s[1]: s for s in children(child(tree, "lib_symbols") or [], "symbol")}
        for sym in children(tree, "symbol"):
            lib_id = (child(sym, "lib_id") or [None, ""])[1]
            if lib_id.startswith("power:") or (prop(sym, "Reference") or "").startswith("#"):
                continue
            ref, unit = _symbol_ref(sym, path)
            if ref.startswith("#"):
                continue
            at = child(sym, "at") or ["at", 0, 0, 0]
            mirror = (child(sym, "mirror") or [None, None])[1]
            pts = _lib_points(libs.get(lib_id, []), unit) if lib_id in libs else []
            box = _bbox(_place(pts, _num(at[1]), _num(at[2]), _num(at[3]) if len(at) > 3 else 0, mirror), 0.6)
            if box is None:
                x, y = _num(at[1]), _num(at[2])
                box = (x - 2.54, y - 2.54, x + 2.54, y + 2.54)
            dnp = (child(sym, "dnp") or [None, "no"])[1] == "yes"
            sheet.items.append(Item(ref, prop(sym, "Value") or "", prop(sym, "MPN") or "", box, dnp=dnp))
        sheets.append(sheet)
        for sh in children(tree, "sheet"):
            uuid = (child(sh, "uuid") or [None, ""])[1]
            sub_name = prop(sh, "Sheetname") or prop(sh, "Sheet name") or uuid
            sub_file = prop(sh, "Sheetfile") or prop(sh, "Sheet file")
            if sub_file:
                walk(f.parent / sub_file, sub_name, f"{path}/{uuid}", depth + 1)

    root = load(root_file)
    walk(root_file, "", "/" + (child(root, "uuid") or [None, ""])[1], 0)
    return sheets


# Board ----------------------------------------------------------------------------------

def read_board(pcb_file: Path) -> tuple[tuple[float, float], list[Item]]:
    """Page size and every footprint with its bounding box (from its pads), in page mm."""
    tree = parse_sexpr(Path(pcb_file).read_text(encoding="utf-8"))
    items = []
    for fp in children(tree, "footprint"):
        at = child(fp, "at") or ["at", 0, 0]
        fx, fy = _num(at[1]), _num(at[2])
        rot = math.radians(_num(at[3]) if len(at) > 3 else 0)
        c, s = math.cos(rot), math.sin(rot)
        layer = (child(fp, "layer") or [None, "F.Cu"])[1]
        ref = prop(fp, "Reference")
        if ref is None:                                         # KiCad 7 and older
            ref = next((t[2] for t in children(fp, "fp_text") if len(t) > 2 and t[1] == "reference"), "?")
        pts = []
        for pad in children(fp, "pad"):
            pa, size = child(pad, "at"), child(pad, "size")
            if not pa:
                continue
            px, py = _num(pa[1]), _num(pa[2])
            hw, hh = (_num(size[1]) / 2, _num(size[2]) / 2) if size else (0.3, 0.3)
            r = max(hw, hh)
            # pad position relative to the footprint, rotated like KiCad (y down, counterclockwise)
            x = fx + px * c + py * s
            y = fy - px * s + py * c
            pts += [(x - r, y - r), (x + r, y + r)]
        if not pts:
            pts = [(fx - 1, fy - 1), (fx + 1, fy + 1)]
        attr = child(fp, "attr") or []
        items.append(Item(ref, prop(fp, "Value") or "", prop(fp, "MPN") or "", _bbox(pts, 0.25),
                          side="back" if layer.startswith("B.") else "front", dnp="dnp" in attr))
    return paper_size(tree), items
