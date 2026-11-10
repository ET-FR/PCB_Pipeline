"""Create a hardware project repo from templates/project."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "templates" / "project"


def init_project(target: Path, name: str | None = None) -> tuple[list[Path], list[Path]]:
    """Copy the template into target. Existing files are never overwritten."""
    target = Path(target)
    values = {
        "{{name}}": name or target.resolve().name,
        "{{pipeline}}": str(REPO),
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
