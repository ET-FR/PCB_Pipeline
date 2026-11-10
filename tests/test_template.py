import yaml

from pcb_pipeline.cli import main
from pcb_pipeline.schemas import validate
from pcb_pipeline.template import init_project


def test_init_creates_project(tmp_path):
    created, skipped = init_project(tmp_path / "my_board")
    root = tmp_path / "my_board"
    assert skipped == []
    for path in ["inputs/README.md", "design/prd.md", "datasheets/index.yaml", "review/notes.yaml",
                 "review/decisions.yaml", "review/missed.yaml", "CLAUDE.md", ".claude/commands/define.md"]:
        assert (root / path).exists(), path
    assert "my_board" in (root / "design/prd.md").read_text(encoding="utf-8")
    assert "{{" not in "".join((root / p).read_text(encoding="utf-8") for p in created)
    assert validate("notes", yaml.safe_load((root / "review/notes.yaml").read_text(encoding="utf-8"))) == []


def test_init_never_overwrites(tmp_path):
    (tmp_path / "design").mkdir()
    (tmp_path / "design/prd.md").write_text("my PRD", encoding="utf-8")
    _, skipped = init_project(tmp_path)
    assert (tmp_path / "design/prd.md").read_text(encoding="utf-8") == "my PRD"
    assert any(p.as_posix() == "design/prd.md" for p in skipped)


def test_cli_check_spec(tmp_path, capsys):
    assert main(["check-spec", "tests/fixtures/spec_trapped.yaml", "--out", str(tmp_path),
                 "--fail-on", "critical"]) == 1
    assert (tmp_path / "spec_report.md").exists()


def test_cli_check_with_spec_rails(tmp_path, capsys):
    # The spec gives /VIN max 14 V and /+5V max 5.1 V: same traps as --rail /VIN=12 --rail /+5V=5
    main(["check", "--netlist", "tests/fixtures/buck_trapped.xml", "--library", "examples/component_sheets",
          "--spec", "examples/spec/sensor_node.spec.yaml", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert "CAP-001" in out and "EQ-001" in out
