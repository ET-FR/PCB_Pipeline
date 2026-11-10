"""The example spec must be clean; the trapped spec must trigger every spec rule."""

from pathlib import Path

import pytest
import yaml

from pcb_pipeline.rules.engine import load_rules
from pcb_pipeline.spec import check_spec, spec_rails

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = yaml.safe_load((ROOT / "examples/spec/sensor_node.spec.yaml").read_text(encoding="utf-8"))
TRAPPED = yaml.safe_load((ROOT / "tests/fixtures/spec_trapped.yaml").read_text(encoding="utf-8"))


def run(spec):
    errors, findings, _ = check_spec(spec, "test", load_rules())
    assert errors == []
    return findings.to_doc()["findings"]


def rule_ids(findings):
    return {e["rule_id"] for f in findings for e in f["evidence"] if e.get("rule_id")}


def test_example_spec_is_clean():
    findings = run(EXAMPLE)
    assert [f["severity"] for f in findings] == ["info"]           # LDO dissipation only
    assert "0.13 W" in findings[0]["title"]                        # (5.1 - 3.3) x 0.07 A


@pytest.fixture(scope="module")
def trapped():
    return run(TRAPPED)


def test_i2c_conflict(trapped):
    f = next(f for f in trapped if "I2C address conflict" in f["title"])
    assert f["severity"] == "critical" and set(f["refs"]) == {"temp_sensor", "humidity_sensor"}


def test_unknown_part(trapped):
    assert any("unknown part 'eeprom'" in f["title"] for f in trapped)


def test_mcu_pin_twice(trapped):
    assert any("PA9" in f["title"] and f["severity"] == "critical" for f in trapped)


def test_ldo_overloaded(trapped):
    f = next(f for f in trapped if f["title"] == "rail '3v3' is overloaded")
    assert "0.370 A vs capacity 0.300 A" in f["evidence"][0]["calculation"]


def test_buck_margin(trapped):
    f = next(f for f in trapped if f["title"].startswith("rail '5v' load above 80%"))
    assert "0.870 A" in f["evidence"][0]["calculation"]


def test_every_spec_rule_has_a_trap(trapped):
    assert {"SPEC-001", "BUS-001", "MCU-001", "PWR-001", "PWR-002"} <= rule_ids(trapped)


def test_power_tree_loop_is_reported():
    spec = yaml.safe_load((ROOT / "examples/spec/sensor_node.spec.yaml").read_text(encoding="utf-8"))
    vin = spec["power_tree"]["rails"][0]
    vin["source"] = {"type": "buck", "from_rail": "3v3"}
    assert any(f["title"] == "power tree has a loop" for f in run(spec))


def test_schema_error_is_returned():
    errors, _, _ = check_spec({"schema_version": 1}, "bad")
    assert errors


def test_rails_for_rule_engine():
    assert spec_rails(EXAMPLE) == {"/VIN": 14, "/+5V": 5.1, "/+3V3": 3.4}


# Ratings against component sheets --------------------------------------------------

from pcb_pipeline.datasheet.library import SheetLibrary  # noqa: E402

LIB = SheetLibrary(ROOT / "examples/component_sheets", ROOT / "tests/fixtures/component_sheets")


def run_with_library(spec):
    errors, findings, _ = check_spec(spec, "test", load_rules(), LIB)
    assert errors == []
    return findings.to_doc()["findings"]


def test_trapped_ratings():
    findings = run_with_library(TRAPPED)
    by_rule = {e["rule_id"]: f for f in findings for e in f["evidence"] if e.get("rule_id")}
    assert by_rule["RAT-001"]["severity"] == "critical"          # 40 V transient > 18 V absolute max
    assert "40 V > absolute max 18 V" in by_rule["RAT-001"]["evidence"][1]["calculation"]
    assert by_rule["RAT-001"]["evidence"][0] == {"kind": "datasheet", "mpn": "EXAMPLE-BUCK-01", "page": 3,
                                                 "summary": "VIN ..18 V"}
    assert by_rule["RAT-002"]["severity"] == "critical"          # 0.37 A > 0.25 A LDO rating
    assert by_rule["RAT-003"]["refs"] == ["temp_sensor", "3v3"]  # 3.4 V > 3.3 V
    assert "RAT-004" in by_rule                                  # parts without sheets are listed


def test_example_ratings():
    # The only serious finding is the test sheet trap: temperature sensor rated 3.3 V max on a 3.4 V rail.
    findings = run_with_library(EXAMPLE)
    serious = {e["rule_id"] for f in findings if f["severity"] in ("critical", "major")
               for e in f["evidence"] if e.get("rule_id")}
    assert serious == {"RAT-003"}
