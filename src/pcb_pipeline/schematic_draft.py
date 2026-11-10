"""Draft a KiCad schematic from code (used by the schematic drafter agent, agents/schematic_drafter.md).

Built on kicad-sch-api (pip install "pcb-pipeline[schematic]"), which reads the installed KiCad
symbol libraries and writes .kicad_sch files that KiCad 9 and 10 open (KiCad upgrades the
format on save). This module adds what a readable, reviewable draft needs:

- one hierarchical sheet per block, all referenced from the root sheet;
- every connection drawn as a short wire stub leaving the pin, ending on a power symbol
  (rails), a global label (nets used on several sheets) or a local label (nets of one sheet),
  so the user can drag parts in KiCad (G) without breaking anything;
- MPN, Voltage, LCSC and other fields on every part, so the pipeline rules can run.

The drafter creates a sheet once. Later changes are targeted edits of the existing file
(load, change, save), so the positions the user set in KiCad are kept.
"""

from __future__ import annotations

import json
import math
import re
import uuid as _uuid
from dataclasses import dataclass, field
from pathlib import Path

try:
    import kicad_sch_api as ksa
except ImportError as exc:  # pragma: no cover - optional dependency
    raise ImportError('schematic drafting needs kicad-sch-api: pip install "pcb-pipeline[schematic]"') from exc

GRID = 1.27
STUB = 5.08


def snap(v: float) -> float:
    return round(v / GRID) * GRID


