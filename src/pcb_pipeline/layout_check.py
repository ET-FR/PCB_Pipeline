"""Phase 3 layout checks: KiCad DRC plus placement and current-path rules from the spec.

The board is read with KiCad's own Python (positions of pads and tracks), the netlist and the
schematic blocks give the intent. Every finding cites its rule and the measured value.

Rules (parameters in `LayoutRules`):
- LAY decoupling: a capacitor of a block, between a supply pin net of an IC of the same block
  and a ground, sits within `decoupling_mm` of that IC supply pin.
- LAY esd: an ESD diode sharing a net with a connector pin sits within `esd_mm` of that pin.
- LAY width: a track of a net class with `max_current_a` is at least the class width, except
  the track chains that end on an IC pin (sense lines such as a shunt Kelvin pair).
- LAY placement: parts still outside the board outline (info, placement progress).
- DRC: the KiCad DRC violations, grouped by type.
"""

from __future__ import annotations

import json
import math
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .findings import Findings
from .layout_draft import drc_summary, kicad_python, read_netlist, run_drc, schematic_blocks

DUMP_SCRIPT = r'''
import json, sys
import pcbnew
b = pcbnew.LoadBoard(sys.argv[1])
to = pcbnew.ToMM
bb = b.GetBoardEdgesBoundingBox()
out = {"outline": [to(bb.GetLeft()), to(bb.GetTop()), to(bb.GetRight()), to(bb.GetBottom())],
       "footprints": {}, "tracks": [], "classes": {}}
for fp in b.GetFootprints():
    pads = {}
    for p in fp.Pads():
        pos, size = p.GetPosition(), p.GetBoundingBox()
        pads.setdefault(p.GetNumber(), []).append({"x": to(pos.x), "y": to(pos.y), "net": p.GetNetname(),
                                                   "r": to(max(size.GetWidth(), size.GetHeight())) / 2})
    pos = fp.GetPosition()
    out["footprints"][fp.GetReference()] = {"x": to(pos.x), "y": to(pos.y), "pads": pads,
                                            "value": fp.GetValue()}
for t in b.GetTracks():
    if t.GetClass() != "PCB_TRACK":
        continue
    s, e = t.GetStart(), t.GetEnd()
    out["tracks"].append({"net": t.GetNetname(), "w": to(t.GetWidth()), "layer": t.GetLayerName(),
                          "a": [to(s.x), to(s.y)], "b": [to(e.x), to(e.y)], "cls": t.GetNetClassName()})
json.dump(out, open(sys.argv[2], "w", encoding="utf-8"))
'''


@dataclass
class LayoutRules:
    decoupling_mm: float = 5.0      # capacitor pad to the IC supply pin it decouples
    esd_mm: float = 15.0            # ESD diode pad to the connector pin it protects


