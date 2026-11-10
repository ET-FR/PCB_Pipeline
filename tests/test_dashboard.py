"""KiCad file reading (positions for highlighting) and dashboard generation."""

import json
import re
from pathlib import Path

import pytest
import yaml

from pcb_pipeline.dashboard import _sheet_svg, build_data, write_dashboard
from pcb_pipeline.kicad_files import paper_size, parse_sexpr, read_board, read_schematic
from pcb_pipeline.template import init_project

ROOT = Path(__file__).resolve().parents[1]
KICAD = ROOT / "tests/fixtures/kicad"


def approx(box, expected, tol=0.01):
    return all(abs(a - b) <= tol for a, b in zip(box, expected))


def test_parse_sexpr_strings_and_escapes():
    tree = parse_sexpr('(a "b c" (d 1.5) "e \\"q\\"")')
    assert tree == ["a", "b c", ["d", "1.5"], 'e "q"']


def test_paper_sizes():
    assert paper_size(parse_sexpr('(kicad_sch (paper "A4"))')) == (297, 210)
    assert paper_size(parse_sexpr('(kicad_sch (paper "A3" portrait))')) == (297, 420)
    assert paper_size(parse_sexpr('(kicad_sch (paper "User" 100 80))')) == (100, 80)


def test_schematic_hierarchy_and_positions():
    sheets = read_schematic(KICAD / "mini.kicad_sch")
    assert [s.name for s in sheets] == ["", "power"]
    root, power = sheets
    refs = {i.ref: i for i in root.items}
    assert set(refs) == {"U1", "U2"}                       # power symbols skipped
    # U1 at (100, 50): body -5..5 x -2..2 plus the pin from x = -7.62, margin 0.6
    assert approx(refs["U1"].bbox, (100 - 7.62 - 0.6, 50 - 2 - 0.6, 100 + 5 + 0.6, 50 + 2 + 0.6))
    assert refs["U1"].mpn == "EXAMPLE-BUCK-01"
    # U2 rotated 90 degrees: the box becomes 4 wide and the pin goes down (KiCad y axis points down)
    x0, y0, x1, y1 = refs["U2"].bbox
    assert approx((x1 - x0, y1 - y0), (4 + 1.2, 12.62 + 1.2))
    assert y1 > 80 + 7                                      # pin end below the anchor
    # sub-sheet: reference from the instance path, mirror, page in portrait, DNP
    u3 = power.items[0]
    assert u3.ref == "U3" and u3.dnp and power.page == (297, 420)
    assert approx(u3.bbox, (20 - 5.6, 30 - 2.6, 20 + 5.6, 30 + 2.6))


def test_board_positions():
    page, items = read_board(KICAD / "mini.kicad_pcb")
    assert page == (297, 210)
    refs = {i.ref: i for i in items}
    # R1 rotated 90: pads at (-1, 0) and (1, 0) end up above and below (20, 30)
    x0, y0, x1, y1 = refs["R1"].bbox
    assert approx(((x0 + x1) / 2, (y0 + y1) / 2), (20, 30)) and (y1 - y0) > (x1 - x0)
    assert refs["U1"].side == "back" and refs["U1"].dnp and refs["U1"].mpn == "EXAMPLE-BUCK-01"


def test_sheet_svg_names(tmp_path):
    svgs = [tmp_path / n for n in ("mini.svg", "mini-power.svg", "mini-My sheet.svg")]
    assert _sheet_svg(svgs, "mini", "") == svgs[0]
    assert _sheet_svg(svgs, "mini", "power") == svgs[1]
    assert _sheet_svg(svgs, "mini", "My sheet") == svgs[2]


@pytest.fixture
def project(tmp_path):
    init_project(tmp_path / "board", "mini")
    root = tmp_path / "board"
    (root / "design/spec.yaml").write_text((ROOT / "examples/spec/sensor_node.spec.yaml").read_text())
    for f in KICAD.glob("*"):
        (root / "kicad" / f.name).write_text(f.read_text())
    (root / "datasheets/EXAMPLE-BUCK-01@A.pdf").write_bytes(b"%PDF-1.4")
    (root / "datasheets/index.yaml").write_text(yaml.safe_dump({"datasheets": [
        {"mpn": "EXAMPLE-BUCK-01", "file": "EXAMPLE-BUCK-01@A.pdf", "revision": "A"}]}))
    return root


def test_dashboard_data_without_kicad(project, tmp_path):
    data = build_data(project, tmp_path / "out", use_kicad=False, library_dirs=[ROOT / "examples/component_sheets"])
    assert data["project"]["name"] == "sensor_node" and data["project"]["kicad_project"] == "mini"
    assert [p["status"] for p in data["phases"]][:3] == ["todo", "in_progress", "in_progress"]
    assert [s["name"] for s in data["schematic"]] == ["root", "power"]
    assert {i["ref"] for i in data["board"]["items"]} == {"R1", "U1"}
    assert 'data-rail="5v"' in data["power_tree_svg"]
    buck = next(d for d in data["datasheets"] if d["mpn"] == "EXAMPLE-BUCK-01")
    assert buck["pdf"].endswith("datasheets/EXAMPLE-BUCK-01@A.pdf") and buck["sheet"] and buck["score"] == 9
    # spec findings are mapped to KiCad references through parts[].ref (ldo_3v3 -> U3)
    ldo = next(f for f in data["findings"] if f["title"].startswith("LDO '3v3'"))
    assert "U3" in ldo["kicad_refs"]


def test_gate_and_decision(project, tmp_path):
    (project / "review/gates.yaml").write_text(yaml.safe_dump({"gates": [
        {"id": "architecture_review", "passed": "2026-11-10", "revision": "A.1"}]}))
    data = build_data(project, tmp_path / "out", use_kicad=False)
    arch = next(p for p in data["phases"] if p["id"] == "architecture")
    assert arch["status"] == "done" and "2026-11-10" in arch["gate_passed"]


def test_write_dashboard(project, tmp_path):
    index = write_dashboard(project, tmp_path / "dash", use_kicad=False)
    page = index.read_text()
    assert "<title>sensor_node" in page
    data = json.loads(re.search(r"const D = (.*?);\n", page).group(1))
    assert data["project"]["name"] == "sensor_node"
    assert "/*__DATA__*/" not in page
