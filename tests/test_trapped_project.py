"""The trapped project must trigger every deterministic rule exactly where expected."""

from pathlib import Path

import pytest

from pcb_pipeline.datasheet.library import SheetLibrary
from pcb_pipeline.findings import Findings
from pcb_pipeline.kicad_import import parse_netlist_xml
from pcb_pipeline.netlist import functional_groups
from pcb_pipeline.rules.engine import RuleEngine, load_rules

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def result():
    netlist = parse_netlist_xml(ROOT / "tests/fixtures/buck_trapped.xml")
    lib = SheetLibrary(ROOT / "examples/component_sheets")
    f = Findings("buck_trapped")
    RuleEngine(netlist, lib, f, load_rules(), rails={"/VIN": 12.0, "/+5V": 5.0}).run()
    return netlist, f.to_doc()["findings"]


def titles(findings):
    return [x["title"] for x in findings]


def test_floating_enable(result):
    _, findings = result
    assert "U1.EN is floating" in titles(findings)


def test_capacitor_derating(result):
    _, findings = result
    c1 = [x for x in findings if x["refs"] == ["C1"]]
    assert c1 and c1[0]["severity"] == "critical"  # 10 V part on a 12 V rail

def test_feedback_divider(result):
    _, findings = result
    eq = [x for x in findings if x["id"].startswith("EQ-")]
    assert len(eq) == 1
    assert "R1" in eq[0]["refs"] and "R2" in eq[0]["refs"]


def test_missing_mpn(result):
    _, findings = result
    assert "U2 has no MPN field" in titles(findings)


def test_every_finding_has_evidence(result):
    _, findings = result
    assert all(f["evidence"] for f in findings)


def test_functional_groups(result):
    netlist, _ = result
    groups = {g["id"]: g for g in functional_groups(netlist)}
    assert {"C1", "C3", "L1", "R1", "R2"} <= set(groups["U1"]["members"])
    assert "U2" in groups["U1"]["boundary"]
