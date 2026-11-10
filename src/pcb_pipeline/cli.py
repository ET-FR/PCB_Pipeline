"""Command line interface.

pcb-pipeline init | check-spec | fetch-datasheets | render-spec | spec-diff | check |
validate-sheet | validate-notes | report
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import yaml

from .datasheet.library import SheetLibrary
from .findings import SEVERITY_ORDER, Findings
from .kicad_import import export_netlist, parse_netlist_xml
from .netlist import functional_groups
from .report import render_markdown
from .rules.engine import load_rules, RuleEngine
from .schemas import validate
from .datasheet.fetch import fetch_datasheets
from .render import build_sections, render_markdown as render_spec_markdown, render_pdf
from .spec import check_spec, load_spec, spec_rails
from .spec_diff import impact, load_from_git, render_impact
from .template import init_project

REPO = Path(__file__).resolve().parents[2]


def _pipeline_config() -> dict:
    p = REPO / "pipeline.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else {}


def _stage_params(cfg: dict, stage_id: str) -> dict:
    """Params of a stage, searched in every phase of pipeline.yaml."""
    for phase in cfg.get("phases", []):
        for stage in phase.get("stages", []):
            if stage.get("id") == stage_id:
                return stage.get("params", {})
    return {}


def _parse_rails(items: list[str]) -> dict[str, float]:
    rails = {}
    for item in items or []:
        net, _, volts = item.partition("=")
        rails[net] = float(volts)
    return rails


def cmd_check(args) -> int:
    cfg = _pipeline_config()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.netlist:
        netlist_path = Path(args.netlist)
        project = netlist_path.stem
    elif args.schematic:
        sch = Path(args.schematic)
        netlist_path = export_netlist(sch, out, cfg.get("inputs", {}).get("kicad_cli", "kicad-cli"))
        project = sch.stem
    else:
        print("error: give a schematic or --netlist", file=sys.stderr)
        return 2

    netlist = parse_netlist_xml(netlist_path)
    graph_cfg = _stage_params(cfg, "graph")
    groups = functional_groups(netlist, graph_cfg.get("neighborhood_depth", 2), graph_cfg.get("ignore_nets"))

    lib_dirs = [Path(d) for d in (args.library or [REPO / "library" / "component_sheets"])]
    library = SheetLibrary(*lib_dirs)
    for path, errs in library.errors.items():
        print(f"warning: invalid sheet {path}: {errs[0]}", file=sys.stderr)

    findings = Findings(project)
    rules = load_rules(Path(args.rules) if args.rules else None)
    rails = spec_rails(load_spec(Path(args.spec))) if args.spec else {}
    rails.update(_parse_rails(args.rail))   # --rail overrides the spec
    RuleEngine(netlist, library, findings, rules, rails).run()
    doc = findings.to_doc()

    mpns = [c.mpn for c in netlist.components.values() if c.mpn]
    (out / "netlist.json").write_text(json.dumps(
        {"components": {k: asdict(v) for k, v in netlist.components.items()},
         "nets": {k: [asdict(n) for n in v] for k, v in netlist.nets.items()}}, indent=2))
    (out / "groups.json").write_text(json.dumps(groups, indent=2))
    (out / "missing_sheets.json").write_text(json.dumps(library.missing(mpns), indent=2))
    (out / "rules_findings.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False))
    (out / "rules_report.md").write_text(render_markdown(doc))

    print(f"{project}: {len(netlist.components)} parts, {len(groups)} functional groups, "
          f"{len(library.missing(mpns))} MPN without sheet")
    _print_findings(doc)
    print(f"outputs in {out}/")
    return 1 if _fails(doc, args.fail_on) else 0


def _print_findings(doc: dict):
    counts = {s: sum(f["severity"] == s for f in doc["findings"]) for s in SEVERITY_ORDER}
    print("findings: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    for f in doc["findings"]:
        rules = [e["rule_id"] for e in f["evidence"] if e.get("rule_id") and e["rule_id"] != f["id"]]
        rule = f" ({', '.join(rules)})" if rules else ""
        print(f"  [{f['severity']}] {f['id']}{rule} {f['title']}")


def _fails(doc: dict, fail_on: str | None) -> bool:
    if not fail_on:
        return False
    limit = SEVERITY_ORDER[fail_on]
    return any(SEVERITY_ORDER[f["severity"]] <= limit for f in doc["findings"])


def _library(dirs: list[str] | None) -> SheetLibrary:
    library = SheetLibrary(*[Path(d) for d in (dirs or [REPO / "library" / "component_sheets"])])
    for path, errs in library.errors.items():
        print(f"warning: invalid sheet {path}: {errs[0]}", file=sys.stderr)
    return library


def _project_name(spec: dict, path: Path) -> str:
    return spec.get("project", {}).get("name", path.stem) if isinstance(spec.get("project"), dict) else path.stem


def cmd_check_spec(args) -> int:
    path = Path(args.spec)
    spec = load_spec(path)
    project = _project_name(spec, path)
    errors, findings, _ = check_spec(spec, project, load_rules(Path(args.rules) if args.rules else None),
                                     _library(args.library))
    if errors:
        print(f"{path}: INVALID")
        for e in errors:
            print(f"  {e}")
        return 1
    doc = findings.to_doc()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "spec_findings.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False))
    (out / "spec_report.md").write_text(render_markdown(doc))
    rails = spec.get("power_tree", {}).get("rails", [])
    print(f"{project}: {len(spec.get('parts', []))} parts, {len(rails)} rails, {len(spec.get('buses', []))} buses")
    _print_findings(doc)
    print(f"outputs in {out}/")
    return 1 if _fails(doc, args.fail_on) else 0


def cmd_fetch_datasheets(args) -> int:
    spec = load_spec(Path(args.spec))
    folder = Path(args.dir) if args.dir else Path(args.spec).resolve().parent.parent / "datasheets"
    res = fetch_datasheets(spec, folder, timeout=args.timeout, offline=args.offline)
    print(f"datasheets in {folder}: {len(res.present)} present, {len(res.downloaded)} downloaded, "
          f"{len(res.missing)} missing")
    for mpn in res.changed:
        print(f"  changed  {mpn}: the PDF differs from the indexed one, check the revision and rebuild its sheet")
    for m in res.missing:
        print(f"  missing  {m['mpn']}: {m['reason']}")
        print(f"           download it by hand{' from ' + m['url'] if m.get('url') else ''} "
              f"and save it as {folder / m['file']}")
    return 1 if res.missing else 0


def cmd_render_spec(args) -> int:
    path = Path(args.spec)
    spec = load_spec(path)
    errors, findings, checker = check_spec(spec, _project_name(spec, path),
                                           load_rules(Path(args.rules) if args.rules else None),
                                           _library(args.library))
    if errors:
        print(f"{path}: INVALID, fix it before rendering")
        for e in errors:
            print(f"  {e}")
        return 1
    sections = build_sections(spec, checker.currents, findings.to_doc()["findings"])
    md = Path(args.markdown) if args.markdown else path.with_suffix(".md")
    md.write_text(render_spec_markdown(spec, sections))
    print(f"markdown written to {md}")
    if not args.no_pdf:
        pdf = Path(args.pdf) if args.pdf else path.with_suffix(".pdf")
        render_pdf(spec, sections, pdf)
        print(f"pdf written to {pdf}")
    return 0


def cmd_spec_diff(args) -> int:
    new_path = Path(args.spec)
    new = load_spec(new_path)
    if args.old:
        old, old_label = load_spec(Path(args.old)), args.old
    else:
        old, old_label = load_from_git(new_path, args.against), f"{args.against}:{new_path.name}"
    imp = impact(old, new)
    text = render_impact(imp, old_label, str(new_path))
    if args.output:
        Path(args.output).write_text(text)
        print(f"impact written to {args.output}")
    print(text)
    return 0


def cmd_init(args) -> int:
    created, skipped = init_project(Path(args.path), args.name)
    for p in created:
        print(f"  created {p}")
    for p in skipped:
        print(f"  kept    {p} (already exists)")
    print(f"project ready in {args.path}. Next: put your documents in inputs/ and run /define in Claude Code.")
    return 0


def cmd_validate_sheet(args) -> int:
    status = 0
    for path in args.paths:
        errors = validate("component_sheet", json.loads(Path(path).read_text()))
        if errors:
            status = 1
            print(f"{path}: INVALID")
            for e in errors:
                print(f"  {e}")
        else:
            print(f"{path}: ok")
    return status


def cmd_validate_notes(args) -> int:
    status = 0
    for path in args.paths:
        errors = validate("notes", yaml.safe_load(Path(path).read_text()) or {})
        if errors:
            status = 1
            print(f"{path}: INVALID")
            for e in errors:
                print(f"  {e}")
        else:
            print(f"{path}: ok")
    return status


def cmd_report(args) -> int:
    doc = json.loads(Path(args.findings).read_text())
    errors = validate("findings", doc)
    if errors:
        print("findings.json invalid:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 1
    md = render_markdown(doc)
    out = Path(args.output) if args.output else Path(args.findings).with_suffix(".md")
    out.write_text(md)
    print(f"report written to {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pcb-pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="import, functional groups, deterministic rules")
    c.add_argument("schematic", nargs="?", help="root .kicad_sch file")
    c.add_argument("--netlist", help="use an exported KiCad XML netlist instead of kicad-cli")
    c.add_argument("--out", default="out")
    c.add_argument("--library", action="append", help="component sheet directory (repeatable)")
    c.add_argument("--rules", help="rules YAML (default rules/checklist.yaml)")
    c.add_argument("--rail", action="append", metavar="NET=VOLTS", help="declare a rail voltage")
    c.add_argument("--spec", help="design/spec.yaml: rail voltages are taken from its power tree")
    c.add_argument("--fail-on", choices=list(SEVERITY_ORDER), help="non-zero exit at this severity or worse")
    c.set_defaults(fn=cmd_check)

    i = sub.add_parser("init", help="create a hardware project repo from the template")
    i.add_argument("path")
    i.add_argument("--name", help="board name (default: folder name)")
    i.set_defaults(fn=cmd_init)

    s = sub.add_parser("check-spec", help="validate design/spec.yaml and run the spec rules")
    s.add_argument("spec")
    s.add_argument("--out", default="out")
    s.add_argument("--rules", help="rules YAML (default rules/checklist.yaml)")
    s.add_argument("--library", action="append", help="component sheet directory (repeatable)")
    s.add_argument("--fail-on", choices=list(SEVERITY_ORDER), help="non-zero exit at this severity or worse")
    s.set_defaults(fn=cmd_check_spec)

    fd = sub.add_parser("fetch-datasheets", help="download selected parts' datasheets, update datasheets/index.yaml")
    fd.add_argument("spec")
    fd.add_argument("--dir", help="datasheet folder (default: datasheets/ next to design/)")
    fd.add_argument("--timeout", type=float, default=30.0)
    fd.add_argument("--offline", action="store_true", help="only register PDFs already on disk")
    fd.set_defaults(fn=cmd_fetch_datasheets)

    rs = sub.add_parser("render-spec", help="render the spec to Markdown and PDF")
    rs.add_argument("spec")
    rs.add_argument("--markdown", help="default: spec.md next to the spec")
    rs.add_argument("--pdf", help="default: spec.pdf next to the spec")
    rs.add_argument("--no-pdf", action="store_true")
    rs.add_argument("--rules")
    rs.add_argument("--library", action="append")
    rs.set_defaults(fn=cmd_render_spec)

    sd = sub.add_parser("spec-diff", help="changes between two spec revisions and what to check again")
    sd.add_argument("spec", help="new spec")
    g = sd.add_mutually_exclusive_group()
    g.add_argument("--old", help="old spec file")
    g.add_argument("--against", default="HEAD", help="git revision of the old spec (default HEAD)")
    sd.add_argument("-o", "--output", help="write the impact report to this file")
    sd.set_defaults(fn=cmd_spec_diff)

    v = sub.add_parser("validate-sheet", help="validate component sheets against the schema")
    v.add_argument("paths", nargs="+")
    v.set_defaults(fn=cmd_validate_sheet)

    n = sub.add_parser("validate-notes", help="validate agent notes (YAML) against the schema")
    n.add_argument("paths", nargs="+")
    n.set_defaults(fn=cmd_validate_notes)

    r = sub.add_parser("report", help="render findings.json to Markdown")
    r.add_argument("findings")
    r.add_argument("-o", "--output")
    r.set_defaults(fn=cmd_report)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
