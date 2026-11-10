"""Where things live. Three places, never mixed:

1. The pipeline repo (this code): code, schemas, rules, agent prompts, templates and the
   seed versions of the knowledge files. No project data, ever.
2. The knowledge base (`data home`): the user's own shared data, which grows with every
   project: component sheets, accepted agent notes, preferred parts, the living phase 0
   question list and architecture checklist. Ideally its own private git repo.
3. One repo per board: inputs, PRD, spec, datasheets, KiCad files, reviews.

The knowledge base is found with, in order: the PCB_PIPELINE_DATA environment
variable, `data_home` in ~/.config/pcb-pipeline/config.yaml, or ~/pcb-pipeline-data.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SEED = REPO / "templates" / "knowledge_base"
ENV = "PCB_PIPELINE_DATA"
DEFAULT_DATA_HOME = Path.home() / "pcb-pipeline-data"


def config_file() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "pcb-pipeline" / "config.yaml"


def data_home() -> Path:
    if os.environ.get(ENV):
        return Path(os.environ[ENV]).expanduser().resolve()
    cfg = config_file()
    if cfg.exists():
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        if data.get("data_home"):
            return Path(data["data_home"]).expanduser().resolve()
    return DEFAULT_DATA_HOME


def library_dir() -> Path:
    return data_home() / "library" / "component_sheets"


def knowledge_dir() -> Path:
    return data_home() / "knowledge"


def default_library_dirs() -> list[Path]:
    """Component sheet folders used when the user gives none: the knowledge base only."""
    return [library_dir()]


def is_inside(path: Path, parent: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def setup_data_home(target: Path | None = None, save_config: bool = True) -> tuple[Path, list[Path], list[Path]]:
    """Create the knowledge base from the seed files. Existing files are never overwritten."""
    target = Path(target).expanduser().resolve() if target else data_home()
    if is_inside(target, REPO):
        raise RuntimeError(f"the knowledge base must not be inside the pipeline repo ({REPO})")
    created, kept = [], []
    for src in sorted(SEED.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(SEED)
        dst = target / rel
        if dst.exists():
            kept.append(rel)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        created.append(rel)
    if save_config:
        cfg = config_file()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        data = (yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}) if cfg.exists() else {}
        data["data_home"] = str(target)
        cfg.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return target, created, kept
