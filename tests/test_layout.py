"""Phase 3: board creation from a drafted schematic, rules export, layout checks."""

import json
import shutil
from pathlib import Path

import pytest

from pcb_pipeline import layout_check as lc
from pcb_pipeline import layout_draft as ld
from pcb_pipeline import schematic_draft as sd
from pcb_pipeline.findings import Findings
from pcb_pipeline.layout_draft import Comp

KICAD_CLI = shutil.which("kicad-cli") or next(
    (str(p) for p in Path("C:/Program Files/KiCad").glob("*/bin/kicad-cli.exe")), None)

SPEC = {
    "mechanical": {"outline": {"width_mm": 60, "height_mm": 40}, "thickness_mm": 1.6,
                   "mounting_holes": [{"x_mm": 4, "y_mm": 4, "diameter_mm": 3.2, "plated": False}],
                   "stackup": {"layers": 2}},
    "design_rules": {"manufacturer": {"min_track_mm": 0.16, "min_clearance_mm": 0.16, "min_drill_mm": 0.3},
                     "net_classes": [{"name": "Pump", "nets": ["/PUMP_SW", "PUMP_GND"], "track_width_mm": 4.0,
                                      "clearance_mm": 0.3, "max_current_a": 15},
                                     {"name": "Default", "nets": ["*"], "track_width_mm": 0.25,
                                      "clearance_mm": 0.2}]},
}


def test_net_settings_match_board_names():
    ns = ld.net_settings(SPEC, ["/PUMP_SW", "PUMP_GND", "/OTHER"])
    assert [c["name"] for c in ns["classes"]] == ["Pump", "Default"]
    assert {p["pattern"] for p in ns["netclass_patterns"]} == {"/PUMP_SW", "PUMP_GND"}


def test_dru_has_hole_keepout_and_no_width_minimum(tmp_path):
    ld.write_dru(tmp_path / "x.kicad_dru", SPEC)
    t = (tmp_path / "x.kicad_dru").read_text()
    assert "hole_clearance (min 2mm)" in t and "memberOfFootprint('H*')" in t
    assert "track_width" not in t              # class widths are defaults (Kelvin pairs stay thin)


def test_cluster_positions_do_not_overlap():
    items = [(f"R{i}", "a" if i < 5 else "b", (-1, -0.5, 1, 0.5)) for i in range(10)]
    pos = ld.cluster_positions(items, width=20)
    boxes = [(x - 1, y - 0.5, x + 1, y + 0.5) for x, y in pos.values()]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert not (a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3])


def _pad(x, y, net, r=0.5):
    return {"x": x, "y": y, "net": net, "r": r}


def _board(cap_x, esd_x, tracks=()):
    return {"outline": [0, 0, 60, 40], "tracks": list(tracks), "footprints": {
        "U1": {"x": 10, "y": 10, "value": "IC", "pads": {"1": [_pad(10, 10, "+5V")], "2": [_pad(10, 12, "GND")]}},
        "C1": {"x": cap_x, "y": 10, "value": "100n", "pads": {"1": [_pad(cap_x, 10, "+5V")],
                                                           "2": [_pad(cap_x, 11, "GND")]}},
        "J1": {"x": 50, "y": 30, "value": "J", "pads": {"1": [_pad(50, 30, "/SIG")]}},
        "D1": {"x": esd_x, "y": 30, "value": "ESD5Z5.0", "pads": {"1": [_pad(esd_x, 30, "/SIG")],
                                                               "2": [_pad(esd_x, 31, "GND")]}}}}


COMPS = {"U1": Comp("U1", "IC", "", "/1", {}, {"1": "+5V", "2": "GND"}),
         "C1": Comp("C1", "100n", "", "/2", {}, {"1": "+5V", "2": "GND"}),
         "J1": Comp("J1", "J", "", "/3", {}, {"1": "/SIG"}),
         "D1": Comp("D1", "ESD5Z5.0", "", "/4", {"MPN": "ESD5Z5.0T1G"}, {"1": "/SIG", "2": "GND"})}