def _rot(v: tuple[float, float], deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return (round(v[0] * math.cos(a) - v[1] * math.sin(a), 6), round(v[0] * math.sin(a) + v[1] * math.cos(a), 6))


def lib_to_screen(v: tuple[float, float], rotation: float) -> tuple[float, float]:
    """Library vector (y up) to schematic vector (y down) for a symbol placed with `rotation`.

    KiCad rotates symbols counterclockwise on screen (y down), i.e. by -rotation in screen
    maths. kicad-sch-api 0.5.x get_component_pin_position uses the opposite sign, which swaps
    the pins of rotated two-pin parts, so pin positions are computed here.
    """
    return _rot((v[0], -v[1]), -rotation)


@dataclass
class Conn:
    ref: str
    pin: str
    net: str | None           # None = no connect
    stub: float | None = None  # wire length from the pin; default Project.stub
    label: bool = False        # draw a power net as a global label (same name joins the power net)


GROUND_LIBS = ("power:GND", "power:GNDPWR", "power:GNDA", "power:GNDD", "power:Earth")


@dataclass
class Placed:
    lib_id: str
    at: tuple[float, float]
    rotation: float
    fields: str               # right | left | top | bottom | topbottom | none
    value: str


@dataclass
class Sheet:
    project: "Project"
    name: str
    title: str
    page: int
    sch: object = None
    conns: list[Conn] = field(default_factory=list)
    sheet_uuid: str = ""
    placed: dict[str, Placed] = field(default_factory=dict)
    field_pos: dict[str, dict[str, tuple]] = field(default_factory=dict)
    boxes: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    routes: list = field(default_factory=list)     # (points, net, group) drawn as wires
    powers: list = field(default_factory=list)     # (net, at, rise, group)
    groups: dict = field(default_factory=dict)     # group -> title
    group_of: dict = field(default_factory=dict)   # ref / owner -> group
    current: str | None = None
    segments: list = field(default_factory=list)   # (p, q, net, owner) of every wire

    def part(self, lib_id: str, ref: str, value: str, at: tuple[float, float], footprint: str = "",
             rotation: float = 0, mpn: str = "", fields: str = "auto", **fields_):
        at = (snap(at[0]), snap(at[1]))
        c = self.sch.components.add(lib_id, reference=ref, value=value, position=at,
                                    footprint=footprint, rotation=rotation)
        props = {"MPN": mpn, **{k.replace("_", " "): v for k, v in fields_.items()}}
        for k, v in props.items():
            if v:
                c.set_property(k, str(v))
        if fields == "auto":
            x0, y0, x1, y1 = screen_box(lib_id, at, rotation)
            w, hgt = x1 - x0, y1 - y0
            fields = "right" if w < 10.5 else "corners"     # two-pin parts, transistors, connectors: right
        self.placed[ref] = Placed(lib_id, at, rotation, fields, value)
        if self.current:
            self.group_of[ref] = self.current
        return c

    # ---- blocks, wires, power symbols on wires ----
    def block(self, title: str):
        """Start a functional block: what follows is framed with this title (drafting rule: framed blocks)."""
        self.current = title
        self.groups[title] = title

    def pin_point(self, ref: str, pin: str | int) -> tuple[float, float]:
        return self._outward(ref, str(pin))[0]

    def wire(self, a, b, net: str, via=(), route: str = "hv"):
        """Orthogonal wire between two pins ((ref, pin)) or points ((x, y)), through optional via points.

        Use it for local connections (an IC and its resistors, decoupling capacitors, protection
        diodes): drafting rule, wires rather than net labels inside a block.
        """
        pts = [self._end(a)] + [(snap(x), snap(y)) for x, y in via] + [self._end(b)]
        if not via and pts[0][0] != pts[1][0] and pts[0][1] != pts[1][1]:
            corner = (pts[1][0], pts[0][1]) if route == "hv" else (pts[0][0], pts[1][1])
            pts.insert(1, corner)
        self.routes.append((pts, net.lstrip("/"), self.current))
        for end in (a, b):
            if isinstance(end[0], str):
                self.wired.add((end[0], str(end[1])))

    def label(self, net: str, at, angle: int = 0, offset: float = 2.54, glob: bool = False):
        """Net label on a wire point; offset > 0 first draws a short wire in the label direction."""
        at = (snap(at[0]), snap(at[1]))
        d = {0: (1, 0), 90: (0, -1), 180: (-1, 0), 270: (0, 1)}[angle]
        end = (snap(at[0] + d[0] * offset), snap(at[1] + d[1] * offset))
        if offset:
            self.routes.append(([at, end], net.lstrip("/"), self.current))
        self.labels_at.append((net.lstrip("/"), end, angle, glob, self.current))

    @property
    def labels_at(self):
        if not hasattr(self, "_labels_at"):
            self._labels_at = []
        return self._labels_at

    def power(self, net: str, at, rise: float = 2.54):
        """Power symbol standing vertically on a point of a wire (rail up, ground down)."""
        self.powers.append((net.lstrip("/"), (snap(at[0]), snap(at[1])), rise, self.current))

    def _end(self, e):
        if isinstance(e[0], str):
            return self.pin_point(e[0], str(e[1]))
        return (snap(e[0]), snap(e[1]))

    @property
    def wired(self):
        if not hasattr(self, "_wired"):
            self._wired = set()
        return self._wired

    def connect(self, ref: str, pin: str | int, net: str, stub: float | None = None, label: bool = False):
        self.conns.append(Conn(ref, str(pin), net.lstrip("/"), stub, label))

    def pins(self, ref: str, mapping: dict, stubs: dict | None = None, labels=()):
        """labels: pins whose power net is drawn as a global label (crowded connector or IC sides)."""
        labels = {str(x) for x in labels}
        for pin, net in mapping.items():
            if net is None:
                self.nc(ref, pin)
            else:
                self.connect(ref, pin, net, (stubs or {}).get(str(pin)), str(pin) in labels)

    def nc(self, ref: str, pin: str | int):
        self.conns.append(Conn(ref, str(pin), None))

    def note(self, text: str, at: tuple[float, float] | None = None, size: float = 1.27, width: int = 110):
        """Sheet note, wrapped; kicad-sch-api centres texts on their position, so the default is the page top centre."""
        import textwrap
        lines = textwrap.wrap(text, width)
        x, y = at if at else (self.project.paper_w / 2, 22.86)
        for k, line in enumerate(lines):
            pos = (snap(x), snap(y + k * 2.54))
            self.sch.add_text(line, pos, size=size)
            self.boxes.append((f"note:{line[:12]}", text_box(line, pos, size, 0, "center"), "note"))
            if self.current:
                self.group_of[f"note:{line[:12]}"] = self.current

    # ---- geometry ----
    def _outward(self, ref: str, pin: str) -> tuple[tuple[float, float], tuple[int, int]]:
        p = self.placed[ref]
        sym = ksa.get_symbol_info(p.lib_id)
        sp = next(x for x in sym.pins if x.number == pin)
        d = (-math.cos(math.radians(sp.rotation)), -math.sin(math.radians(sp.rotation)))
        out = lib_to_screen(d, p.rotation)
        off = lib_to_screen((sp.position.x, sp.position.y), p.rotation)
        return (round(p.at[0] + off[0], 4), round(p.at[1] + off[1], 4)), (round(out[0]), round(out[1]))

    def _fields(self, ref: str, p: Placed):
        if p.fields == "none" or ref.startswith("#"):
            return
        x0, y0, x1, y1 = screen_box(p.lib_id, p.at, p.rotation)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        g = 0.762
        if p.fields == "right":
            pos = {"Reference": (x1 + g, cy - 0.889, 0, "left"), "Value": (x1 + g, cy + 0.889, 0, "left")}
        elif p.fields == "left":
            pos = {"Reference": (x0 - g, cy - 0.889, 0, "right"), "Value": (x0 - g, cy + 0.889, 0, "right")}
        elif p.fields == "bottom":
            pos = {"Reference": (cx, y1 + 1.27, 0, "center"), "Value": (cx, y1 + 2.794, 0, "center")}
        elif p.fields == "corners":                     # ICs: outside the body, top-right and bottom-right
            pos = {"Reference": (x1 + g, y0 - 0.635, 0, "left"), "Value": (x1 + g, y1 + 0.635, 0, "left")}
        elif p.fields == "bottomright":                 # both fields below the body, right of the bottom pins
            pos = {"Reference": (x1 + g, y1 + 0.635, 0, "left"), "Value": (x1 + g, y1 + 2.413, 0, "left")}
        elif p.fields == "topbottom":
            pos = {"Reference": (x0, y0 - 1.27, 0, "left"), "Value": (x0, y1 + 1.27, 0, "left")}
        else:  # top
            pos = {"Reference": (cx, y0 - 2.794, 0, "center"), "Value": (cx, y0 - 1.27, 0, "center")}
        self.field_pos[ref] = pos
        for name, (x, y, a, j) in pos.items():
            txt = ref if name == "Reference" else p.value
            self.boxes.append((f"{ref}.{name}", text_box(txt, (x, y), 1.27, a, j), ref + ":f"))

    def draw(self, power: set[str], globals_: set[str], power_lib: dict[str, str]):
        globals_out = []
        done: dict[tuple[str, float, float], str | None] = {}
        for ref, p in self.placed.items():
            self.boxes.append((ref, screen_box(p.lib_id, p.at, p.rotation), ref))
            self._fields(ref, p)
        for c in self.conns:
            (px, py), (dx, dy) = self._outward(c.ref, c.pin)
            key = (c.ref, round(px, 2), round(py, 2))
            if key in done:                              # stacked pins (e.g. MOSFET source 1-3): one stub only
                if done[key] != c.net:
                    raise ValueError(f"{c.ref} pins at the same point on two nets: {done[key]} / {c.net}")
                continue
            done[key] = c.net
            if c.net is None:
                self.sch.no_connects.add(position=(px, py))
                continue
            own = f"conn:{c.ref}.{c.pin}"
            length = c.stub if c.stub is not None else self.project.stub
            ex, ey = snap(px + dx * length), snap(py + dy * length)
            self.sch.add_wire((px, py), (ex, ey))
            self.segments.append(((px, py), (ex, ey), c.net, own))
            self.boxes.append((f"wire {c.ref}.{c.pin}", (min(px, ex) - 0.15, min(py, ey) - 0.15,
                                                          max(px, ex) + 0.15, max(py, ey) + 0.15), own))
            if c.net in power and not c.label:
                self.project.pwr += 1
                pref = f"#PWR{self.project.pwr:03d}"
                lib = power_lib.get(c.net) or ("power:GND" if c.net.upper().endswith("GND") else "power:VCC")
                ground = lib in GROUND_LIBS
                # always vertical: away from the part on a vertical stub, up (rail) / down (ground) on a side stub
                if dy:
                    rot = 0 if (dy > 0) == ground else 180
                else:
                    rot = 0
                self.sch.components.add(lib, reference=pref, value=c.net, position=(ex, ey), rotation=rot)
                down = ground == (rot == 0)
                bx0, by0, bx1, by1 = screen_box(lib, (ex, ey), rot)
                vy = by1 + 1.524 if down else by0 - 1.524
                self.field_pos[pref] = {"Value": (ex, vy, 0, "center"), "Reference": (ex, vy, 0, "center")}
                self.boxes.append((f"{pref}({c.net})", (bx0, by0, bx1, by1), own))
                self.boxes.append((f"{pref}.Value({c.net})", text_box(c.net, (ex, vy), 1.27, 0, "center"), own))
            else:
                rot = {(1, 0): 0, (0, -1): 90, (-1, 0): 180, (0, 1): 270}[(dx, dy)]
                glob = c.label or c.net in globals_ or c.net in power
                if glob:
                    globals_out.append((c.net, ex, ey, rot))
                else:
                    self.sch.add_label(c.net, position=(ex, ey), rotation=rot)
                self.boxes.append((f"label {c.net} ({c.ref}.{c.pin})",
                                   text_box(c.net, (ex, ey), 1.27, rot, label="global" if glob else "local"), own))
        for i, (pts, net, grp) in enumerate(self.routes):
            own = f"route:{i}"
            if grp:
                self.group_of[own] = grp
            for p0, p1 in zip(pts, pts[1:]):
                if p0 == p1:
                    continue
                self.sch.add_wire(p0, p1)
                self.segments.append((p0, p1, net, own))
                self.boxes.append((f"wire route {net}", (min(p0[0], p1[0]) - 0.15, min(p0[1], p1[1]) - 0.15,
                                                        max(p0[0], p1[0]) + 0.15, max(p0[1], p1[1]) + 0.15), own))
        for i, (net, at, rise, grp) in enumerate(self.powers):
            own = f"pw:{i}"
            if grp:
                self.group_of[own] = grp
            lib = power_lib.get(net) or ("power:GND" if net.upper().endswith("GND") else "power:VCC")
            ground = lib in GROUND_LIBS
            top = (at[0], snap(at[1] + rise if ground else at[1] - rise))
            self.sch.add_wire(at, top)
            self.segments.append((at, top, net, own))
            self.project.pwr += 1
            pref = f"#PWR{self.project.pwr:03d}"
            self.sch.components.add(lib, reference=pref, value=net, position=top, rotation=0)
            bx0, by0, bx1, by1 = screen_box(lib, top, 0)
            vy = by1 + 1.524 if ground else by0 - 1.524
            self.field_pos[pref] = {"Value": (top[0], vy, 0, "center"), "Reference": (top[0], vy, 0, "center")}
            self.boxes.append((f"{pref}({net})", (bx0, by0, bx1, by1), own))
            self.boxes.append((f"{pref}.Value({net})", text_box(net, (top[0], vy), 1.27, 0, "center"), own))
        for i, (net, at, angle, glob, grp) in enumerate(self.labels_at):
            own = f"lbl:{i}"
            if grp:
                self.group_of[own] = grp
            g = glob or net in globals_ or net in power
            if g:
                globals_out.append((net, at[0], at[1], angle))
            else:
                self.sch.add_label(net, position=at, rotation=angle)
            self.boxes.append((f"label {net}", text_box(net, at, 1.27, angle, label="global" if g else "local"), own))
        name_issues = self._name_nets(power)
        conn_issues = self._junctions() + name_issues
        for c in self.conns:
            if c.ref in self.group_of:
                self.group_of[f"conn:{c.ref}.{c.pin}"] = self.group_of[c.ref]
        for ref in list(self.group_of):
            if ref in self.placed:
                self.group_of[ref + ":f"] = self.group_of[ref]
        frame_issues = self._frames()
        self.issues = overlaps(self.boxes) + self._outside_page() + conn_issues + frame_issues
        return globals_out

    def _name_nets(self, power) -> list:
        """One small net-name label sitting on a wire of each net drawn only with wires.

        Without it KiCad names the net after a pin (Net-(U1-FB)) and the netlist loses the spec names.
        The label goes on the longest free segment, horizontal first, where it overlaps nothing.
        """
        named = set(power) | {n for n, *_ in self.labels_at} | {c.net for c in self.conns if c.net}
        named |= {n for n, *_ in self.powers}
        issues = []
        for net in sorted({n for _, n, _ in self.routes} - named):
            if net.startswith("Net-"):
                continue
            segs = [s for s in self.segments if s[2] == net and s[3].startswith("route:")]
            segs.sort(key=lambda s: (s[0][1] != s[1][1], -abs(s[1][0] - s[0][0]) - abs(s[1][1] - s[0][1])))
            w = len(net) * 1.27 * CHAR_W + 0.3
            spot = None
            for p0, p1, _, own in segs:
                horiz = p0[1] == p1[1]
                a, b = sorted((p0[0], p1[0]) if horiz else (p0[1], p1[1]))
                lo, hi = a + 1.27, b - 1.27 - w          # range of the text start along the segment
                if hi < lo:
                    continue
                n = int((hi - lo) / 1.27)
                starts = sorted((snap(lo + k * 1.27) for k in range(n + 1)), key=lambda t: abs(t - (lo + hi) / 2))
                for t in starts:
                    if horiz:
                        at, ang = (t, p0[1]), 0
                    else:
                        at, ang = (p0[0], snap(t + w)), 90     # reads upwards from the anchor
                    box = text_box(net, at, 1.27, ang, label="local")
                    # the text sits above (left of) its wire: a branch leaving on the other side is no clash
                    chk = (box[0], box[1], box[2], at[1] - 0.1) if horiz else (box[0], box[1], at[0] - 0.1, box[3])
                    if not self._hits(chk, own):
                        spot = (at, ang, chk, own)
                        break
                if spot:
                    break
            if not spot:
                issues.append((f"net {net}", "no room for a net-name label on its wires"))
                continue
            at, ang, box, own = spot
            self.sch.add_label(net, position=at, rotation=ang)
            self.boxes.append((f"label {net} (net name)", box, own))
        return issues

    def _hits(self, box, skip_owner, margin: float = 0.25) -> bool:
        for _, b, o in self.boxes:
            if o == skip_owner:
                continue
            if box[0] < b[2] - margin and b[0] < box[2] - margin and box[1] < b[3] - margin and b[1] < box[3] - margin:
                return True
        return False

    def _junctions(self):
        """Junction dots on T connections; a wire touching another net, or a pin in its middle, is an issue."""
        def on_inside(pt, seg):
            (x0, y0), (x1, y1) = seg[0], seg[1]
            if x0 == x1 == pt[0]:
                return min(y0, y1) + 0.01 < pt[1] < max(y0, y1) - 0.01
            if y0 == y1 == pt[1]:
                return min(x0, x1) + 0.01 < pt[0] < max(x0, x1) - 0.01
            return False
        issues, junctions = [], set()
        ends: dict[tuple, int] = {}
        for p0, p1, _, _ in self.segments:
            for q in (p0, p1):
                key = (round(q[0], 2), round(q[1], 2))
                ends[key] = ends.get(key, 0) + 1
        for a in self.segments:
            for q in (a[0], a[1]):
                for b in self.segments:
                    if b is a or not on_inside(q, b):
                        continue
                    if a[2] == b[2]:
                        junctions.add((round(q[0], 2), round(q[1], 2)))
                    else:
                        issues.append((f"wire {a[2]}", f"touches wire {b[2]} at {q} (short)"))
        for key, n in ends.items():
            if n >= 3:
                junctions.add(key)
        pins = []
        for ref, p in self.placed.items():
            for sp in ksa.get_symbol_info(p.lib_id).pins:
                pins.append((ref, sp.number, self._outward(ref, sp.number)[0]))
        for ref, num, pt in pins:
            for seg in self.segments:
                if on_inside(pt, seg):
                    issues.append((f"pin {ref}.{num}", f"on the middle of wire {seg[2]}"))
        for x, y in sorted(junctions):
            self.sch.junctions.add(position=(x, y))
        return issues

    def _frames(self):
        """Dashed frame with a title around each block; frames must not overlap or swallow other blocks."""
        frames, issues = {}, []
        for g in self.groups:
            bs = [b for n, b, o in self.boxes if self.group_of.get(o) == g or self.group_of.get(n) == g]
            if not bs:
                continue
            x0 = min(b[0] for b in bs) - 2.54
            y0 = min(b[1] for b in bs) - 2.54 - 3.81
            x1 = max(b[2] for b in bs) + 2.54
            y1 = max(b[3] for b in bs) + 2.54
            x0, y0 = math.floor(x0 / GRID) * GRID, math.floor(y0 / GRID) * GRID
            x1, y1 = math.ceil(x1 / GRID) * GRID, math.ceil(y1 / GRID) * GRID
            frames[g] = (x0, y0, x1, y1)
            self.sch.add_rectangle((x0, y0), (x1, y1), stroke_width=0.254, stroke_type="dash")
            tpos = (snap((x0 + x1) / 2), snap(y0 + 2.54))
            self.sch.add_text(g, tpos, size=1.524, bold=True)
            tb = text_box(g, tpos, 1.524, 0, "center")
            if tb[2] - tb[0] > x1 - x0:
                issues.append((f"frame {g}", "title wider than the frame"))
        names = list(frames)
        for i, a in enumerate(names):
            fa = frames[a]
            for b in names[i + 1:]:
                fb = frames[b]
                if fa[0] < fb[2] and fb[0] < fa[2] and fa[1] < fb[3] and fb[1] < fa[3]:
                    issues.append((f"frame {a}", f"frame {b}"))
            for n, bx, o in self.boxes:
                g = self.group_of.get(o) or self.group_of.get(n)
                if g and g != a and bx[0] < fa[2] and fa[0] < bx[2] and bx[1] < fa[3] and fa[1] < bx[3]:
                    issues.append((f"frame {a}", n))
        self.frames = frames
        return issues

    def _outside_page(self):
        """Items crossing the page frame or the title block (KiCad default frame: 10 mm margin)."""
        w = self.project.paper_w
        hgt = {"A4": 210.0, "A3": 297.0, "A2": 420.0}.get(self.project.paper, 210.0)
        frame = (12.7, 12.7, w - 12.7, hgt - 12.7)
        title = (w - 12.7 - 101.6, hgt - 12.7 - 33.02, w - 12.7, hgt - 12.7)
        out = []
        for name, (x0, y0, x1, y1), _ in self.boxes:
            if x0 < frame[0] or y0 < frame[1] or x1 > frame[2] or y1 > frame[3]:
                out.append((name, "page frame"))
            elif x0 < title[2] and title[0] < x1 and y0 < title[3] and title[1] < y1:
                out.append((name, "title block"))
        return out


class Project:
    """A KiCad project drafted either flat (one page, `page()`) or as a root sheet plus one sheet per block."""

    def __init__(self, kicad_dir: Path, name: str, power_nets: dict[str, str] | None = None,
                 paper: str = "A4", stub: float = 2.54):
        self.dir = Path(kicad_dir)
        self.name = name
        self.root = ksa.create_schematic(name)
        self.paper = paper
        self.paper_w = {"A4": 297.0, "A3": 420.0, "A2": 594.0}.get(paper, 297.0)
        self.root.set_paper_size(paper)
        self.sheets: list[Sheet] = []
        self.flat: Sheet | None = None
        self.power_lib = dict(power_nets or {})       # net -> power symbol lib id
        self.stub = stub
        self._pos = 0
        self.pwr = 0

    def page(self, title: str = "") -> Sheet:
        """Flat project: everything on the root page (small boards)."""
        self.flat = Sheet(self, self.name, title or self.name, 1, self.root)
        return self.flat

    def sheet(self, name: str, title: str) -> Sheet:
        page = len(self.sheets) + 2
        x, y = 30.48 + (self._pos % 4) * 60.96, 40.64 + (self._pos // 4) * 35.56
        self._pos += 1
        sid = self.root.add_sheet(title, f"{name}.kicad_sch", (x, y), (45.72, 20.32),
                                  project_name=self.name, page_number=str(page))
        sch = ksa.create_schematic(title)
        sch.set_paper_size(self.paper)
        sch.set_hierarchy_context(self.root.uuid, sid)
        s = Sheet(self, name, title, page, sch, sheet_uuid=sid)
        self.sheets.append(s)
        return s

    def issues(self) -> list[tuple[str, str, str]]:
        return [(s.title, a, b) for s in ([self.flat] if self.flat else []) + self.sheets for a, b in s.issues]

    def save(self) -> list[Path]:
        self.dir.mkdir(parents=True, exist_ok=True)
        power = set(self.power_lib)
        written = []
        if self.flat:
            root_path = self.dir / f"{self.name}.kicad_sch"
            # a net drawn once as a global label must be global everywhere, or KiCad splits it
            forced = {c.net for c in self.flat.conns if c.label and c.net and c.net not in power}
            gl = self.flat.draw(power, forced, self.power_lib)
            self.root.save(str(root_path))
            _inject_global_labels(root_path, gl)
            _tidy_properties(root_path)
            _fix_label_justify(root_path)
            _place_fields(root_path, self.flat.field_pos)
            written.append(root_path)
        else:
            uses: dict[str, set[str]] = {}
            for s in self.sheets:
                for c in s.conns:
                    if c.net:
                        uses.setdefault(c.net, set()).add(s.name)
            globals_ = {n for n, sh in uses.items() if len(sh) > 1 and n not in power}
            globals_ |= {c.net for sh in self.sheets for c in sh.conns if c.label and c.net and c.net not in power}
            for s in self.sheets:
                gl = s.draw(power, globals_, self.power_lib)
                path = self.dir / f"{s.name}.kicad_sch"
                s.sch.save(str(path))
                _inject_global_labels(path, gl)
                _tidy_properties(path)
                _fix_label_justify(path)
                _place_fields(path, s.field_pos)
                written.append(path)
            root_path = self.dir / f"{self.name}.kicad_sch"
            self.root.save(str(root_path))
            _drop_zero_wires(root_path)
            written.append(root_path)
        pro = self.dir / f"{self.name}.kicad_pro"
        if not pro.exists():
            pro.write_text(json.dumps({"meta": {"filename": pro.name, "version": 3}}, indent=2), encoding="utf-8")
            written.append(pro)
        return written


def _place_fields(path: Path, positions: dict[str, dict[str, tuple]]):
    """Write explicit Reference / Value positions (absolute, text angle, justify) for the placed symbols."""
    text = path.read_text(encoding="utf-8")
    start = text.find("(lib_symbols")
    start = _block_end(text, start) if start >= 0 else 0
    out, i = [text[:start]], start
    for m in re.finditer(r'\(symbol\s*\n?\s*\(lib_id "[^"]+"\)', text[start:]):
        a = start + m.start()
        if a < i:
            continue
        b = _block_end(text, a)
        block = text[a:b]
        ref = re.search(r'\(property "Reference" "([^"]+)"', block)
        pos = positions.get(ref.group(1)) if ref else None
        srot = re.search(r'\(lib_id "[^"]+"\)\s*\(at [\-\d.]+ [\-\d.]+ ([\-\d.]+)\)', block)
        srot = int(float(srot.group(1))) % 360 if srot else 0
        if pos:
            for name, (x, y, ang, just) in pos.items():
                if srot in (90, 270):                      # keep the text horizontal on screen
                    ang = (ang + 90) % 180
                    if srot == 90 and just in ("left", "right"):
                        just = "right" if just == "left" else "left"
                pm = re.search(r'\(property "' + name + r'" "[^"]*"', block)
                if not pm:
                    continue
                pe = _block_end(block, pm.start())
                prop = block[pm.start():pe]
                prop = re.sub(r"\(at [\-\d.]+ [\-\d.]+ [\-\d.]+\)", f"(at {x:.3f} {y:.3f} {ang})", prop, count=1)
                prop = re.sub(r"\s*\(justify[^)]*\)", "", prop)
                if just != "center":
                    j = prop.find("(effects")
                    if j >= 0:
                        k = _block_end(prop, j)
                        prop = prop[:k - 1] + f" (justify {just}))" + prop[k:]
                block = block[:pm.start()] + prop + block[pe:]
        out.append(text[i:a])
        out.append(block)
        i = b
    out.append(text[i:])
    path.write_text("".join(out), encoding="utf-8")


def _inject_global_labels(path: Path, labels: list[tuple[str, float, float, int]]):
    """kicad-sch-api 0.5.x does not serialize global labels: write them directly."""
    if not labels:
        return
    text = path.read_text(encoding="utf-8")
    blocks = []
    for name, x, y, rot in labels:
        just = "left" if rot in (0, 90) else "right"
        blocks.append(
            f'\t(global_label "{name}"\n\t\t(shape bidirectional)\n\t\t(at {x:g} {y:g} {rot})\n'
            f'\t\t(fields_autoplaced yes)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
            f'\t\t\t(justify {just})\n\t\t)\n\t\t(uuid "{_uuid.uuid4()}")\n\t)\n')
    i = text.rfind("(sheet_instances")
    if i < 0:
        i = text.rstrip().rfind(")")
    else:
        i = text.rfind("\n", 0, i) + 1
    path.write_text(text[:i] + "".join(blocks) + text[i:], encoding="utf-8")


def _drop_zero_wires(path: Path):
    """add_sheet in kicad-sch-api 0.5.x can leave a near zero length wire on the root sheet."""
    text = path.read_text(encoding="utf-8")
    pat = re.compile(r"\t\(wire\s*\n\t\t\(pts\s*\n\t\t\t\(xy ([\d.\-]+) ([\d.\-]+)\) \(xy ([\d.\-]+) ([\d.\-]+)\)\s*\n\t\t\).*?\n\t\)\n", re.S)

    def keep(m):
        x1, y1, x2, y2 = map(float, m.groups())
        return "" if math.hypot(x2 - x1, y2 - y1) < 0.2 else m.group(0)
    path.write_text(pat.sub(keep, text), encoding="utf-8")


def _block_end(text: str, start: int) -> int:
    """Index just after the s-expression starting at text[start] == '('."""
    depth, i, in_str = 0, start, False
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


VISIBLE = {"Reference", "Value"}


def _fix_label_justify(path: Path):
    """Local labels at 180 / 270 degrees must be justified right, or KiCad draws them over the pin."""
    text = path.read_text(encoding="utf-8")

    def fix(m):
        block = m.group(0)
        ang = int(float(re.search(r"\(at [\-\d.]+ [\-\d.]+ ([\-\d.]+)\)", block).group(1))) % 360
        side = "right" if ang in (180, 270) else "left"
        return re.sub(r"\(justify [a-z ]+\)", f"(justify {side} bottom)", block, count=1)
    text = re.sub(r'\t\(label "[^"]*"\s*\n.*?\n\t\)\n', fix, text, flags=re.S)
    path.write_text(text, encoding="utf-8")


def _tidy_properties(path: Path):
    """Drop the visible 'hierarchy_path' property kicad-sch-api adds, hide every field but Reference and Value."""
    text = path.read_text(encoding="utf-8")
    out, i = [], 0
    for m in re.finditer(r'\(property "([^"]+)"', text):
        if m.start() < i:
            continue
        name, end = m.group(1), _block_end(text, m.start())
        block = text[m.start():end]
        out.append(text[i:m.start()])
        if name == "hierarchy_path":
            out[-1] = out[-1].rstrip(" \t")
            if text[end:end + 1] == "\n":
                end += 1
            block = ""
        elif name not in VISIBLE and "(hide yes)" not in block:
            j = block.find("(effects")
            if j >= 0:
                k = _block_end(block, j)
                block = block[:k - 1] + " (hide yes))" + block[k:]
            else:
                block = block[:-1] + " (effects (font (size 1.27 1.27)) (hide yes)))"
        out.append(block)
        i = end
    out.append(text[i:])
    path.write_text("".join(out), encoding="utf-8")


# ---------- project symbol library ----------

PIN_TYPES = {"power_in", "power_out", "input", "output", "bidirectional", "tri_state", "passive",
             "open_collector", "open_emitter", "no_connect", "unspecified", "free"}


def _f(size: float = 1.27, hide: bool = False) -> str:
    return f"(effects (font (size {size} {size})){' (hide yes)' if hide else ''})"


def symbol_sexpr(name: str, left: list[tuple], right: list[tuple], ref: str = "U", footprint: str = "",
                 datasheet: str = "", description: str = "", width: float = 20.32,
                 top: list[tuple] = (), bottom: list[tuple] = (), pitch: float = 5.08) -> str:
    """Rectangular symbol. left/right: (number, name, pin_type) top to bottom; top/bottom: left to right.

    Put supply pins on top and ground pins at the bottom: their power symbols then stand vertically
    without crossing the side pins (drafting rule 2).
    """
    rows = max(len(left), len(right))
    h = snap((rows + 1) * 2.54 / 2) + 1.27
    name_w = lambda lst: max((len(n) * 1.27 * CHAR_W for _, n, _ in lst), default=0)
    span = max(len(top), len(bottom), 1) * pitch
    width = max(width, snap(name_w(left) + name_w(right) + span + 2.54))
    hw = snap(width / 2)
    pins = []
    for side, lst in ((1, list(top)), (-1, list(bottom))):
        x = -snap((len(lst) - 1) * pitch / 2)
        for number, pname, ptype in lst:
            ptype = ptype if ptype in PIN_TYPES else {"ground": "power_in"}.get(ptype, "passive")
            y = side * (h + 5.08)
            ang = 270 if side > 0 else 90
            pins.append(f'			(pin {ptype} line (at {x:g} {y:g} {ang}) (length 5.08) '
                        f'(name "{pname}" {_f()}) (number "{number}" {_f()}))')
            x = round(x + pitch, 4)
    for side, lst in ((-1, left), (1, right)):
        y = snap((len(lst) - 1) * 2.54 / 2)
        for number, pname, ptype in lst:
            ptype = ptype if ptype in PIN_TYPES else {"ground": "power_in", "open_drain": "open_collector",
                                                      "nc": "no_connect", "analog": "passive"}.get(ptype, "passive")
            x = side * (hw + 5.08)
            ang = 0 if side < 0 else 180
            hide = " hide" if ptype == "no_connect" else ""
            pins.append(f'\t\t\t(pin {ptype} line{hide} (at {x:g} {y:g} {ang}) (length 5.08) '
                        f'(name "{pname}" {_f()}) (number "{number}" {_f()}))')
            y = round(y - 2.54, 4)
    return (f'\t(symbol "{name}" (pin_names (offset 1.016)) (exclude_from_sim no) (in_bom yes) (on_board yes)\n'
            f'\t\t(property "Reference" "{ref}" (at {-hw:g} {h + 1.27:g} 0) (effects (font (size 1.27 1.27)) (justify left)))\n'
            f'\t\t(property "Value" "{name}" (at {-hw:g} {-h - 1.27:g} 0) (effects (font (size 1.27 1.27)) (justify left)))\n'
            f'\t\t(property "Footprint" "{footprint}" (at 0 0 0) {_f(hide=True)})\n'
            f'\t\t(property "Datasheet" "{datasheet}" (at 0 0 0) {_f(hide=True)})\n'
            f'\t\t(property "Description" "{description}" (at 0 0 0) {_f(hide=True)})\n'
            f'\t\t(symbol "{name}_0_1" (rectangle (start {-hw:g} {h:g}) (end {hw:g} {-h:g}) '
            f'(stroke (width 0.254) (type default)) (fill (type background))))\n'
            f'\t\t(symbol "{name}_1_1"\n' + "\n".join(pins) + "\n\t\t)\n\t)\n")


def write_symbol_lib(path: Path, symbols: list[str]):
    Path(path).write_text('(kicad_symbol_lib (version 20241209) (generator "pcb_pipeline") (generator_version "1")\n'
                          + "".join(symbols) + ")\n", encoding="utf-8")


def write_lib_tables(kicad_dir: Path, name: str, footprints: bool = False):
    """Project sym-lib-table (and fp-lib-table) pointing at <name>.kicad_sym / <name>.pretty."""
    d = Path(kicad_dir)
    (d / "sym-lib-table").write_text(
        f'(sym_lib_table\n  (version 7)\n  (lib (name "{name}")(type "KiCad")(uri "${{KIPRJMOD}}/{name}.kicad_sym")(options "")(descr "Project symbols"))\n)\n',
        encoding="utf-8")
    if footprints:
        (d / "fp-lib-table").write_text(
            f'(fp_lib_table\n  (version 7)\n  (lib (name "{name}")(type "KiCad")(uri "${{KIPRJMOD}}/{name}.pretty")(options "")(descr "Project footprints"))\n)\n',
            encoding="utf-8")


# ---------- geometry of library symbols (for field placement and overlap checks) ----------

_LIB_CACHE: dict[str, str] = {}


def _lib_dirs() -> list[Path]:
    import os
    dirs = [Path(p) for p in os.environ.get("KICAD_SYMBOL_DIR", "").split(";") if p]
    dirs += sorted(Path("C:/Program Files/KiCad").glob("*/share/kicad/symbols"), reverse=True)
    dirs += [Path("/usr/share/kicad/symbols"), Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols")]
    return [d for d in dirs if d.exists()]


def _symbol_block(lib_id: str) -> str:
    lib, name = lib_id.split(":", 1)
    if lib not in _LIB_CACHE:
        for d in _lib_dirs():
            f = d / f"{lib}.kicad_sym"
            if f.exists():
                _LIB_CACHE[lib] = f.read_text(encoding="utf-8")
                break
        else:
            _LIB_CACHE[lib] = ""
    text = _LIB_CACHE[lib]
    m = re.search(r'\(symbol "' + re.escape(name) + r'"\s', text)
    if not m:
        return ""
    block = text[m.start():_block_end(text, m.start())]
    ext = re.search(r'\(extends "([^"]+)"\)', block)
    return _symbol_block(f"{lib}:{ext.group(1)}") if ext else block


def symbol_extent(lib_id: str) -> tuple[float, float, float, float]:
    """Library-space box (x0, y0, x1, y1) of the drawing and pins of a symbol (y up)."""
    block = _symbol_block(lib_id)
    body, i = [], 0
    for m in re.finditer(r'\(property "', block):      # drop the property blocks (fields), keep the drawing
        if m.start() < i:
            continue
        body.append(block[i:m.start()])
        i = _block_end(block, m.start())
    body = "".join(body) + block[i:]
    xs, ys = [], []
    for m in re.finditer(r"\((?:xy|start|end|center|mid) ([\-\d.]+) ([\-\d.]+)\)", body):
        xs.append(float(m.group(1)))
        ys.append(float(m.group(2)))
    for m in re.finditer(r"\(circle\s*\(center ([\-\d.]+) ([\-\d.]+)\)\s*\(radius ([\d.]+)\)", body):
        x, y, r = map(float, m.groups())
        xs += [x - r, x + r]
        ys += [y - r, y + r]
    for m in re.finditer(r"\(pin \w+ \w+(?: hide)?\s*\(at ([\-\d.]+) ([\-\d.]+) ([\d.]+)\)\s*\(length ([\d.]+)\)", body):
        x, y, a, length = map(float, m.groups())
        xs += [x, x + length * math.cos(math.radians(a))]
        ys += [y, y + length * math.sin(math.radians(a))]
    if not xs:
        return (-1.27, -1.27, 1.27, 1.27)
    return (min(xs), min(ys), max(xs), max(ys))


def screen_box(lib_id: str, at: tuple[float, float], rotation: float) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = symbol_extent(lib_id)
    pts = [lib_to_screen(p, rotation) for p in ((x0, y0), (x0, y1), (x1, y0), (x1, y1))]
    return (at[0] + min(p[0] for p in pts), at[1] + min(p[1] for p in pts),
            at[0] + max(p[0] for p in pts), at[1] + max(p[1] for p in pts))


CHAR_W = 0.92      # KiCad stroke font advance per character, x text size (measured on KiCad 10 SVG)


def text_box(text: str, at: tuple[float, float], size: float = 1.27, angle: int = 0,
             justify: str = "left", label: str = "") -> tuple[float, float, float, float]:
    """Screen box of a text anchored at `at`. label: '' plain text/field, 'local' or 'global' net label."""
    w = len(text) * size * CHAR_W + (size * 2.2 if label == "global" else 0.3)
    h = size * 1.3
    x, y = at
    if angle in (0, 180):
        if label:                                    # labels: text above the wire, extends away from the anchor
            x0, x1 = (x, x + w) if angle == 0 else (x - w, x)
            return (x0, y - h - 0.3, x1, y + (h / 2 if label == "global" else 0.2))
        x0 = x if justify == "left" else x - w if justify == "right" else x - w / 2
        return (x0, y - h / 2, x0 + w, y + h / 2)
    if label:
        y0, y1 = (y - w, y) if angle == 90 else (y, y + w)
        return (x - h - 0.3, y0, x + (h / 2 if label == "global" else 0.2), y1)
    y0 = y - w if justify == "left" else y if justify == "right" else y - w / 2
    return (x - h / 2, y0, x + h / 2, y0 + w)


def overlaps(boxes: list[tuple[str, tuple[float, float, float, float], str]], margin: float = 0.25):
    """Pairs of named boxes that overlap; boxes with the same owner (third item) are not compared."""
    out = []
    for i in range(len(boxes)):
        na, a, oa = boxes[i]
        for j in range(i + 1, len(boxes)):
            nb, b, ob = boxes[j]
            if oa and oa == ob:
                continue
            if na.startswith("wire") and nb.startswith("wire"):
                continue                                     # wires may cross (no junction, no connection)
            if a[0] < b[2] - margin and b[0] < a[2] - margin and a[1] < b[3] - margin and b[1] < a[3] - margin:
                out.append((na, nb))
    return out
