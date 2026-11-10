"""Schematic drafting: geometry helpers always; a full draft + KiCad ERC/netlist when available."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from pcb_pipeline import schematic_draft as sd


def test_rotation_convention_matches_kicad():
    # Device:R pin 1 at library (0, 3.81): top when unrotated, left after a 90 deg rotation in KiCad
    assert sd.lib_to_screen((0, 3.81), 0) == (0, -3.81)
    assert sd.lib_to_screen((0, 3.81), 90) == (-3.81, 0)
    assert sd.lib_to_screen((0, 3.81), 270) == (3.81, 0)


def test_tidy_and_global_labels(tmp_path):
    f = tmp_path / "s.kicad_sch"
    f.write_text('(kicad_sch\n\t(symbol\n\t\t(property "Reference" "R1"\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n'
                 '\t\t(property "hierarchy_path" "/a/b"\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n'
                 '\t\t(property "MPN" "X"\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n'
                 '\t(sheet_instances\n\t)\n)\n', encoding="utf-8")
    sd._tidy_properties(f)
    sd._inject_global_labels(f, [("SDA", 10.16, 20.32, 180)])
    t = f.read_text(encoding="utf-8")
    assert "hierarchy_path" not in t
    assert re.search(r'"MPN" "X".*?\(hide yes\)', t, re.S)
    assert '(global_label "SDA"' in t and "(justify right)" in t
    assert t.index("global_label") < t.index("sheet_instances")


KICAD_CLI = shutil.which("kicad-cli") or next(
    (str(p) for p in Path("C:/Program Files/KiCad").glob("*/bin/kicad-cli.exe")), None)


@pytest.mark.skipif(not KICAD_CLI, reason="KiCad not installed")
def test_draft_two_sheets_netlist(tmp_path):
    prj = sd.Project(tmp_path, "T", power_nets={"GND": "power:GND", "+5V": "power:+5V"})
    a = prj.sheet("a", "Sheet A")
    a.part("Device:L", "L1", "15uH", (100.33, 100.33), "Inductor_SMD:L_1210_3225Metric", rotation=90, mpn="X")
    a.pins("L1", {"1": "SW", "2": "+5V"})
    a.part("Device:R", "R1", "1k", (120.65, 100.33), "Resistor_SMD:R_0603_1608Metric", mpn="X")
    a.pins("R1", {"1": "+5V", "2": "SIG"})
    b = prj.sheet("b", "Sheet B")
    b.part("Device:R", "R2", "1k", (100.33, 100.33), "Resistor_SMD:R_0603_1608Metric", mpn="X")
    b.pins("R2", {"1": "SIG", "2": "GND"})
    prj.save()
    net = tmp_path / "n.net"
    subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", str(net),
                    str(tmp_path / "T.kicad_sch")], check=True, capture_output=True)
    t = net.read_text(encoding="utf-8")
    nets = {m.group(1): set(re.findall(r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"\)', m.group(2)))
            for m in re.finditer(r'\(net\s+\(code "?\d+"?\)\s+\(name "([^"]+)"\)(.*?)\n\s*\)\s*(?=\(net|\))', t, re.S)}
    assert nets["+5V"] == {("L1", "2"), ("R1", "1")}                  # rotated part: pins not swapped
    assert nets["SIG"] == {("R1", "2"), ("R2", "1")}                 # global label across sheets
    assert any(("L1", "1") in v for k, v in nets.items() if k.endswith("SW"))


def test_label_justify_follows_angle(tmp_path):
    f = tmp_path / "s.kicad_sch"
    f.write_text('(kicad_sch\n\t(label "A"\n\t\t(at 10 10 180)\n\t\t(effects\n\t\t\t(justify left bottom)\n\t\t)\n\t)\n'
                 '\t(label "B"\n\t\t(at 10 20 0)\n\t\t(effects\n\t\t\t(justify left bottom)\n\t\t)\n\t)\n)\n', encoding="utf-8")
    sd._fix_label_justify(f)
    t = f.read_text(encoding="utf-8")
    assert t.index("justify right bottom") < t.index('"B"') < t.index("justify left bottom")


def test_overlap_and_text_boxes():
    a = sd.text_box("12V_FRONT", (10, 10), 1.27, 0, "center")
    b = sd.text_box("12V_FRONT", (20.16, 10), 1.27, 0, "center")
    c = sd.text_box("12V_FRONT", (22.7, 10), 1.27, 0, "center")
    assert sd.overlaps([("a", a, "1"), ("b", b, "2")])            # 10.16 mm pitch is too tight for 9 chars
    assert not sd.overlaps([("a", a, "1"), ("c", c, "2")])
    assert not sd.overlaps([("a", a, "1"), ("b", b, "1")])        # same owner is not compared


@pytest.mark.skipif(not KICAD_CLI, reason="KiCad not installed")
def test_flat_page_power_symbols_vertical_and_global_consistency(tmp_path):
    prj = sd.Project(tmp_path, "F", power_nets={"GND": "power:GND", "+5V": "power:+5V"}, paper="A4")
    s = prj.page()
    s.part("Connector_Generic:Conn_01x02", "J1", "J", (50.8, 50.8), "", fields="right")
    s.pins("J1", {"1": "+5V", "2": "SIG"}, labels=("2",))            # SIG global on the connector
    s.part("Device:R", "R1", "1k", (101.6, 50.8), "Resistor_SMD:R_0603_1608Metric")
    s.pins("R1", {"1": "SIG", "2": "GND"})                           # ... so global here too
    prj.save()
    t = (tmp_path / "F.kicad_sch").read_text(encoding="utf-8")
    assert t.count('(global_label "SIG"') == 2 and '(label "SIG"' not in t
    rots = re.findall(r'\(lib_id "power:(?:\+5V|GND)"\)\s*\(at [\d.\-]+ [\d.\-]+ (\d+)\)', t)
    assert rots and all(r in ("0", "180") for r in rots)              # vertical power symbols only
    assert not prj.issues()
