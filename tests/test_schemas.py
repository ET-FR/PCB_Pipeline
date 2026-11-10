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


NOTE = {"id": "N-20261110-001", "scope": "project", "kind": "verified", "topic": "power/buck_5v",
        "statement": "Feedback divider R1/R2 gives 5.01 V, within 2 %.",
        "evidence": [{"kind": "calculation", "summary": "0.8 V x (1 + 52.3k/10k)"}],
        "depends_on": {"sheets": ["EXAMPLE-BUCK-01@A"], "group_hash": "abc"},
        "author": "agent:conformity", "status": "proposed", "created": "2026-11-10"}


def test_note_is_valid():
    assert validate("notes", {"schema_version": 1, "notes": [NOTE]}) == []


def test_note_without_evidence_is_rejected():
    bad = {**NOTE, "evidence": []}
    assert validate("notes", {"schema_version": 1, "notes": [bad]})


def test_verified_note_without_depends_on_is_rejected():
    bad = {k: v for k, v in NOTE.items() if k != "depends_on"}
    assert validate("notes", {"schema_version": 1, "notes": [bad]})


def test_pipeline_notes_file_is_valid():
    import yaml
    doc = yaml.safe_load((ROOT / "knowledge/notes.yaml").read_text())
    assert validate("notes", doc) == []
