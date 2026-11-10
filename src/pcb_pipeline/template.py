"""Create a hardware project repo from templates/project."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from .paths import REPO, data_home, is_inside

TEMPLATE = REPO / "templates" / "project"


def init_project(target: Path, name: str | None = None) -> tuple[list[Path], list[Path]]:
    """Copy the template into target. Existing files are never overwritten."""
    target = Path(target)
    if is_inside(target, REPO):
        raise RuntimeError(f"a board repo must not be inside the pipeline repo ({REPO}): "
                           f"create it next to it, e.g. pcb-pipeline init ../my_board")
    if is_inside(target, data_home()):
        raise RuntimeError(f"a board repo must not be inside the knowledge base ({data_home()})")
    values = {
        "{{name}}": name or target.resolve().name,
        "{{pipeline}}": str(REPO),
        "{{data_home}}": str(data_home()),
        "{{date}}": dt.date.today().isoformat(),
    }
    created, skipped = [], []
    for src in sorted(TEMPLATE.rglob("*")):
        if src.is_dir():
            continue
        rel = Path(*(values.get(part, part) for part in src.relative_to(TEMPLATE).parts))
        dst = target / rel
        if dst.exists():
            skipped.append(rel)
            continue
        text = src.read_text()
        for key, value in values.items():
            text = text.replace(key, value)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text)
        created.append(rel)
    return created, skipped
