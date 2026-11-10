"""Board data, user data and pipeline code live in three separate places."""

import pytest
import yaml

from pcb_pipeline import paths
from pcb_pipeline.cli import main
from pcb_pipeline.template import init_project


def test_data_home_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("PCB_PIPELINE_DATA", str(tmp_path / "env"))
    assert paths.data_home() == tmp_path / "env"
    monkeypatch.delenv("PCB_PIPELINE_DATA")
    cfg = paths.config_file()
    cfg.parent.mkdir(parents=True)
    cfg.write_text(yaml.safe_dump({"data_home": str(tmp_path / "cfg")}), encoding="utf-8")
    assert paths.data_home() == tmp_path / "cfg"
    cfg.unlink()
    assert paths.data_home() == paths.DEFAULT_DATA_HOME


def test_setup_creates_knowledge_base(tmp_path, monkeypatch):
    monkeypatch.delenv("PCB_PIPELINE_DATA")
    target, created, kept = paths.setup_data_home(tmp_path / "kb")
    for f in ["knowledge/phase0_questions.md", "knowledge/architecture_checklist.md",
              "knowledge/preferred_parts.yaml", "knowledge/notes.yaml", "library/component_sheets/.gitkeep"]:
        assert (target / f).exists(), f
    assert paths.data_home() == target                     # saved in the config
    (target / "knowledge/preferred_parts.yaml").write_text("parts: [mine]\n", encoding="utf-8")
    _, _, kept = paths.setup_data_home(target)
    assert (target / "knowledge/preferred_parts.yaml").read_text(encoding="utf-8") == "parts: [mine]\n"   # never overwritten


def test_nothing_goes_into_the_pipeline_repo():
    with pytest.raises(RuntimeError):
        paths.setup_data_home(paths.REPO / "kb")
    with pytest.raises(RuntimeError):
        init_project(paths.REPO / "my_board")


def test_board_not_inside_knowledge_base(isolated_knowledge_base):
    with pytest.raises(RuntimeError):
        init_project(isolated_knowledge_base / "board")


def test_init_creates_knowledge_base_and_links_it(tmp_path, isolated_knowledge_base, capsys):
    assert main(["init", str(tmp_path / "board")]) == 0
    assert (isolated_knowledge_base / "knowledge/phase0_questions.md").exists()
    claude_md = (tmp_path / "board/CLAUDE.md").read_text(encoding="utf-8")
    assert str(isolated_knowledge_base) in claude_md and str(paths.REPO) in claude_md
    define = (tmp_path / "board/.claude/commands/define.md").read_text(encoding="utf-8")
    assert f"{isolated_knowledge_base}/knowledge/phase0_questions.md" in define


def test_default_library_is_the_knowledge_base(isolated_knowledge_base):
    assert paths.default_library_dirs() == [isolated_knowledge_base / "library" / "component_sheets"]


def test_where(capsys, isolated_knowledge_base):
    assert main(["where"]) == 1                            # not set up yet
    paths.setup_data_home()
    assert main(["where"]) == 0
    assert str(isolated_knowledge_base) in capsys.readouterr().out
