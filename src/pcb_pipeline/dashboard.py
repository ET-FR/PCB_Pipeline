"""Project dashboard: one HTML page with status, PRD, power tree, datasheets, findings,
schematic and layout (exported by kicad-cli), with findings highlighted on the drawings.

Read only. Generated into out/dashboard/ of the hardware project; open index.html in a
browser. Nothing here talks to an AI model: the agents run in Claude Code and the
dashboard shows what they and the deterministic checks produced.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .datasheet.library import SheetLibrary
from .findings import SEVERITY_ORDER, Findings
from .kicad_files import read_board, read_schematic
from .kicad_import import export_netlist, parse_netlist_xml
from .rules.engine import RuleEngine, load_rules
from .paths import default_library_dirs
from .spec import check_spec, load_spec, spec_rails

REPO = Path(__file__).resolve().parents[2]
ASSET = Path(__file__).resolve().parent / "dashboard_assets" / "index.html"

PCB_VIEWS = {  # view name -> layers
    "Top": "F.Cu,F.Silkscreen,Edge.Cuts",
    "Bottom": "B.Cu,B.Silkscreen,Edge.Cuts",
    "All copper": "F.Cu,B.Cu,F.Silkscreen,Edge.Cuts",
}


@dataclass
class Project:
    root: Path
    prd: Path
    spec: Path
    datasheets: Path
    review: Path
    sch: Path | None = None
    pcb: Path | None = None
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def find(cls, root: Path) -> "Project":
        root = Path(root).resolve()
        p = cls(root, root / "design/prd.md", root / "design/spec.yaml", root / "datasheets", root / "review")
        pros = sorted((root / "kicad").glob("*.kicad_pro")) or sorted(
            x for x in root.rglob("*.kicad_pro") if "out" not in x.parts)
        if not pros:   # no project file: a schematic that has a board next to it, or any schematic
            schs = sorted((root / "kicad").glob("*.kicad_sch"))
            pros = [s for s in schs if s.with_suffix(".kicad_pcb").exists()] or schs[:1]
        if pros:
            pro = pros[0]
            sch, pcb = pro.with_suffix(".kicad_sch"), pro.with_suffix(".kicad_pcb")
            p.sch = sch if sch.exists() else None
            p.pcb = pcb if pcb.exists() else None
        return p


def _yaml(path: Path, key: str) -> list:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    return data.get(key) or [] if isinstance(data, dict) else []


def _mtime(*paths: Path) -> float:
    return max((p.stat().st_mtime for p in paths if p and p.exists()), default=0.0)


def _iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""


# KiCad exports ---------------------------------------------------------------------------

def kicad_version(kicad_cli: str) -> str | None:
    if not shutil.which(kicad_cli) and not Path(kicad_cli).exists():
        return None
    try:
        out = subprocess.run([kicad_cli, "version"], capture_output=True, text=True, timeout=120)
        return out.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _run(cmd: list[str]) -> tuple[bool, str]:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return out.returncode == 0, (out.stderr or out.stdout).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


class Exporter:
    """Runs kicad-cli only when the KiCad files changed since the last export."""

    def __init__(self, out: Path, kicad_cli: str, version: str):
        self.out = out / "svg"
        self.out.mkdir(parents=True, exist_ok=True)
        self.cli = kicad_cli
        self.major = int(re.match(r"(\d+)", version).group(1)) if re.match(r"(\d+)", version) else 10
        self.cache_file = out / "cache.json"
        self.cache = json.loads(self.cache_file.read_text()) if self.cache_file.exists() else {}

    def _fresh(self, key: str, sources: list[Path], outputs: list[Path]) -> bool:
        stamp = _mtime(*sources)
        return self.cache.get(key) == stamp and all(o.exists() for o in outputs)

    def _done(self, key: str, sources: list[Path]):
        self.cache[key] = _mtime(*sources)
        self.cache_file.write_text(json.dumps(self.cache, indent=2))

    def schematic(self, sch: Path) -> tuple[list[Path], str | None]:
        sources = sorted(sch.parent.rglob("*.kicad_sch"))
        existing = sorted(self.out.glob(f"{sch.stem}*.svg"))
        if self._fresh("sch", sources, existing) and existing:
            return existing, None
        for old in existing:
            old.unlink()
        ok, msg = _run([self.cli, "sch", "export", "svg", "-o", str(self.out), str(sch)])
        if not ok:
            return [], f"schematic export failed: {msg}"
        self._done("sch", sources)
        return sorted(self.out.glob(f"{sch.stem}*.svg")), None

    def board(self, pcb: Path) -> tuple[dict[str, Path], str | None]:
        files = {name: self.out / f"pcb_{i}.svg" for i, name in enumerate(PCB_VIEWS)}
        if self._fresh("pcb", [pcb], list(files.values())):
            return files, None
        for name, layers in PCB_VIEWS.items():
            cmd = [self.cli, "pcb", "export", "svg", "--layers", layers, "--page-size-mode", "0",
                   "-o", str(files[name]), str(pcb)]
            if self.major >= 9:
                cmd.insert(4, "--mode-single")
            ok, msg = _run(cmd)
            if not ok:
                return {}, f"layout export failed ({name}): {msg}"
        self._done("pcb", [pcb])
        return files, None


def _sheet_svg(svgs: list[Path], project: str, sheet_name: str) -> Path | None:
    """kicad-cli names the root page <project>.svg and sub-sheets <project>-<sheet name>.svg."""
    if not sheet_name:
        return next((s for s in svgs if s.stem == project), None)
    safe = re.sub(r'[\\/:*?"<>|]', "_", sheet_name)
    return next((s for s in svgs if s.stem in (f"{project}-{sheet_name}", f"{project}-{safe}")), None) or \
        next((s for s in svgs if s.stem.endswith(f"-{safe}")), None)


# Data collection -------------------------------------------------------------------------

def _phase_status(p: Project, spec: dict | None, prd_text: str, gates: dict[str, dict],
                  sheets: list, board_items: list) -> list[dict]:
    prd_started = len(prd_text.strip()) > 200
    prd_signed = bool(re.search(r"status\s*[:=]?\s*\**\s*signed[ _-]?off", prd_text, re.I))
    spec_signed = bool(spec and spec.get("project", {}).get("status") == "signed_off")
    sch_started = any(s["items"] for s in sheets)
    pcb_started = bool(board_items)

    def status(done: bool, started: bool) -> str:
        return "done" if done else ("in_progress" if started else "todo")

    phases = [
        {"id": "definition", "title": "0. Definition", "command": "/define",
         "status": status(prd_signed or "definition" in gates, prd_started), "gate": "PRD signed off"},
        {"id": "architecture", "title": "1. Architecture", "command": "/architecture",
         "status": status(spec_signed or "architecture_review" in gates, spec is not None),
         "gate": "architecture_review"},
        {"id": "schematic", "title": "2. Schematic", "command": "/review",
         "status": status("schematic_review" in gates, sch_started), "gate": "schematic_review"},
        {"id": "layout", "title": "3. Layout", "command": "/review",
         "status": status("pre_fabrication" in gates, pcb_started), "gate": "pre_fabrication"},
        {"id": "simulation", "title": "4. Simulation", "command": "", "status": "disabled", "gate": ""},
    ]
    for ph in phases:
        g = gates.get(ph["gate"])
        if g:
            ph["gate_passed"] = f"{g.get('passed', '')} {g.get('revision', '')}".strip()
    return phases


def _markdown(text: str) -> str:
    try:
        import markdown
        return markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    except ImportError:
        return f"<pre>{html.escape(text)}</pre>"


def _datasheet_rows(spec: dict | None, index: list[dict], lib: SheetLibrary, p: Project, out: Path) -> list[dict]:
    by_mpn = {e["mpn"]: e for e in index}
    rows = []
    for part in (spec or {}).get("parts", []):
        if part.get("status") == "rejected":
            continue
        e = by_mpn.get(part["mpn"], {})
        name = e.get("file") or part.get("datasheet", {}).get("file")
        local = p.datasheets / name if name else None
        sheet = lib.get(part["mpn"])
        ext = (sheet or {}).get("extraction", {})
        rows.append({
            "part": part["id"], "ref": part.get("ref", ""), "mpn": part["mpn"], "block": part["block"],
            "status": part["status"], "revision": e.get("revision") or part.get("datasheet", {}).get("revision", ""),
            "url": e.get("url") or part.get("datasheet", {}).get("url", ""),
            "pdf": os.path.relpath(local, out) if local and local.exists() else "",
            "sheet": bool(sheet), "score": ext.get("critic_score"), "validated": ext.get("human_validated", False),
            "gaps": len(ext.get("gaps", [])),
        })
    return rows


def _power_tree_svg(spec: dict, currents: dict[str, float]) -> str:
    rails = spec.get("power_tree", {}).get("rails", [])
    ratio = spec.get("design_rules", {}).get("electrical", {}).get("rail_load_ratio", 0.8)
    kids: dict[str | None, list[dict]] = {}
    for r in rails:
        kids.setdefault(r["source"].get("from_rail"), []).append(r)
    ids = {r["id"] for r in rails}
    roots = [r for r in rails if r["source"].get("from_rail") not in ids]

    W, H, GX, GY = 230, 74, 70, 22
    pos: dict[str, tuple[float, float]] = {}
    row = [0]

    def place(r: dict, depth: int, seen: frozenset) -> float:
        children = [c for c in kids.get(r["id"], []) if c["id"] not in seen]
        if not children:
            y = row[0] * (H + GY)
            row[0] += 1
        else:
            ys = [place(c, depth + 1, seen | {r["id"]}) for c in children]
            y = (ys[0] + ys[-1]) / 2
        pos[r["id"]] = (depth * (W + GX), y)
        return y

    for r in roots:
        place(r, 0, frozenset())
    if not pos:
        return ""
    width = max(x for x, _ in pos.values()) + W + 4
    height = max(y for _, y in pos.values()) + H + 4
    parts = [f'<svg class="ptree" viewBox="-2 -2 {width} {height}" width="{width}" height="{height}" '
             f'xmlns="http://www.w3.org/2000/svg">']
    for r in rails:
        parent = r["source"].get("from_rail")
        if parent in pos and r["id"] in pos:
            (px, py), (cx, cy) = pos[parent], pos[r["id"]]
            x1, y1, x2, y2 = px + W, py + H / 2, cx, cy + H / 2
            parts.append(f'<path class="edge" d="M{x1},{y1} C{x1 + GX / 2},{y1} {x2 - GX / 2},{y2} {x2},{y2}"/>')
    for r in rails:
        if r["id"] not in pos:
            continue
        x, y = pos[r["id"]]
        i, cap = currents.get(r["id"]), r.get("capacity_a")
        frac = (i / cap) if (i is not None and cap) else None
        cls = "none" if frac is None else ("over" if frac > 1 else "warn" if frac > ratio else "ok")
        src = r["source"]["type"] + (f" · {r['source']['part']}" if r["source"].get("part") else "")
        load = f"{i:.3f} A" if i is not None else "?"
        load += f" / {cap:g} A · {frac:.0%}" if frac is not None else (" · no capacity" if r["source"]["type"] != "external" else "")
        bar = min(frac, 1.0) * (W - 24) if frac is not None else 0
        e = html.escape
        parts.append(
            f'<g class="rail {cls}" data-rail="{e(r["id"])}" transform="translate({x},{y})" tabindex="0">'
            f'<rect class="box" width="{W}" height="{H}" rx="8"/>'
            f'<text x="12" y="22" class="t1">{e(r["id"])}  <tspan class="v">{r["nominal_v"]:g} V</tspan></text>'
            f'<text x="12" y="40" class="t2">{e(src)}</text>'
            f'<rect class="track" x="12" y="50" width="{W - 24}" height="7" rx="3.5"/>'
            f'<rect class="fill" x="12" y="50" width="{bar:.1f}" height="7" rx="3.5"/>'
            f'<text x="12" y="70" class="t3">{e(load)}</text></g>')
    parts.append("</svg>")
    return "".join(parts)


def _kicad_refs(refs: list[str], part_refs: dict[str, str]) -> list[str]:
    out = []
    for r in refs:
        r = part_refs.get(r, r).split(".")[0]
        if r and r not in out:
            out.append(r)
    return out


def _evidence_links(f: dict, datasheets: list[dict]) -> list[dict]:
    pdf = {d["mpn"]: d["pdf"] for d in datasheets if d["pdf"]}
    ev = []
    for e in f.get("evidence", []):
        e = dict(e)
        if e.get("mpn") in pdf:
            e["href"] = pdf[e["mpn"]] + (f"#page={e['page']}" if e.get("page") else "")
        ev.append(e)
    return ev


def build_data(project_dir: Path, out: Path, kicad_cli: str = "kicad-cli", use_kicad: bool = True,
               library_dirs: list[Path] | None = None) -> dict:
    p = Project.find(project_dir)
    out.mkdir(parents=True, exist_ok=True)
    lib = SheetLibrary(*(library_dirs or default_library_dirs()),
                       *([p.root / "library"] if (p.root / "library").exists() else []))

    prd_text = p.prd.read_text() if p.prd.exists() else ""
    spec = load_spec(p.spec) if p.spec.exists() else None
    name = (spec or {}).get("project", {}).get("name") or p.root.name

    findings: list[dict] = []
    currents: dict[str, float] = {}
    spec_errors: list[str] = []
    if spec is not None:
        spec_errors, sf, checker = check_spec(spec, name, load_rules(), lib)
        if checker:
            currents = checker.currents
            findings += [dict(f, origin="spec") for f in sf.to_doc()["findings"]]

    version = kicad_version(kicad_cli) if use_kicad else None
    if use_kicad and not version:
        p.warnings.append(f"kicad-cli not found ({kicad_cli}): no schematic or layout images, no schematic checks.")
    elif version and int(re.match(r"\d+", version).group()) < 10:
        p.warnings.append(f"KiCad {version} found: the pipeline is built and tested with KiCad 10.")

    sheets_data: list[dict] = []
    board: dict = {}
    if p.sch:
        try:
            sheets = read_schematic(p.sch)
        except Exception as exc:  # malformed file: show the rest of the dashboard
            sheets = []
            p.warnings.append(f"could not read {p.sch.name}: {exc}")
        svgs: list[Path] = []
        if version:
            exp = Exporter(out, kicad_cli, version)
            svgs, err = exp.schematic(p.sch)
            if err:
                p.warnings.append(err)
        for s in sheets:
            svg = _sheet_svg(svgs, p.sch.stem, s.name)
            sheets_data.append({"name": s.name or "root", "file": s.file.name, "page": list(s.page),
                                "svg": os.path.relpath(svg, out) if svg else "",
                                "items": [i.to_dict() for i in s.items]})
        if version:
            try:
                netlist = parse_netlist_xml(export_netlist(p.sch, out, kicad_cli))
                rf = Findings(name)
                RuleEngine(netlist, lib, rf, load_rules(), spec_rails(spec) if spec else {}).run()
                findings += [dict(f, origin="schematic") for f in rf.to_doc()["findings"]]
            except Exception as exc:
                p.warnings.append(f"schematic checks failed: {exc}")
    if p.pcb:
        try:
            page, items = read_board(p.pcb)
            board = {"page": list(page), "items": [i.to_dict() for i in items], "views": []}
        except Exception as exc:
            p.warnings.append(f"could not read {p.pcb.name}: {exc}")
        if board and version:
            files, err = Exporter(out, kicad_cli, version).board(p.pcb)
            if err:
                p.warnings.append(err)
            board["views"] = [{"name": n, "svg": os.path.relpath(f, out)} for n, f in files.items()]

    review_findings = p.root / "out" / "findings.json"
    if review_findings.exists():
        doc = json.loads(review_findings.read_text())
        findings += [dict(f, origin="review", generated_at=doc.get("generated_at", "")) for f in doc.get("findings", [])]

    index = _yaml(p.datasheets / "index.yaml", "datasheets")
    datasheets = _datasheet_rows(spec, index, lib, p, out)
    part_refs = {x["id"]: x["ref"] for x in (spec or {}).get("parts", []) if x.get("ref")}
    decisions = _yaml(p.review / "decisions.yaml", "decisions")
    decided = {(d.get("finding"), d.get("title")): d for d in decisions}
    for f in findings:
        f["kicad_refs"] = _kicad_refs(f["refs"], part_refs)
        f["evidence"] = _evidence_links(f, datasheets)
        d = decided.get((f["id"], f["title"]))
        if d:
            f["decision"] = d.get("decision")
    findings.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], f["origin"], f["id"]))

    gates = {g["id"]: g for g in _yaml(p.review / "gates.yaml", "gates") if isinstance(g, dict) and "id" in g}
    board_items = board.get("items", []) if board else []
    phases = _phase_status(p, spec, prd_text, gates, sheets_data, board_items)
    notes = _yaml(p.review / "notes.yaml", "notes")
    open_questions = [q.get("question", "") for q in (spec or {}).get("open_questions", [])]
    m = re.search(r"^##\s*Open questions\s*$(.*?)(?=^##\s|\Z)", prd_text, re.M | re.S | re.I)
    prd_open = [ln.strip("-* ").strip() for ln in (m.group(1).splitlines() if m else []) if ln.strip().startswith(("-", "*"))]

    return {
        "project": {
            "name": name, "dir": str(p.root),
            "spec_revision": (spec or {}).get("project", {}).get("revision", ""),
            "spec_status": (spec or {}).get("project", {}).get("status", ""),
            "prd_revision": (spec or {}).get("project", {}).get("prd_revision", ""),
            "kicad": version or "", "kicad_project": p.sch.stem if p.sch else "",
            "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "updated": {"PRD": _iso(_mtime(p.prd)), "Spec": _iso(_mtime(p.spec)),
                        "Schematic": _iso(_mtime(*(p.sch.parent.rglob("*.kicad_sch") if p.sch else []))),
                        "Layout": _iso(_mtime(p.pcb) if p.pcb else 0)},
        },
        "warnings": p.warnings + [f"spec invalid: {e}" for e in spec_errors[:10]],
        "phases": phases,
        "prd_html": _markdown(prd_text) if prd_text else "",
        "prd_open": prd_open,
        "open_questions": open_questions,
        "power_tree_svg": _power_tree_svg(spec, currents) if spec and not spec_errors else "",
        "rails": [dict(r, budget_a=currents.get(r["id"])) for r in (spec or {}).get("power_tree", {}).get("rails", [])]
        if not spec_errors else [],
        "parts": (spec or {}).get("parts", []),
        "datasheets": datasheets,
        "schematic": sheets_data,
        "board": board,
        "findings": findings,
        "notes": notes,
        "decisions": decisions,
        "missed": _yaml(p.review / "missed.yaml", "missed"),
    }


def write_dashboard(project_dir: Path, out: Path | None = None, kicad_cli: str = "kicad-cli",
                    use_kicad: bool = True, library_dirs: list[Path] | None = None) -> Path:
    project_dir = Path(project_dir).resolve()
    out = Path(out) if out else project_dir / "out" / "dashboard"
    data = build_data(project_dir, out, kicad_cli, use_kicad, library_dirs)
    page = ASSET.read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/")
    page = page.replace("__TITLE__", html.escape(data["project"]["name"])).replace("/*__DATA__*/null", payload)
    index = out / "index.html"
    index.write_text(page, encoding="utf-8")
    return index
