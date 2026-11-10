"""Compare two revisions of design/spec.yaml and list what must be checked again.

Used when the PRD changes: phase 1 updates the spec, then this tells the user and the
agents which parts, rails and schematic blocks are impacted.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# section -> how to get a stable key for each item
KEYED = {
    "blocks": lambda x: x["id"],
    "parts": lambda x: x["id"],
    "rails": lambda x: x["id"],
    "connectors": lambda x: x["id"],
    "buses": lambda x: x["id"],
    "mcu_pins": lambda x: f"{x['part']}:{x['pin']}",
}


@dataclass
class Change:
    section: str
    key: str
    kind: str                     # added | removed | changed
    fields: list[tuple[str, object, object]] = field(default_factory=list)

    def describe(self) -> str:
        if self.kind != "changed":
            return f"{self.section}/{self.key} {self.kind}"
        diffs = "; ".join(f"{f}: {_short(a)} -> {_short(b)}" for f, a, b in self.fields)
        return f"{self.section}/{self.key} changed ({diffs})"


@dataclass
class Impact:
    changes: list[Change]
    actions: list[str]            # what must be done or checked again
    revision_bumped: bool


def _short(v) -> str:
    s = yaml.safe_dump(v, default_flow_style=True).strip() if isinstance(v, (dict, list)) else str(v)
    return s if len(s) <= 60 else s[:57] + "..."


def _items(spec: dict, section: str) -> list[dict]:
    if section == "rails":
        return spec.get("power_tree", {}).get("rails", [])
    return spec.get(section, []) or []


def _field_diff(a: dict, b: dict) -> list[tuple[str, object, object]]:
    return [(k, a.get(k), b.get(k)) for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]


def diff_specs(old: dict, new: dict) -> list[Change]:
    changes: list[Change] = []
    for section, key in KEYED.items():
        before = {key(x): x for x in _items(old, section)}
        after = {key(x): x for x in _items(new, section)}
        for k in after.keys() - before.keys():
            changes.append(Change(section, k, "added"))
        for k in before.keys() - after.keys():
            changes.append(Change(section, k, "removed"))
        for k in before.keys() & after.keys():
            fields = _field_diff(before[k], after[k])
            if fields:
                changes.append(Change(section, k, "changed", fields))
    for section in ("mechanical", "design_rules"):
        a, b = old.get(section) or {}, new.get(section) or {}
        fields = _field_diff(a, b)
        if fields:
            changes.append(Change(section, "-", "changed", fields))
    return sorted(changes, key=lambda c: (list(KEYED).index(c.section) if c.section in KEYED else 99, c.key))


def impact(old: dict, new: dict) -> Impact:
    changes = diff_specs(old, new)
    parts = {p["id"]: p for p in new.get("parts", [])}
    rails = {r["id"]: r for r in new.get("power_tree", {}).get("rails", [])}
    actions: list[str] = []

    def add(a: str):
        if a not in actions:
            actions.append(a)

    def part_label(pid: str) -> str:
        p = parts.get(pid, {})
        return f"{pid} ({p['ref']})" if p.get("ref") else pid

    for c in changes:
        changed = {f for f, _, _ in c.fields}
        if c.section == "parts":
            if c.kind == "added" or "mpn" in changed:
                p = parts.get(c.key, {})
                add(f"Fetch the datasheet and build the component sheet of {c.key} ({p.get('mpn', '?')})")
                add(f"Update the schematic symbol of {part_label(c.key)}: MPN, footprint, pinout")
                add(f"Re-review functional block {p.get('block', '?')}")
            elif c.kind == "removed":
                add(f"Remove {c.key} from the schematic and from every rail, bus and pin assignment")
            elif "block" in changed or "status" in changed:
                add(f"Re-review functional block {parts.get(c.key, {}).get('block', '?')}")
        elif c.section == "rails":
            r = rails.get(c.key, {})
            if c.kind == "removed":
                add(f"Remove rail {c.key} from the schematic and move its loads")
                continue
            if c.kind == "added" or changed & {"nominal_v", "min_v", "max_v", "transient_max_v"}:
                loads = [part_label(x["part"]) for x in r.get("loads", [])]
                children = [x["id"] for x in rails.values() if x["source"].get("from_rail") == c.key]
                add(f"Re-check capacitor derating and absolute maximum ratings on net {r.get('net', c.key)}")
                if loads:
                    add(f"Re-check the supply range of the loads of {c.key}: {', '.join(loads)}")
                if children:
                    add(f"Re-check the converters fed by {c.key}: {', '.join(children)}")
                if r.get("source", {}).get("part"):
                    add(f"Re-check the feedback divider of {part_label(r['source']['part'])}")
            if changed & {"loads", "capacity_a", "source"}:
                add(f"Re-check the power budget and the source of rail {c.key} (track widths and thermal included)")
        elif c.section == "buses":
            add(f"Re-check bus {c.key}: addresses, pull-ups, levels, wiring")
        elif c.section == "mcu_pins":
            add(f"Update the MCU pin assignment in the schematic ({c.key}) and tell the firmware side")
        elif c.section == "connectors":
            add(f"Re-check connector {c.key}: pinout in the schematic, harness, protection")
        elif c.section == "blocks":
            add(f"Review block {c.key} ({c.kind})")
        elif c.section == "design_rules":
            add("Regenerate the KiCad net classes and custom rules, then run the DRC again")
        elif c.section == "mechanical":
            add("Re-check the board outline, mounting holes, heights and keep-outs in the layout")

    if changes:
        add("Run `pcb-pipeline check-spec` and render the spec again")
        add("Project notes that depend on the spec revision expire")
    bumped = (old.get("project", {}).get("revision") != new.get("project", {}).get("revision"))
    if changes and not bumped:
        actions.insert(0, "Bump project.revision in the spec: notes and reviews use it to expire")
    return Impact(changes, actions, bumped)


def load_from_git(spec_path: Path, rev: str) -> dict:
    """Read the spec as it was at a git revision."""
    spec_path = Path(spec_path).resolve()
    out = subprocess.run(["git", "-C", str(spec_path.parent), "show", f"{rev}:./{spec_path.name}"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"git show {rev}:{spec_path.name} failed: {out.stderr.strip()}")
    return yaml.safe_load(out.stdout) or {}


def render_impact(imp: Impact, old_label: str, new_label: str) -> str:
    lines = [f"# Spec changes: {old_label} -> {new_label}", ""]
    if not imp.changes:
        return "\n".join(lines + ["No change."])
    lines += ["## Changes", ""] + [f"- {c.describe()}" for c in imp.changes]
    lines += ["", "## What to do or check again", ""] + [f"- [ ] {a}" for a in imp.actions]
    return "\n".join(lines) + "\n"
