import copy
import json
from pathlib import Path

from pcb_pipeline.schemas import validate

ROOT = Path(__file__).resolve().parents[1]
SHEET = json.loads((ROOT / "examples/component_sheets/EXAMPLE-BUCK-01@A.json").read_text())


def test_example_sheet_is_valid():
    assert validate("component_sheet", SHEET) == []


def test_value_without_page_is_rejected():
    bad = copy.deepcopy(SHEET)
    del bad["absolute_maximum"][0]["page"]
    assert validate("component_sheet", bad)


def test_finding_without_evidence_is_rejected():
    doc = {"schema_version": 1, "project": "p", "generated_at": "now", "findings": [
        {"id": "X-001", "severity": "major", "title": "t", "refs": ["U1"],
         "evidence": [], "confidence": "high", "source": "rules"}]}
    assert validate("findings", doc)
