"""Command line interface: pcb-pipeline check | validate-sheet | report."""

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
    RuleEngine(netlist, library, findings, rules, _parse_rails(args.rail)).run()
    doc = findings.to_doc()

    mpns = [c.mpn for c in netlist.components.values() if c.mpn]
    (out / "netlist.json").write_text(json.dumps(
        {"components": {k: asdict(v) for k, v in netlist.components.items()},
         "nets": {k: [asdict(n) for n in v] for k, v in netlist.nets.items()}}, indent=2))
    (out / "groups.json").write_text(json.dumps(groups, indent=2))
    (out / "missing_sheets.json").write_text(json.dumps(library.missing(mpns), indent=2))
    (out / "rules_findings.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False))
    (out / "rules_report.md").write_text(render_markdown(doc))

    counts = {s: sum(f["severity"] == s for f in doc["findings"]) for s in SEVERITY_ORDER}
    print(f"{project}: {len(netlist.components)} parts, {len(groups)} functional groups, "
          f"{len(library.missing(mpns))} MPN without sheet")
    print("findings: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    for f in doc["findings"]:
        print(f"  [{f['severity']}] {f['id']} {f['title']}")
    print(f"outputs in {out}/")

    if args.fail_on:
        limit = SEVERITY_ORDER[args.fail_on]
        if any(SEVERITY_ORDER[f["severity"]] <= limit for f in doc["findings"]):
            return 1
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
    c.add_argument("--fail-on", choices=list(SEVERITY_ORDER), help="non-zero exit at this severity or worse")
    c.set_defaults(fn=cmd_check)

    v = sub.add_parser("validate-sheet", help="validate component sheets against the schema")
    v.add_argument("paths", nargs="+")
    v.set_defaults(fn=cmd_validate_sheet)

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
