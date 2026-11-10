"""Render findings.json as Markdown."""

from __future__ import annotations

from collections import defaultdict

ICON = {"critical": "🔴", "major": "🟠", "minor": "🟡", "info": "🔵"}


def _evidence_line(e: dict) -> str:
    bits = []
    if e.get("mpn"):
        bits.append(f"{e['mpn']} p.{e['page']}" if e.get("page") else e["mpn"])
    if e.get("net"):
        bits.append(f"net `{e['net']}`")
    if e.get("rule_id"):
        bits.append(e["rule_id"])
    text = e.get("calculation") or e.get("summary") or ""
    return f"  - *{e['kind']}* ({', '.join(bits)}): {text}" if bits else f"  - *{e['kind']}*: {text}"


def render_markdown(doc: dict) -> str:
    items = doc["findings"]
    counts = defaultdict(int)
    for f in items:
        counts[f["severity"]] += 1
    lines = [f"# Design review: {doc['project']}", "", f"Generated {doc['generated_at']}", ""]
    lines.append(" | ".join(f"{ICON[s]} {s}: {counts[s]}" for s in ICON))
    lines.append("")
    if not items:
        lines.append("No findings.")
    for f in items:
        lines.append(f"## {ICON[f['severity']]} {f['id']} {f['title']}")
        lines.append("")
        lines.append(f"Refs: {', '.join(f['refs'])} · confidence: {f['confidence']} · source: {f['source']}")
        if f.get("description"):
            lines += ["", f["description"]]
        lines += ["", "Evidence:"] + [_evidence_line(e) for e in f["evidence"]]
        if f.get("suggestion"):
            lines += ["", f"Suggestion: {f['suggestion']}"]
        lines.append("")
    return "\n".join(lines)
