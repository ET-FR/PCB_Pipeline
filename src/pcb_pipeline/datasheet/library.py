"""Component sheet library: one JSON file per MPN and datasheet revision."""

from __future__ import annotations

import json
from pathlib import Path

from ..schemas import validate


class SheetLibrary:
    def __init__(self, *dirs: Path):
        self.sheets: dict[str, dict] = {}
        self.errors: dict[str, list[str]] = {}
        for d in dirs:
            if not d.exists():
                continue
            for path in sorted(d.glob("*.json")):
                sheet = json.loads(path.read_text())
                errs = validate("component_sheet", sheet)
                if errs:
                    self.errors[str(path)] = errs
                    continue
                mpn = sheet["mpn"]
                # sorted glob: a later revision file overrides an earlier one
                self.sheets[mpn] = sheet

    def get(self, mpn: str | None) -> dict | None:
        return self.sheets.get(mpn) if mpn else None

    def missing(self, mpns: list[str]) -> list[str]:
        return sorted({m for m in mpns if m and m not in self.sheets})


def sheet_filename(sheet: dict) -> str:
    rev = sheet["datasheet"]["revision"].replace(" ", "").replace("/", "-")
    return f"{sheet['mpn']}@{rev}.json"