PINTYPES = {("U1", "1"): "power_in", ("U1", "2"): "power_in"}
BLOCKS = {"U1": "blk", "C1": "blk"}


def _rules(board):
    f = Findings("t")
    lc.check_layout(board, COMPS, PINTYPES, BLOCKS, SPEC, f)
    return {e["rule_id"] for x in f.items for e in x["evidence"]}


def test_decoupling_and_esd_distance():
    assert _rules(_board(cap_x=12, esd_x=48)) == set()
    assert _rules(_board(cap_x=30, esd_x=20)) == {"LAY-DECOUPLING", "LAY-ESD"}


def test_current_path_width_skips_sense_lines():
    thin_power = {"net": "/PUMP_SW", "w": 1.0, "cls": "Pump", "layer": "F.Cu", "a": [30, 20], "b": [40, 20]}
    sense = {"net": "PUMP_GND", "w": 0.25, "cls": "Pump", "layer": "F.Cu", "a": [30, 25], "b": [10, 12]}
    board = _board(12, 48, [thin_power, sense])
    board["footprints"]["U1"]["pads"]["2"][0]["net"] = "PUMP_GND"     # sense line ends on the IC pin
    assert _rules(board) == {"LAY-WIDTH"}
    f = Findings("t")
    lc.check_layout(board, COMPS, PINTYPES, BLOCKS, SPEC, f)
    assert [x["nets"] for x in f.items] == [["/PUMP_SW"]]


@pytest.mark.skipif(not KICAD_CLI, reason="KiCad not installed")
def test_layout_init_from_drafted_schematic(tmp_path):
    prj = sd.Project(tmp_path, "B", power_nets={"GND": "power:GND", "+5V": "power:+5V"}, paper="A4")
    s = prj.page()
    s.block("Load")
    s.part("Device:R", "R1", "1k", (101.6, 60.96), "Resistor_SMD:R_0603_1608Metric", mpn="X")
    s.part("Device:C", "C1", "100n", (114.3, 60.96), "Capacitor_SMD:C_0603_1608Metric", mpn="Y")
    s.pins("R1", {"1": "+5V", "2": "GND"})
    s.pins("C1", {"1": "+5V", "2": "GND"})
    prj.save()
    pro_file = tmp_path / "B.kicad_pro"
    pro0 = json.loads(pro_file.read_text()) if pro_file.exists() else {"meta": {"version": 3}}
    pro0["text_variables"] = {"REV": "A"}                            # a user project setting
    pro_file.write_text(json.dumps(pro0))
    pcb = ld.layout_init(tmp_path, "B", SPEC, KICAD_CLI)
    assert pcb.exists()
    with pytest.raises(FileExistsError):
        ld.layout_init(tmp_path, "B", SPEC, KICAD_CLI)              # never overwrites the user's board
    rep = ld.run_drc(pcb, KICAD_CLI, tmp_path / "drc.json")
    counts = ld.drc_summary(rep)
    assert set(counts) <= {"unconnected_items"}, counts           # schematic parity clean, holes board-only
    pro = json.loads((tmp_path / "B.kicad_pro").read_text())
    assert pro["net_settings"]["classes"][0]["name"] == "Pump"
    assert pro["text_variables"] == {"REV": "A"}                     # kept although pcbnew rewrote the file
    assert ld.schematic_blocks(tmp_path / "B.kicad_sch") == {"R1": "Load", "C1": "Load"}


def test_current_path_width_skips_small_part_branches():
    to_tp = {"net": "/PUMP_SW", "w": 0.5, "cls": "Pump", "layer": "F.Cu", "a": [30, 20], "b": [45, 20]}
    board = _board(12, 48, [to_tp])
    board["footprints"]["TP1"] = {"x": 45, "y": 20, "value": "TP", "pads": {"1": [_pad(45, 20, "/PUMP_SW", 0.75)]}}
    assert _rules(board) == set()
    board["footprints"]["TP1"]["pads"]["1"][0]["r"] = 1.85                # a J3-size pad: real current path
    assert _rules(board) == {"LAY-WIDTH"}
