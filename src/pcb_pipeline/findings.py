"""Findings collection and serialization."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from .schemas import validate

SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "info": 3}


class Findings:
    def __init__(self, project: str):
        self.project = project
        self.items: list[dict] = []
        self._counters: dict[str, int] = defaultdict(int)

    def add(self, prefix: str, severity: str, title: str, refs: list[str], evidence: list[dict],
            source: str, confidence: str = "high", **extra) -> dict:
        if not evidence:
            raise ValueError("No proof, no finding: evidence is required")
        self._counters[prefix] += 1
        item = {
            "id": f"{prefix}-{self._counters[prefix]:03d}",
            "severity": severity,
            "title": title,
            "refs": refs,
            "evidence": evidence,
            "confidence": confidence,
            "source": source,
        }
        item.update({k: v for k, v in extra.items() if v is not None})
        self.items.append(item)
        return item

    def to_doc(self) -> dict:
        doc = {
            "schema_version": 1,
            "project": self.project,
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "findings": sorted(self.items, key=lambda f: (SEVERITY_ORDER[f["severity"]], f["id"])),
        }
        errors = validate("findings", doc)
        if errors:
            raise ValueError("findings.json does not match schema:\n" + "\n".join(errors))
        return doc
