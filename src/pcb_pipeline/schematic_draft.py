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


@dataclass
class Sheet:
    project: "Project"
    name: str
    title: str
    page: int
    sch: object = None
    conns: list[Conn] = field(default_factory=list)
    sheet_uuid: str = ""

    def part(self, lib_id: str, ref: str, value: str, at: tuple[float, float], footprint: str = "",
             rotation: float = 0, mpn: str = "", **fields_):
        c = self.sch.components.add(lib_id, reference=ref, value=value, position=(snap(at[0]), snap(at[1])),
                                    footprint=footprint, rotation=rotation)
        props = {"MPN": mpn, **{k.replace("_", " "): v for k, v in fields_.items()}}
        for k, v in props.items():
            if v:
                c.set_property(k, str(v))
        return c

    def connect(self, ref: str, pin: str | int, net: str):
        self.conns.append(Conn(ref, str(pin), net.lstrip("/")))

    def pins(self, ref: str, mapping: dict):
        for pin, net in mapping.items():
            if net is None:
                self.nc(ref, pin)
            else:
                self.connect(ref, pin, net)

    def nc(self, ref: str, pin: str | int):
        self.conns.append(Conn(ref, str(pin), None))

    def note(self, text: str, at: tuple[float, float], size: float = 1.27):
        self.sch.add_text(text, (snap(at[0]), snap(at[1])), size=size)

    # ---- drawing ----
    def _outward(self, ref: str, pin: str) -> tuple[tuple[float, float], tuple[float, float]]:
        comp = self.sch.components.get(ref)
        sym = ksa.get_symbol_info(comp.lib_id)
        sp = next(p for p in sym.pins if p.number == pin)
        d = (-math.cos(math.radians(sp.rotation)), -math.sin(math.radians(sp.rotation)))
        rot = comp.rotation or 0
        out = lib_to_screen(d, rot)
        off = lib_to_screen((sp.position.x, sp.position.y), rot)
        pos = (round(comp.position.x + off[0], 4), round(comp.position.y + off[1], 4))
        return pos, (round(out[0]), round(out[1]))

    def draw(self, power: set[str], globals_: set[str], power_lib: dict[str, str]):
        globals_out = []
        for c in self.conns:
            (px, py), (dx, dy) = self._outward(c.ref, c.pin)
            if c.net is None:
                self.sch.no_connects.add(position=(px, py)) if hasattr(self.sch.no_connects, "add") else None
                continue
            ex, ey = snap(px + dx * STUB), snap(py + dy * STUB)
            self.sch.add_wire((px, py), (ex, ey))
            if c.net in power:
                self.project.pwr += 1
                lib = power_lib.get(c.net) or ("power:GND" if c.net.upper().endswith("GND") else "power:VCC")
                body = (0, 1) if lib in ("power:GND", "power:GNDPWR", "power:GNDA", "power:GNDD") else (0, -1)
                rot = next(a for a in (0, 90, 180, 270) if tuple(round(x) for x in _rot(body, -a)) == (dx, dy))
                self.sch.components.add(lib, reference=f"#PWR{self.project.pwr:03d}", value=c.net,
                                        position=(ex, ey), rotation=rot)
            else:
                rot = {(1, 0): 0, (0, -1): 90, (-1, 0): 180, (0, 1): 270}[(dx, dy)]
                if c.net in globals_:
                    globals_out.append((c.net, ex, ey, rot))
                else:
                    self.sch.add_label(c.net, position=(ex, ey), rotation=rot)
        return globals_out


class Project:
    """A KiCad project drafted as a root sheet plus one sheet per block."""

    def __init__(self, kicad_dir: Path, name: str, power_nets: dict[str, str] | None = None):
        self.dir = Path(kicad_dir)
        self.name = name
        self.root = ksa.create_schematic(name)
        self.sheets: list[Sheet] = []
        self.power_lib = dict(power_nets or {})       # net -> power symbol lib id
        self._pos = 0
        self.pwr = 0

    def sheet(self, name: str, title: str) -> Sheet:
        page = len(self.sheets) + 2
        x, y = 30.48 + (self._pos % 4) * 60.96, 40.64 + (self._pos // 4) * 35.56
        self._pos += 1
        sid = self.root.add_sheet(title, f"{name}.kicad_sch", (x, y), (45.72, 20.32),
                                  project_name=self.name, page_number=str(page))
        sch = ksa.create_schematic(title)
        sch.set_hierarchy_context(self.root.uuid, sid)
        s = Sheet(self, name, title, page, sch, sheet_uuid=sid)
        self.sheets.append(s)
        return s

    def save(self) -> list[Path]:
        self.dir.mkdir(parents=True, exist_ok=True)
        uses: dict[str, set[str]] = {}
        for s in self.sheets:
            for c in s.conns:
                if c.net:
                    uses.setdefault(c.net, set()).add(s.name)
        power = set(self.power_lib)
        globals_ = {n for n, sh in uses.items() if len(sh) > 1 and n not in power}
        written = []
        for s in self.sheets:
            gl = s.draw(power, globals_, self.power_lib)
            path = self.dir / f"{s.name}.kicad_sch"
            s.sch.save(str(path))
            _inject_global_labels(path, gl)
            _tidy_properties(path)
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
