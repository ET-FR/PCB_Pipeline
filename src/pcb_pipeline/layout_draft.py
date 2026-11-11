"""Phase 3: create the KiCad board from the schematic and the spec, export the design rules, run DRC.

The board is created once (`layout_init`): outline and mounting holes from `spec.mechanical`, every
footprint of the netlist linked to its symbol (so KiCad "Update PCB from Schematic" finds it later),
pads on their nets, footprints grouped and clustered by schematic block (the framed blocks of the
draft), net classes and manufacturer limits in the project file, keepouts in a custom rules file.
After that the user places and routes in KiCad; the pipeline never regenerates the board.

The board is written with KiCad's own Python (`pcbnew`), run as a child process: KiCad ships its
own interpreter, the pipeline does not need to import pcbnew.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- netlist and schematic

_SEXPR_TOKEN = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+')


def parse_sexpr(text: str):
    """Minimal S-expression reader: lists of strings."""
    stack, cur = [], []
    for tok in _SEXPR_TOKEN.findall(text):
        if tok == "(":
            stack.append(cur)
            cur = []
        elif tok == ")":
            done, cur = cur, stack.pop()
            cur.append(done)
        else:
            cur.append(tok[1:-1].replace('\\"', '"') if tok.startswith('"') else tok)
    return cur[0] if cur else []


def _find(node, key):
    return next((x for x in node if isinstance(x, list) and x and x[0] == key), None)


def _findall(node, key):
    return [x for x in node if isinstance(x, list) and x and x[0] == key]


def _val(node, key, default=""):
    x = _find(node, key)
    return x[1] if x and len(x) > 1 and isinstance(x[1], str) else default


@dataclass
class Comp:
    ref: str
    value: str
    footprint: str
    path: str                       # KiCad symbol path, "/<sheet uuids>/<symbol uuid>"
    fields: dict = field(default_factory=dict)
    pads: dict = field(default_factory=dict)   # pad number -> net name
    flags: set = field(default_factory=set)    # exclude_from_bom, dnp, exclude_from_board


def read_netlist(path: Path) -> tuple[dict[str, Comp], list[str]]:
    """KiCad s-expression netlist (kicad-cli sch export netlist --format kicadsexpr)."""
    root = parse_sexpr(Path(path).read_text(encoding="utf-8"))
    comps: dict[str, Comp] = {}
    for c in _findall(_find(root, "components") or [], "comp"):
        sheet = _find(c, "sheetpath")
        sheet_ts = _val(sheet, "tstamps", "/") if sheet else "/"
        ts = next((x[1] for x in _findall(c, "tstamps")), "")
        fields = {}
        for f in _findall(_find(c, "fields") or [], "field"):
            name = _val(f, "name")
            fields[name] = f[2] if len(f) > 2 and isinstance(f[2], str) else ""
        flags = {_val(p, "name") for p in _findall(c, "property")} & {"exclude_from_bom", "dnp",
                                                                       "exclude_from_board"}
        comps[_val(c, "ref")] = Comp(_val(c, "ref"), _val(c, "value"), _val(c, "footprint"),
                                     sheet_ts.rstrip("/") + "/" + ts, fields, flags=flags)
    nets = []
    for n in _findall(_find(root, "nets") or [], "net"):
        name = _val(n, "name")
        nets.append(name)
        for node in _findall(n, "node"):
            ref, pin = _val(node, "ref"), _val(node, "pin")
            if ref in comps:
                comps[ref].pads[pin] = name
    return comps, nets


def schematic_blocks(sch: Path) -> dict[str, str]:
    """Reference -> title of the framed block holding the symbol (dashed rectangles of the draft).

    A block is a rectangle with a text inside its top band; symbols are assigned to the smallest
    rectangle containing them. Parts outside any frame are left out (block "").
    """
    root = parse_sexpr(Path(sch).read_text(encoding="utf-8"))
    rects = []
    for r in _findall(root, "rectangle"):
        (x0, y0), (x1, y1) = (map(float, _find(r, k)[1:3]) for k in ("start", "end"))
        rects.append((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))
    texts = []
    for t in _findall(root, "text"):
        at = _find(t, "at")
        texts.append((t[1], float(at[1]), float(at[2])))
    frames = []
    for x0, y0, x1, y1 in rects:
        title = next((s for s, x, y in texts if x0 <= x <= x1 and y0 <= y <= y0 + 6), None)
        if title:
            frames.append(((x0, y0, x1, y1), title))
    out = {}
    for s in _findall(root, "symbol"):
        at = _find(s, "at")
        ref = next((p[2] for p in _findall(s, "property") if p[1] == "Reference"), "")
        if not at or not ref or ref.startswith("#"):
            continue
        x, y = float(at[1]), float(at[2])
        inside = [(b, t) for b, t in frames if b[0] <= x <= b[2] and b[1] <= y <= b[3]]
        if inside:
            out[ref] = min(inside, key=lambda bt: (bt[0][2] - bt[0][0]) * (bt[0][3] - bt[0][1]))[1]
    return out


# ---------------------------------------------------------------- footprint libraries

def kicad_share(kicad_cli: str) -> Path:
    """C:/Program Files/KiCad/10.0/bin/kicad-cli.exe -> C:/Program Files/KiCad/10.0/share/kicad."""
    return Path(kicad_cli).resolve().parent.parent / "share" / "kicad"


def resolve_footprint(lib_id: str, project_dir: Path, share: Path) -> tuple[Path, str]:
    nick, _, name = lib_id.partition(":")
    table = project_dir / "fp-lib-table"
    if table.exists():
        m = re.search(r'\(lib\s+\(name\s+"?' + re.escape(nick) + r'"?\).*?\(uri\s+"([^"]+)"', table.read_text(
            encoding="utf-8"), re.S)
        if m:
            uri = m.group(1).replace("${KIPRJMOD}", str(project_dir))
            return Path(uri), name
    for env in ("KICAD10_FOOTPRINT_DIR", "KICAD9_FOOTPRINT_DIR"):
        if os.environ.get(env):
            return Path(os.environ[env]) / f"{nick}.pretty", name
    return share / "footprints" / f"{nick}.pretty", name


# ---------------------------------------------------------------- rules

def _bare(net: str) -> str:
    return net.lstrip("/")


def net_settings(spec: dict, nets: list[str]) -> dict:
    """KiCad project `net_settings` from spec.design_rules.net_classes (patterns use the board net names)."""
    dr = spec.get("design_rules", {})
    mf = dr.get("manufacturer", {})
    classes, patterns = [], []
    default = {"track_width_mm": 0.25, "clearance_mm": 0.2}
    for nc in dr.get("net_classes", []):
        if nc.get("name") == "Default":
            default = nc
            continue
        classes.append(_netclass(nc, mf, priority=len(classes)))
        wanted = {_bare(n) for n in nc.get("nets", [])}
        for n in nets:
            if n and _bare(n) in wanted:
                patterns.append({"netclass": nc["name"], "pattern": n})
    classes.append(_netclass({**default, "name": "Default"}, mf, priority=2147483647))
    return {"classes": classes, "meta": {"version": 4}, "net_colors": None, "netclass_assignments": None,
            "netclass_patterns": patterns}


def _netclass(nc: dict, mf: dict, priority: int) -> dict:
    via_d = nc.get("via_diameter_mm", 0.6)
    via_h = max(nc.get("via_drill_mm", 0.3), mf.get("min_drill_mm", 0.3))
    return {"name": nc["name"], "priority": priority, "clearance": nc.get("clearance_mm", 0.2),
            "track_width": nc.get("track_width_mm", 0.25), "via_diameter": via_d, "via_drill": via_h,
            "microvia_diameter": 0.3, "microvia_drill": 0.1, "diff_pair_width": 0.2, "diff_pair_gap": 0.25,
            "diff_pair_via_gap": 0.25, "wire_width": 6, "bus_width": 12, "line_style": 0,
            "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)",
            "tuning_profile": ""}


def write_project_rules(pro: Path, spec: dict, nets: list[str]):
    """Merge net classes and manufacturer minimums into the .kicad_pro (JSON), keeping everything else."""
    data = json.loads(pro.read_text(encoding="utf-8")) if pro.exists() else {"meta": {"version": 3}}
    mf = spec.get("design_rules", {}).get("manufacturer", {})
    board = data.setdefault("board", {})
    ds = board.setdefault("design_settings", {})
    rules = ds.setdefault("rules", {})
    rules.update({"min_track_width": mf.get("min_track_mm", 0.16),
                  "min_clearance": mf.get("min_clearance_mm", 0.16),
                  "min_through_hole_diameter": mf.get("min_drill_mm", 0.3),
                  "min_via_annular_width": mf.get("min_annular_ring_mm", 0.13),
                  "min_hole_to_hole": 0.5, "min_copper_edge_clearance": 0.2,
                  "min_silk_clearance": 0.0, "min_text_height": 0.8, "min_text_thickness": 0.15})
    data["net_settings"] = net_settings(spec, nets)
    pro.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def write_dru(path: Path, spec: dict):
    """Custom rules: copper and parts kept away from isolated mounting holes (metal standoffs).

    Net class widths stay defaults, not minimums: a Kelvin sense pair on a pump net is thin on
    purpose; the current path width is checked by the layout rules of the pipeline.
    """
    mech = spec.get("mechanical", {})
    lines = ["(version 1)", ""]
    holes = [h for h in mech.get("mounting_holes", []) if not h.get("plated", False)]
    if holes:
        lines += ['(rule "Isolated mounting hole, copper keepout"',
                  "\t(condition \"A.Type == 'Pad' && A.memberOfFootprint('H*') && !B.memberOfFootprint('H*')"
                  " && B.Type != 'Footprint' && B.Layer != 'Edge.Cuts'\")",
                  "\t(constraint hole_clearance (min 2mm))",
                  "\t(constraint physical_clearance (min 2mm)))", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------- board creation (runs in KiCad Python)

PCBNEW_SCRIPT = r'''
import json, sys
import pcbnew
job = json.load(open(sys.argv[1], encoding="utf-8"))
mm = pcbnew.FromMM
board = pcbnew.NewBoard(job["out"])
board.SetCopperLayerCount(job["layers"])
ds = board.GetDesignSettings()
ds.SetBoardThickness(mm(job["thickness"]))
nets = {}
for name in job["nets"]:
    if name and name not in nets:
        n = pcbnew.NETINFO_ITEM(board, name)
        board.Add(n)
        nets[name] = n
groups = {}
for c in job["comps"]:
    fp = pcbnew.FootprintLoad(c["lib"], c["name"])
    if fp is None:
        print("MISSING", c["ref"], c["lib"], c["name"]); continue
    fp.SetFPID(pcbnew.LIB_ID(c["nick"], c["name"]))
    fp.SetReference(c["ref"]); fp.SetValue(c["value"])
    fp.SetPath(pcbnew.KIID_PATH(c["path"]))
    fp.SetSheetname("/"); fp.SetSheetfile(job["sheetfile"])
    for k, v in c["fields"].items():
        try:
            fp.SetField(k, v)
            fld = fp.GetField(k)                        # BOM data, not silkscreen
            fld.SetVisible(False)
            fld.SetLayer(pcbnew.F_Fab)
        except Exception as exc:
            print("FIELD", c["ref"], k, exc)
    fp.SetPosition(pcbnew.VECTOR2I(mm(c["x"]), mm(c["y"])))
    fp.SetExcludedFromBOM(c["no_bom"])     # follow the symbol (schematic parity)
    fp.SetDNP(c["dnp"])
    for pad in fp.Pads():
        net = c["pads"].get(pad.GetNumber())
        if net in nets:
            pad.SetNet(nets[net])
    board.Add(fp)
    if c["block"]:
        g = groups.get(c["block"])
        if g is None:
            g = pcbnew.PCB_GROUP(board); g.SetName(c["block"]); board.Add(g); groups[c["block"]] = g
        g.AddItem(fp)
w, h = job["outline"]
edge = pcbnew.PCB_SHAPE(board)
edge.SetShape(pcbnew.SHAPE_T_RECT)
edge.SetStart(pcbnew.VECTOR2I(0, 0)); edge.SetEnd(pcbnew.VECTOR2I(mm(w), mm(h)))
edge.SetLayer(pcbnew.Edge_Cuts); edge.SetWidth(mm(0.1))
board.Add(edge)
for i, hole in enumerate(job["holes"]):
    fp = pcbnew.FootprintLoad(hole["lib"], hole["name"])
    fp.SetReference(f"H{i + 1}"); fp.SetValue("MountingHole")
    fp.SetFPID(pcbnew.LIB_ID("MountingHole", hole["name"]))
    fp.SetPosition(pcbnew.VECTOR2I(mm(hole["x"]), mm(hole["y"])))
    fp.SetLocked(True)
    fp.Reference().SetVisible(False)
    fp.SetBoardOnly(True)          # not in the schematic: no parity error
    board.Add(fp)
board.SetModified()
pcbnew.SaveBoard(job["out"], board)
print("OK", len(job["comps"]), "footprints")
'''


def footprint_size(lib: Path, name: str) -> tuple[float, float, float, float]:
    """Courtyard (or pad) extent of a footprint file, relative to its origin."""
    t = (lib / f"{name}.kicad_mod").read_text(encoding="utf-8")
    xs, ys = [], []
    for m in re.finditer(r'\((?:fp_line|fp_rect|fp_poly)\b(.*?)\(layer "F\.CrtYd"\)', t, re.S):
        for x, y in re.findall(r'\((?:start|end|xy)\s+([-\d.]+)\s+([-\d.]+)\)', m.group(1)):
            xs.append(float(x)); ys.append(float(y))
    for m in re.finditer(r'\(fp_circle\b.*?\(center\s+([-\d.]+)\s+([-\d.]+)\).*?\(end\s+([-\d.]+)\s+([-\d.]+)\)'
                         r'.*?\(layer "F\.CrtYd"\)', t, re.S):
        cx, cy, ex, ey = map(float, m.groups())
        r = ((ex - cx) ** 2 + (ey - cy) ** 2) ** 0.5
        xs += [cx - r, cx + r]; ys += [cy - r, cy + r]
    if not xs:
        for x, y in re.findall(r'\(pad\b[^\n]*?\(at\s+([-\d.]+)\s+([-\d.]+)', t):
            xs.append(float(x)); ys.append(float(y))
        if not xs:
            return (-1, -1, 1, 1)
        return (min(xs) - 1, min(ys) - 1, max(xs) + 1, max(ys) + 1)
    return (min(xs), min(ys), max(xs), max(ys))


def cluster_positions(items: list[tuple[str, str, tuple]], width: float, gap: float = 1.0,
                      block_gap: float = 5.0) -> dict[str, tuple[float, float]]:
    """Shelf-pack parts per block, then the blocks in rows of `width` mm, starting at (0, 0).

    items: (ref, block, extent). Returns the origin of each footprint. A first placement only:
    the user moves the blocks into place in KiCad.
    """
    by_block: dict[str, list] = {}
    for ref, blk, ext in items:
        by_block.setdefault(blk or "~unassigned", []).append((ref, ext))
    clusters = []
    for blk, parts in by_block.items():
        parts.sort(key=lambda p: (-(p[1][3] - p[1][1]), _refkey(p[0])))
        area = sum((e[2] - e[0] + gap) * (e[3] - e[1] + gap) for _, e in parts)
        row_w = max(max(e[2] - e[0] for _, e in parts) + gap, area ** 0.5 * 1.4)
        x = y = row_h = 0.0
        pos, w_used = {}, 0.0
        for ref, e in parts:
            w, h = e[2] - e[0] + gap, e[3] - e[1] + gap
            if x and x + w > row_w:
                x, y, row_h = 0.0, y + row_h, 0.0
            pos[ref] = (x - e[0], y - e[1])
            x += w
            row_h = max(row_h, h)
            w_used = max(w_used, x)
        clusters.append((blk, pos, w_used, y + row_h))
    out, x, y, row_h = {}, 0.0, 0.0, 0.0
    for blk, pos, w, h in clusters:
        if x and x + w > width:
            x, y, row_h = 0.0, y + row_h + block_gap, 0.0
        for ref, (px, py) in pos.items():
            out[ref] = (round(x + px, 3), round(y + py, 3))
        x += w + block_gap
        row_h = max(row_h, h)
    return out


def _refkey(ref: str):
    m = re.match(r"([A-Za-z#]+)(\d*)", ref)
    return (m.group(1), int(m.group(2) or 0)) if m else (ref, 0)


def kicad_python(kicad_cli: str) -> str:
    exe = Path(kicad_cli).resolve().parent / ("python.exe" if os.name == "nt" else "python3")
    return str(exe) if exe.exists() else sys.executable


def layout_init(project_dir: Path, name: str, spec: dict, kicad_cli: str, force: bool = False) -> Path:
    """Create kicad/<name>.kicad_pcb, the project rules and the custom rules. Never overwrites a board."""
    kdir = Path(project_dir)
    pcb = kdir / f"{name}.kicad_pcb"
    if pcb.exists() and not force:
        raise FileExistsError(f"{pcb} exists: the board is the user's now; change it in KiCad")
    sch = kdir / f"{name}.kicad_sch"
    tmp = Path(tempfile.mkdtemp(prefix="pcbpipe_"))
    netfile = tmp / "board.net"
    subprocess.run([kicad_cli, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", str(netfile),
                    str(sch)], check=True, capture_output=True)
    comps, nets = read_netlist(netfile)
    blocks = schematic_blocks(sch)
    share = kicad_share(kicad_cli)
    mech = spec.get("mechanical", {})
    outline = (mech.get("outline", {}).get("width_mm", 100.0), mech.get("outline", {}).get("height_mm", 80.0))
    items, resolved = [], {}
    for ref, c in comps.items():
        if not c.footprint:
            raise ValueError(f"{ref} has no footprint")
        lib, fname = resolve_footprint(c.footprint, kdir, share)
        resolved[ref] = (lib, fname)
        items.append((ref, blocks.get(ref, ""), footprint_size(lib, fname)))
    # first placement: clusters below the outline, so the board area is free for the user
    pos = cluster_positions(items, width=max(outline[0], 150.0))
    job = {"out": str(pcb), "layers": mech.get("stackup", {}).get("layers", 2),
           "thickness": mech.get("thickness_mm", 1.6), "outline": outline, "nets": nets,
           "sheetfile": sch.name, "comps": [], "holes": []}
    for ref, c in sorted(comps.items(), key=lambda kv: _refkey(kv[0])):
        lib, fname = resolved[ref]
        x, y = pos[ref]
        keep = {k: v for k, v in c.fields.items() if v and k not in ("Footprint", "Datasheet", "Description")}
        job["comps"].append({"ref": ref, "value": c.value, "nick": c.footprint.partition(":")[0], "lib": str(lib),
                             "name": fname, "path": c.path, "pads": c.pads, "x": x, "y": outline[1] + 15 + y,
                             "block": blocks.get(ref, ""), "fields": keep,
                             "no_bom": "exclude_from_bom" in c.flags, "dnp": "dnp" in c.flags})
    for h in mech.get("mounting_holes", []):
        d = h.get("diameter_mm", 3.2)
        hname = f"MountingHole_{d:g}mm_M{round(d - 0.2):d}" + ("_Pad" if h.get("plated") else "")
        job["holes"].append({"lib": str(share / "footprints" / "MountingHole.pretty"), "name": hname,
                             "x": h["x_mm"], "y": h["y_mm"]})
    pro = kdir / f"{name}.kicad_pro"
    before = json.loads(pro.read_text(encoding="utf-8")) if pro.exists() else None
    jf = tmp / "job.json"
    jf.write_text(json.dumps(job), encoding="utf-8")
    sf = tmp / "make_board.py"
    sf.write_text(PCBNEW_SCRIPT, encoding="utf-8")
    r = subprocess.run([kicad_python(kicad_cli), str(sf), str(jf)], capture_output=True, text=True)
    if r.returncode != 0 or "OK" not in r.stdout:
        raise RuntimeError(f"board creation failed:\n{r.stdout}\n{r.stderr}")
    missing = [ln for ln in r.stdout.splitlines() if ln.startswith("MISSING")]
    if missing:
        raise RuntimeError("footprints not found:\n" + "\n".join(missing))
    # pcbnew rewrites the project file: keep every setting the project had (schematic, ERC,
    # text variables...), take only the new board section when the project had none
    if before is not None:
        after = json.loads(pro.read_text(encoding="utf-8")) if pro.exists() else {}
        merged = dict(before)
        if "board" not in before and "board" in after:
            merged["board"] = after["board"]
        pro.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    write_project_rules(pro, spec, nets)
    write_dru(kdir / f"{name}.kicad_dru", spec)
    return pcb


def export_rules(kdir: Path, name: str, spec: dict, kicad_cli: str):
    """Re-export net classes, manufacturer minimums and custom rules; the board is not touched."""
    tmp = Path(tempfile.mkdtemp(prefix="pcbpipe_"))
    netfile = tmp / "board.net"
    subprocess.run([kicad_cli, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", str(netfile),
                    str(kdir / f"{name}.kicad_sch")], check=True, capture_output=True)
    _, nets = read_netlist(netfile)
    write_project_rules(kdir / f"{name}.kicad_pro", spec, nets)
    write_dru(kdir / f"{name}.kicad_dru", spec)


# ---------------------------------------------------------------- DRC

def run_drc(pcb: Path, kicad_cli: str, out: Path, parity: bool = True) -> dict:
    """kicad-cli pcb drc, JSON report; with parity, schematic/board mismatches are reported too."""
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [kicad_cli, "pcb", "drc", "--format", "json", "--severity-all", "-o", str(out)]
    if parity:
        cmd.append("--schematic-parity")
    subprocess.run(cmd + [str(pcb)], capture_output=True, text=True)
    return json.loads(out.read_text(encoding="utf-8"))


def drc_summary(report: dict) -> dict[str, int]:
    """Count per violation type, unconnected items and parity issues included."""
    counts: dict[str, int] = {}
    for key in ("violations", "unconnected_items", "schematic_parity"):
        for v in report.get(key, []):
            counts[v.get("type", key)] = counts.get(v.get("type", key), 0) + 1
    return counts
