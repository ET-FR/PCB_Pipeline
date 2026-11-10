"""Render design/spec.yaml as a readable document: Markdown always, PDF with reportlab.

The spec YAML is the source of truth. This output is for reading and sharing; it is
regenerated after every spec change and never edited by hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Section:
    title: str
    paragraphs: list[str] = field(default_factory=list)
    tables: list[tuple[list[str], list[list[str]]]] = field(default_factory=list)   # (header, rows)
    preformatted: list[str] = field(default_factory=list)
    mermaid: str | None = None


def _fmt(v, unit: str = "") -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, float):
        v = f"{v:g}"
    return f"{v} {unit}".strip()


def _refs(item: dict) -> str:
    return ", ".join(item.get("prd_refs", []))


def _power_tree_text(rails: list[dict], currents: dict[str, float]) -> str:
    children: dict[str, list[dict]] = {}
    roots = []
    for r in rails:
        parent = r["source"].get("from_rail")
        (children.setdefault(parent, []) if parent else roots).append(r)

    lines: list[str] = []

    def walk(r: dict, prefix: str, last: bool, depth: int):
        src = r["source"]
        kind = src["type"] + (f" {src['part']}" if src.get("part") else "")
        i = currents.get(r["id"])
        cap = r.get("capacity_a")
        load = f"{i:.3f} A" if i is not None else "?"
        if cap:
            load += f" / {cap:g} A ({i / cap:.0%})" if i is not None else f" / {cap:g} A"
        branch = "" if depth == 0 else ("`- " if last else "|- ")   # ASCII: PDF fonts lack box glyphs
        lines.append(f"{prefix}{branch}{r['id']}  {r['nominal_v']:g} V  [{kind}]  {load}")
        kids = children.get(r["id"], [])
        for n, k in enumerate(kids):
            ext = "" if depth == 0 else ("   " if last else "|  ")
            walk(k, prefix + ext, n == len(kids) - 1, depth + 1)

    for r in roots:
        walk(r, "", True, 0)
    return "\n".join(lines)


def build_sections(spec: dict, currents: dict[str, float] | None = None,
                   findings: list[dict] | None = None) -> list[Section]:
    currents = currents or {}
    p = spec["project"]
    out: list[Section] = []

    s = Section("Summary")
    s.tables.append((["Project", "Spec revision", "Status", "PRD revision", "Date"],
                     [[p["name"], p["revision"], p["status"], p.get("prd_revision", ""), p.get("date", "")]]))
    if findings is not None:
        counts = {k: sum(f["severity"] == k for f in findings) for k in ("critical", "major", "minor", "info")}
        s.paragraphs.append("Spec checks: " + ", ".join(f"{k} {v}" for k, v in counts.items()) + ".")
        for f in findings:
            if f["severity"] in ("critical", "major"):
                s.paragraphs.append(f"[{f['severity']}] {f['id']} {f['title']}")
    out.append(s)

    s = Section("Block diagram")
    s.tables.append((["Block", "Function", "Criticality", "Connects to", "PRD"],
                     [[b["id"], b["function"], b.get("criticality", "standard"),
                       ", ".join(b.get("connects_to", [])), _refs(b)] for b in spec["blocks"]]))
    edges = [(b["id"], o) for b in spec["blocks"] for o in b.get("connects_to", [])]
    node = lambda x: x.replace("/", "_").replace("-", "_").replace(".", "_")
    s.mermaid = "flowchart LR\n" + "\n".join(
        [f'    {node(b["id"])}["{b["id"]}"]' for b in spec["blocks"]] + [f"    {node(a)} --> {node(b)}" for a, b in edges])
    out.append(s)

    s = Section("Components")
    s.tables.append((["Id", "Ref", "MPN", "Block", "Status", "Datasheet", "Reasons"],
                     [[x["id"], x.get("ref", ""), x["mpn"], x["block"], x["status"],
                       x.get("datasheet", {}).get("revision", ""), "; ".join(x.get("reasons", []))]
                      for x in spec["parts"]]))
    alts = [[x["id"], a["mpn"], a["why_not"]] for x in spec["parts"] for a in x.get("alternatives", [])]
    if alts:
        s.tables.append((["Part", "Alternative", "Why not"], alts))
    out.append(s)

    rails = spec["power_tree"]["rails"]
    s = Section("Power tree")
    s.preformatted.append(_power_tree_text(rails, currents))
    s.tables.append((["Rail", "Net", "Min", "Nom", "Max", "Transient", "Source", "Budget", "Capacity"],
                     [[r["id"], r["net"], _fmt(r.get("min_v"), "V"), _fmt(r["nominal_v"], "V"),
                       _fmt(r.get("max_v"), "V"), _fmt(r.get("transient_max_v"), "V"),
                       r["source"]["type"] + (f" ({r['source']['part']})" if r["source"].get("part") else ""),
                       f"{currents[r['id']]:.3f} A" if r["id"] in currents else "",
                       _fmt(r.get("capacity_a"), "A")] for r in rails]))
    loads = [[r["id"], ld["part"], _fmt(ld["current"].get("typ_a"), "A"), _fmt(ld["current"]["max_a"], "A"),
              _fmt(ld["current"].get("sleep_a"), "A"), ld.get("notes", "")] for r in rails for ld in r.get("loads", [])]
    if loads:
        s.tables.append((["Rail", "Load", "Typ", "Max", "Sleep", "Notes"], loads))
    seq = [[r["id"], ", ".join(r["sequencing"].get("after", [])), _fmt(r["sequencing"].get("delay_ms"), "ms"),
            r["sequencing"].get("enable_net", ""), r["sequencing"].get("power_good_net", "")]
           for r in rails if r.get("sequencing")]
    if seq:
        s.tables.append((["Rail", "After", "Delay", "Enable", "Power good"], seq))
    out.append(s)

    if spec.get("connectors"):
        s = Section("Connectors")
        for c in spec["connectors"]:
            flags = ", ".join(k for k in ("keyed", "hot_plug") if c.get(k))
            s.paragraphs.append(f"{c['id']}: {c['purpose']}" + (f" ({flags})" if flags else "")
                                + (f", mates with {c['mates_with']}" if c.get("mates_with") else ""))
            s.tables.append((["Pin", "Signal", "Net", "Direction", "Max V", "Max I", "ESD"],
                             [[x["pin"], x["signal"], x.get("net", ""), x.get("direction", ""),
                               _fmt(x.get("max_v"), "V"), _fmt(x.get("max_current_a"), "A"),
                               {True: "yes", False: "no"}.get(x.get("esd_protected"), "")] for x in c["pins"]]))
        out.append(s)

    if spec.get("buses"):
        s = Section("Buses")
        for b in spec["buses"]:
            s.paragraphs.append(f"{b['id']} ({b['type']}), controller {b.get('controller', '?')}, "
                                f"{_fmt(b.get('voltage_v'), 'V')} {_fmt(b.get('speed_hz'), 'Hz')}"
                                + (f", pull-ups {b['pullup_ohm']:g} ohm" if b.get("pullup_ohm") else ""))
            s.tables.append((["Device", "Address", "Address select", "Chip select"],
                             [[d["part"], d.get("address", ""), d.get("address_select", ""), d.get("chip_select", "")]
                              for d in b["devices"]]))
        out.append(s)

    if spec.get("mcu_pins"):
        s = Section("MCU pins")
        s.tables.append((["Part", "Pin", "Function", "Net", "Default", "Notes"],
                         [[x["part"], x["pin"], x["function"], x.get("net", ""), x.get("default_state", ""),
                           x.get("notes", "")] for x in spec["mcu_pins"]]))
        out.append(s)

    m = spec.get("mechanical")
    if m:
        s = Section("Mechanical")
        o = m.get("outline", {})
        rows = [["Outline", f"{_fmt(o.get('width_mm'))} x {_fmt(o.get('height_mm'))} mm" if o.get("width_mm") else o.get("file", "")],
                ["Thickness", _fmt(m.get("thickness_mm"), "mm")],
                ["Max height top / bottom", f"{_fmt(m.get('max_height_mm', {}).get('top'))} / "
                                            f"{_fmt(m.get('max_height_mm', {}).get('bottom'))} mm"],
                ["Stackup", f"{m.get('stackup', {}).get('layers', '')} layers, {_fmt(m.get('stackup', {}).get('copper_oz'), 'oz')} "
                            f"{m.get('stackup', {}).get('description', '')}".strip()]]
        s.tables.append((["Item", "Value"], rows))
        if m.get("mounting_holes"):
            s.tables.append((["X", "Y", "Diameter", "Plated", "Net"],
                             [[_fmt(h["x_mm"], "mm"), _fmt(h["y_mm"], "mm"), _fmt(h["diameter_mm"], "mm"),
                               {True: "yes", False: "no"}.get(h.get("plated"), ""), h.get("net", "")]
                              for h in m["mounting_holes"]]))
        s.paragraphs += [f"Keep-out: {k}" for k in m.get("keepouts", [])]
        out.append(s)

    d = spec.get("design_rules")
    if d:
        s = Section("Design rules")
        e = d.get("electrical", {})
        if e:
            t = e.get("temperature_range_c", {})
            s.tables.append((["Electrical rule", "Value"], [
                ["Capacitor voltage ratio", _fmt(e.get("cap_voltage_ratio"))],
                ["Rail load ratio", _fmt(e.get("rail_load_ratio"))],
                ["Resistor power ratio", _fmt(e.get("resistor_power_ratio"))],
                ["Temperature range", f"{_fmt(t.get('min'))} to {_fmt(t.get('max'))} C" if t else ""]]))
        mf = d.get("manufacturer", {})
        if mf:
            s.tables.append((["Manufacturer", "Min track", "Min clearance", "Min drill", "Min annular ring"],
                             [[mf.get("name", ""), _fmt(mf.get("min_track_mm"), "mm"), _fmt(mf.get("min_clearance_mm"), "mm"),
                               _fmt(mf.get("min_drill_mm"), "mm"), _fmt(mf.get("min_annular_ring_mm"), "mm")]]))
        if d.get("net_classes"):
            s.tables.append((["Net class", "Nets", "Track", "Clearance", "Via", "Diff pair", "Impedance", "Max I"],
                             [[n["name"], ", ".join(n["nets"]), _fmt(n.get("track_width_mm"), "mm"),
                               _fmt(n.get("clearance_mm"), "mm"),
                               f"{_fmt(n.get('via_diameter_mm'))}/{_fmt(n.get('via_drill_mm'))} mm" if n.get("via_diameter_mm") else "",
                               f"{_fmt(n.get('diff_pair_width_mm'))}/{_fmt(n.get('diff_pair_gap_mm'))} mm" if n.get("diff_pair_width_mm") else "",
                               _fmt(n.get("impedance_ohm"), "ohm"), _fmt(n.get("max_current_a"), "A")]
                              for n in d["net_classes"]]))
        s.paragraphs += d.get("notes", [])
        out.append(s)

    if spec.get("assumptions") or spec.get("open_questions"):
        s = Section("Assumptions and open questions")
        if spec.get("assumptions"):
            s.tables.append((["Assumption", "PRD"], [[a["statement"], _refs(a)] for a in spec["assumptions"]]))
        if spec.get("open_questions"):
            s.tables.append((["Open question", "Owner", "PRD"],
                             [[q["question"], q.get("owner", ""), _refs(q)] for q in spec["open_questions"]]))
        out.append(s)
    return out


def _md_cell(v: str) -> str:
    return str(v).replace("|", "\\|").replace("\n", " ")


def render_markdown(spec: dict, sections: list[Section]) -> str:
    p = spec["project"]
    lines = [f"# {p['name']} design spec, revision {p['revision']}", "",
             "_Generated from design/spec.yaml. Do not edit by hand._", ""]
    for s in sections:
        lines += [f"## {s.title}", ""]
        for para in s.paragraphs:
            lines += [para, ""]
        if s.mermaid:
            lines += ["```mermaid", s.mermaid, "```", ""]
        for pre in s.preformatted:
            lines += ["```", pre, "```", ""]
        for header, rows in s.tables:
            lines.append("| " + " | ".join(header) + " |")
            lines.append("|" + "---|" * len(header))
            lines += ["| " + " | ".join(_md_cell(c) for c in row) + " |" for row in rows]
            lines.append("")
    return "\n".join(lines)


def render_pdf(spec: dict, sections: list[Section], path: Path) -> None:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:
        raise RuntimeError('PDF output needs reportlab: pip install -e ".[pdf]"') from exc
    from xml.sax.saxutils import escape

    styles = getSampleStyleSheet()
    cell = styles["BodyText"].clone("cell", fontSize=7.5, leading=9)
    head = styles["BodyText"].clone("head", fontSize=7.5, leading=9, fontName="Helvetica-Bold")
    mono = styles["Code"].clone("mono", fontSize=8, leading=10)
    page = landscape(A4)
    width = page[0] - 30 * mm
    p = spec["project"]

    story = [Paragraph(escape(f"{p['name']} design spec, revision {p['revision']}"), styles["Title"]),
             Paragraph("Generated from design/spec.yaml. Do not edit by hand.", styles["Italic"]), Spacer(1, 4 * mm)]
    for s in sections:
        story.append(Paragraph(escape(s.title), styles["Heading2"]))
        for para in s.paragraphs:
            story.append(Paragraph(escape(para), styles["BodyText"]))
        for pre in s.preformatted:
            story.append(Preformatted(pre, mono))
        for header, rows in s.tables:
            data = [[Paragraph(escape(h), head) for h in header]] + \
                   [[Paragraph(escape(str(c)), cell) for c in row] for row in rows]
            t = Table(data, colWidths=[width / len(header)] * len(header), repeatRows=1)
            t.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story += [Spacer(1, 2 * mm), t, Spacer(1, 3 * mm)]
    # The block diagram is a Mermaid graph in Markdown; in the PDF the block table carries it.
    SimpleDocTemplate(str(path), pagesize=page, leftMargin=15 * mm, rightMargin=15 * mm,
                      topMargin=12 * mm, bottomMargin=12 * mm,
                      title=f"{p['name']} spec {p['revision']}").build(story)