def read_board(pcb: Path, kicad_cli: str) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="pcbpipe_"))
    script, out = tmp / "dump.py", tmp / "board.json"
    script.write_text(DUMP_SCRIPT, encoding="utf-8")
    r = subprocess.run([kicad_python(kicad_cli), str(script), str(pcb), str(out)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"board read failed:\n{r.stderr}")
    return json.loads(out.read_text(encoding="utf-8"))


def _is_ground(net: str) -> bool:
    return net.lstrip("/").upper().endswith("GND")


def _dist(a, b) -> float:
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def _inside(fp, outline) -> bool:
    x0, y0, x1, y1 = outline
    return x0 <= fp["x"] <= x1 and y0 <= fp["y"] <= y1


def check_layout(board: dict, comps: dict, pintypes: dict, blocks: dict, spec: dict, findings: Findings,
                 rules: LayoutRules = LayoutRules()):
    fps, outline = board["footprints"], board["outline"]
    placed = {r for r, fp in fps.items() if _inside(fp, outline) and not r.startswith("H")}
    # ---- placement progress
    unplaced = sorted(r for r in comps if r in fps and r not in placed)
    if unplaced:
        findings.add("LAY", "info", f"{len(unplaced)} of {len(comps)} parts not on the board yet", unplaced[:40],
                     [{"kind": "rule", "rule_id": "LAY-PLACEMENT",
                       "summary": f"footprint origin outside the outline {outline}"}], "layout")
    # ---- decoupling
    for cref, c in comps.items():
        if not cref.startswith("C") or cref not in placed or len(c.pads) != 2:
            continue
        nets = set(c.pads.values())
        if not any(_is_ground(n) for n in nets):
            continue
        supply = next((n for n in nets if not _is_ground(n)), None)
        blk = blocks.get(cref)
        ics = [u for u in comps if u.startswith("U") and blocks.get(u) == blk and u in placed]
        best = None
        for u in ics:
            for num, net in comps[u].pads.items():
                if net != supply or pintypes.get((u, num)) not in ("power_in", "power_out"):
                    continue
                for up in fps[u]["pads"].get(num, []):
                    for cp in (p for ps in fps[cref]["pads"].values() for p in ps if p["net"] == supply):
                        d = _dist(up, cp)
                        if best is None or d < best[0]:
                            best = (d, u, num)
        if best and best[0] > rules.decoupling_mm:
            d, u, num = best
            findings.add("LAY", "major", f"{cref} is {d:.1f} mm from {u} pin {num} ({supply})", [cref, u],
                         [{"kind": "calculation", "rule_id": "LAY-DECOUPLING", "net": supply,
                           "calculation": f"pad to pad {d:.2f} mm > {rules.decoupling_mm} mm"}], "layout",
                         block=blk, nets=[supply],
                         suggestion=f"move {cref} next to {u} pin {num}, short loop to its ground pin")
    # ---- ESD at the connector
    for dref, d in comps.items():
        if not dref.startswith("D") or dref not in placed:
            continue
        mpn = d.fields.get("MPN", "") + " " + d.value
        if "ESD" not in mpn.upper():
            continue
        sig = next((n for n in d.pads.values() if not _is_ground(n)), None)
        best = None
        for jref, j in comps.items():
            if not jref.startswith("J") or jref not in placed:
                continue
            for num, net in j.pads.items():
                if net != sig:
                    continue
                for jp in fps[jref]["pads"].get(num, []):
                    for dp in (p for ps in fps[dref]["pads"].values() for p in ps if p["net"] == sig):
                        dist = _dist(jp, dp)
                        if best is None or dist < best[0]:
                            best = (dist, jref, num)
        if best and best[0] > rules.esd_mm:
            dist, jref, num = best
            findings.add("LAY", "major", f"ESD {dref} is {dist:.1f} mm from {jref} pin {num} ({sig})", [dref, jref],
                         [{"kind": "calculation", "rule_id": "LAY-ESD", "net": sig,
                           "calculation": f"pad to pad {dist:.2f} mm > {rules.esd_mm} mm"}], "layout",
                         nets=[sig], suggestion=f"place {dref} at {jref}, before any other part on {sig}")
    # ---- current path width
    classes = {nc["name"]: nc for nc in spec.get("design_rules", {}).get("net_classes", []) if nc.get("max_current_a")}
    ic_pads = [(p, u) for u, fp in fps.items() if u.startswith("U") for ps in fp["pads"].values() for p in ps]
    by_net: dict[str, list] = {}
    for t in board["tracks"]:
        if t["cls"] in classes:
            by_net.setdefault(t["net"], []).append(t)
    for net, tracks in by_net.items():
        for chain in _chains(tracks):
            ends = [pt for t in chain for pt in (t["a"], t["b"])]
            if any(math.hypot(x - p["x"], y - p["y"]) <= p["r"] + 0.05 and p["net"] == net
                   for x, y in ends for p, _ in ic_pads):
                continue                                # sense line to an IC pin (Kelvin pair)
            nc = classes[chain[0]["cls"]]
            thin = [t for t in chain if t["w"] + 1e-6 < nc["track_width_mm"]]
            if thin:
                w = min(t["w"] for t in thin)
                findings.add("LAY", "major", f"{net}: track {w:.2f} mm in the {nc['name']} path "
                             f"(class {nc['track_width_mm']} mm, {nc['max_current_a']} A)", ["board"],
                             [{"kind": "spec", "rule_id": "LAY-WIDTH", "net": net,
                               "spec_path": f"design_rules/net_classes/{nc['name']}",
                               "summary": f"{len(thin)} segment(s) narrower than the class width"}], "layout",
                             nets=[net], suggestion="widen the tracks or use a pour on this net")


def _chains(tracks: list[dict]) -> list[list[dict]]:
    """Connected groups of track segments (shared end points)."""
    key = lambda p: (round(p[0], 3), round(p[1], 3))
    parent = list(range(len(tracks)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    at: dict[tuple, int] = {}
    for i, t in enumerate(tracks):
        for p in (t["a"], t["b"]):
            k = key(p)
            if k in at:
                parent[find(i)] = find(at[k])
            else:
                at[k] = i
    groups: dict[int, list] = {}
    for i, t in enumerate(tracks):
        groups.setdefault(find(i), []).append(t)
    return list(groups.values())


def add_drc(report: dict, findings: Findings):
    """One finding per DRC violation type; errors are major, warnings minor. Unrouted nets are info."""
    by_type: dict[str, list] = {}
    for v in report.get("violations", []) + report.get("schematic_parity", []):
        by_type.setdefault(v["type"], []).append(v)
    for typ, vs in sorted(by_type.items()):
        sev = "major" if any(v.get("severity") == "error" for v in vs) else "minor"
        refs = sorted({i["description"].split()[-1] for v in vs for i in v.get("items", [])
                       if i.get("description", "").startswith("Footprint ")}) or ["board"]
        findings.add("DRC", sev, f"{len(vs)} x {vs[0]['description']}", refs[:20],
                     [{"kind": "rule", "rule_id": f"KICAD-DRC-{typ}", "summary": vs[0]["description"]}], "layout")
    n = len(report.get("unconnected_items", []))
    if n:
        findings.add("DRC", "info", f"{n} connections not routed yet", ["board"],
                     [{"kind": "rule", "rule_id": "KICAD-DRC-unconnected_items", "summary": "ratsnest left"}],
                     "layout")


def run_layout_check(kdir: Path, name: str, spec: dict, kicad_cli: str, out: Path,
                     rules: LayoutRules = LayoutRules()) -> dict:
    pcb, sch = kdir / f"{name}.kicad_pcb", kdir / f"{name}.kicad_sch"
    out.mkdir(parents=True, exist_ok=True)
    netfile = out / "board.net"
    subprocess.run([kicad_cli, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", str(netfile), str(sch)],
                   check=True, capture_output=True)
    comps, _ = read_netlist(netfile)
    pintypes = _pintypes(netfile)
    board = read_board(pcb, kicad_cli)
    findings = Findings(name)
    check_layout(board, comps, pintypes, schematic_blocks(sch), spec, findings, rules)
    report = run_drc(pcb, kicad_cli, out / "drc.json")
    add_drc(report, findings)
    doc = findings.to_doc()
    (out / "layout_findings.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"doc": doc, "drc": drc_summary(report)}


def _pintypes(netfile: Path) -> dict:
    from .layout_draft import _find, _findall, _val, parse_sexpr
    root = parse_sexpr(netfile.read_text(encoding="utf-8"))
    out = {}
    for n in _findall(_find(root, "nets") or [], "net"):
        for node in _findall(n, "node"):
            out[(_val(node, "ref"), _val(node, "pin"))] = _val(node, "pintype")
    return out
