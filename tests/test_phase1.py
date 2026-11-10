"""Datasheet fetch, spec rendering and spec diff."""

import copy
from pathlib import Path

import yaml

from pcb_pipeline.datasheet.fetch import datasheet_filename, fetch_datasheets
from pcb_pipeline.render import build_sections, render_markdown, render_pdf
from pcb_pipeline.spec import check_spec
from pcb_pipeline.spec_diff import diff_specs, impact, render_impact

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = yaml.safe_load((ROOT / "examples/spec/sensor_node.spec.yaml").read_text(encoding="utf-8"))


def one_part_spec(url):
    spec = copy.deepcopy(EXAMPLE)
    spec["parts"] = [p for p in spec["parts"] if p["id"] == "buck_5v"]
    spec["parts"][0]["datasheet"]["url"] = url
    return spec


def test_filename():
    assert datasheet_filename("TPS62133", "C") == "TPS62133@C.pdf"
    assert datasheet_filename("AB/12 X", None) == "AB-12-X@unknown.pdf"


def test_fetch_downloads_and_indexes(tmp_path):
    src = tmp_path / "remote.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    folder = tmp_path / "datasheets"
    res = fetch_datasheets(one_part_spec(src.as_uri()), folder)
    assert res.downloaded == ["EXAMPLE-BUCK-01"] and not res.missing
    assert (folder / "EXAMPLE-BUCK-01@A.pdf").read_bytes() == b"%PDF-1.4 fake"
    index = yaml.safe_load((folder / "index.yaml").read_text(encoding="utf-8"))
    assert index["datasheets"][0]["file"] == "EXAMPLE-BUCK-01@A.pdf" and len(index["datasheets"][0]["sha256"]) == 64

    # Second run: already present. Then the local PDF changes: reported as changed.
    assert fetch_datasheets(one_part_spec(src.as_uri()), folder).present == ["EXAMPLE-BUCK-01"]
    (folder / "EXAMPLE-BUCK-01@A.pdf").write_bytes(b"%PDF-1.4 new revision")
    assert fetch_datasheets(one_part_spec(src.as_uri()), folder).changed == ["EXAMPLE-BUCK-01"]


def test_fetch_rejects_html_and_lists_missing(tmp_path):
    src = tmp_path / "login.html"
    src.write_text("<html>please log in</html>", encoding="utf-8")
    res = fetch_datasheets(one_part_spec(src.as_uri()), tmp_path / "ds")
    assert res.missing and "did not return a PDF" in res.missing[0]["reason"]
    res = fetch_datasheets(one_part_spec(None), tmp_path / "ds")
    assert res.missing[0]["reason"] == "no URL in the spec"


def test_fetch_registers_manual_drop(tmp_path):
    folder = tmp_path / "ds"
    folder.mkdir()
    (folder / "EXAMPLE-BUCK-01@A.pdf").write_bytes(b"%PDF dropped by hand")
    res = fetch_datasheets(one_part_spec(None), folder, offline=True)
    assert res.present == ["EXAMPLE-BUCK-01"] and not res.missing


def test_render_markdown_and_pdf(tmp_path):
    _, findings, checker = check_spec(EXAMPLE, "sensor_node")
    sections = build_sections(EXAMPLE, checker.currents, findings.to_doc()["findings"])
    md = render_markdown(EXAMPLE, sections)
    assert "## Power tree" in md and "```mermaid" in md
    assert "5v  5 V  [buck buck_5v]  0.370 A / 1 A (37%)" in md      # 0.3 A USB + 0.07 A via the LDO
    assert "| temp_sensor | 0x48 | A0 to GND |  |" in md
    pdf = tmp_path / "spec.pdf"
    render_pdf(EXAMPLE, sections, pdf)
    assert pdf.read_bytes().startswith(b"%PDF")


def test_no_change():
    imp = impact(EXAMPLE, copy.deepcopy(EXAMPLE))
    assert imp.changes == [] and "No change." in render_impact(imp, "a", "b")


def test_prd_change_impact():
    new = copy.deepcopy(EXAMPLE)
    rails = {r["id"]: r for r in new["power_tree"]["rails"]}
    rails["vin"]["max_v"] = 30                                  # PRD now says 24 V systems too
    rails["5v"]["loads"][0]["current"]["max_a"] = 0.9           # bigger USB load
    new["parts"][0]["mpn"] = "EXAMPLE-BUCK-02"                  # buck replaced
    new["buses"][0]["devices"][1]["address"] = "0x41"
    new["project"]["revision"] = "A.2"

    changes = {(c.section, c.key, c.kind) for c in diff_specs(EXAMPLE, new)}
    assert {("rails", "vin", "changed"), ("rails", "5v", "changed"), ("parts", "buck_5v", "changed"),
            ("buses", "i2c1", "changed")} <= changes
    actions = "\n".join(impact(EXAMPLE, new).actions)
    assert "component sheet of buck_5v (EXAMPLE-BUCK-02)" in actions
    assert "schematic symbol of buck_5v (U1)" in actions
    assert "capacitor derating and absolute maximum ratings on net /VIN" in actions
    assert "converters fed by vin: 5v" in actions
    assert "power budget and the source of rail 5v" in actions
    assert "Re-check bus i2c1" in actions
    assert "Bump project.revision" not in actions


def test_revision_not_bumped_is_flagged():
    new = copy.deepcopy(EXAMPLE)
    new["mcu_pins"].append({"part": "mcu", "pin": "PA0", "function": "ADC_IN0"})
    actions = impact(EXAMPLE, new).actions
    assert actions[0].startswith("Bump project.revision")
    assert any("MCU pin assignment" in a for a in actions)
