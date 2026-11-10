"""Deterministic checks on design/spec.yaml (phase 1). Python computes; agents judge."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import yaml

from .findings import Findings
from .schemas import validate

DEFAULT_EFFICIENCY = 0.85
PASS_THROUGH = {"ldo", "load_switch"}   # input current equals output current
STEP_DOWN = {"buck", "ldo"}
STEP_UP = {"boost"}


def load_spec(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text()) or {}


def spec_rails(spec: dict) -> dict[str, float]:
    """Net name -> highest steady state voltage, for the schematic rule engine."""
    return {r["net"]: r.get("max_v", r["nominal_v"]) for r in spec.get("power_tree", {}).get("rails", [])}


def _ev(path: str, summary: str, rule_id: str | None = None) -> list[dict]:
    ev = [{"kind": "spec", "spec_path": path, "summary": summary}]
    if rule_id:
        ev.append({"kind": "rule", "rule_id": rule_id})
    return ev


class SpecChecker:
    def __init__(self, spec: dict, findings: Findings, rules: dict | None = None):
        self.s = spec
        self.f = findings
        self.rules = (rules or {}).get("rules", {})
        self.parts = {p["id"]: p for p in spec.get("parts", [])}
        self.blocks = {b["id"]: b for b in spec.get("blocks", [])}
        self.rails = {r["id"]: r for r in spec.get("power_tree", {}).get("rails", [])}
        self.electrical = spec.get("design_rules", {}).get("electrical", {})
        self.currents: dict[str, float] = {}

    def sev(self, rule_id: str, default: str = "major") -> str:
        return self.rules.get(rule_id, {}).get("severity", default)

    def param(self, rule_id: str, key: str, default):
        return self.rules.get(rule_id, {}).get("params", {}).get(key, default)

    def run(self) -> Findings:
        self.references()
        self.i2c_addresses()
        self.mcu_pins()
        self.rail_voltages()
        self.power_budget()
        return self.f

    # SPEC-001: every reference points to something that exists --------------------

    def references(self):
        rid = "SPEC-001"

        def missing(kind: str, value: str, where: str, known: dict):
            if value not in known:
                self.f.add("ARC", self.sev(rid), f"{where} refers to unknown {kind} '{value}'",
                           [value], _ev(where, f"no {kind} with id '{value}' in the spec", rid),
                           source="architecture", block=None)

        for kind, items in (("block", self.s.get("blocks", [])), ("part", self.s.get("parts", [])),
                            ("rail", self.s.get("power_tree", {}).get("rails", []))):
            for item_id, n in Counter(i["id"] for i in items).items():
                if n > 1:
                    self.f.add("ARC", self.sev(rid), f"{kind} id '{item_id}' is defined {n} times", [item_id],
                               _ev(f"{kind}s", f"duplicate {kind} id", rid), source="architecture")

        for p in self.s.get("parts", []):
            missing("block", p["block"], f"parts/{p['id']}/block", self.blocks)
        for b in self.s.get("blocks", []):
            for other in b.get("connects_to", []):
                missing("block", other, f"blocks/{b['id']}/connects_to", self.blocks)
        for r in self.rails.values():
            src = r["source"]
            if src.get("part"):
                missing("part", src["part"], f"power_tree/{r['id']}/source/part", self.parts)
            if src.get("from_rail"):
                missing("rail", src["from_rail"], f"power_tree/{r['id']}/source/from_rail", self.rails)
            elif src["type"] != "external":
                self.f.add("ARC", self.sev(rid), f"rail '{r['id']}' is not external but has no from_rail", [r["id"]],
                           _ev(f"power_tree/{r['id']}/source", f"source type {src['type']} needs a parent rail", rid),
                           source="architecture")
            for load in r.get("loads", []):
                missing("part", load["part"], f"power_tree/{r['id']}/loads", self.parts)
        for bus in self.s.get("buses", []):
            if bus.get("controller"):
                missing("part", bus["controller"], f"buses/{bus['id']}/controller", self.parts)
            for d in bus["devices"]:
                missing("part", d["part"], f"buses/{bus['id']}/devices", self.parts)
        for c in self.s.get("connectors", []):
            if c.get("part"):
                missing("part", c["part"], f"connectors/{c['id']}/part", self.parts)
        for pin in self.s.get("mcu_pins", []):
            missing("part", pin["part"], f"mcu_pins/{pin['pin']}", self.parts)

    # BUS-001 / BUS-002: I2C address map ----------------------------------------------

    def i2c_addresses(self):
        for bus in self.s.get("buses", []):
            if bus["type"] != "i2c":
                continue
            by_addr = defaultdict(list)
            for d in bus["devices"]:
                if "address" in d:
                    by_addr[int(d["address"], 16)].append(d["part"])
                else:
                    self.f.add("ARC", self.sev("BUS-002", "minor"), f"{d['part']} on {bus['id']} has no I2C address",
                               [d["part"]], _ev(f"buses/{bus['id']}/devices", "address not declared", "BUS-002"),
                               source="architecture", confidence="medium")
            for addr, parts in by_addr.items():
                if len(parts) > 1:
                    self.f.add("ARC", self.sev("BUS-001", "critical"),
                               f"I2C address conflict 0x{addr:02X} on {bus['id']}", parts,
                               _ev(f"buses/{bus['id']}/devices", f"{', '.join(parts)} all use 0x{addr:02X}", "BUS-001"),
                               source="architecture",
                               suggestion="Change an address select strap, move one device to another bus, or add an I2C mux.")

    # MCU-001: a pin is assigned once ---------------------------------------------------

    def mcu_pins(self):
        uses = defaultdict(list)
        for p in self.s.get("mcu_pins", []):
            uses[(p["part"], p["pin"])].append(p["function"])
        for (part, pin), functions in uses.items():
            if len(functions) > 1:
                self.f.add("ARC", self.sev("MCU-001", "critical"), f"{part} pin {pin} is assigned {len(functions)} times",
                           [part], _ev("mcu_pins", f"{pin}: {', '.join(functions)}", "MCU-001"), source="architecture")

    # PWR-004: rail voltages are consistent with their source -----------------------------

    def rail_voltages(self):
        rid = "PWR-004"
        for r in self.rails.values():
            lo, nom, hi = r.get("min_v", r["nominal_v"]), r["nominal_v"], r.get("max_v", r["nominal_v"])
            if not lo <= nom <= hi:
                self.f.add("ARC", self.sev(rid), f"rail '{r['id']}' voltages are inconsistent", [r["id"]],
                           _ev(f"power_tree/{r['id']}", f"min {lo} V, nominal {nom} V, max {hi} V", rid),
                           source="architecture")
            parent = self.rails.get(r["source"].get("from_rail", ""))
            if not parent:
                continue
            p_lo = parent.get("min_v", parent["nominal_v"])
            p_hi = parent.get("max_v", parent["nominal_v"])
            kind = r["source"]["type"]
            if kind in STEP_DOWN and nom >= p_lo:
                self.f.add("ARC", self.sev(rid), f"{kind} rail '{r['id']}' is not below its input '{parent['id']}'",
                           [r["id"], r["source"].get("part", parent["id"])],
                           _ev(f"power_tree/{r['id']}", f"output {nom} V >= input minimum {p_lo} V", rid),
                           source="architecture")
            if kind in STEP_UP and nom <= p_hi:
                self.f.add("ARC", self.sev(rid), f"boost rail '{r['id']}' is not above its input '{parent['id']}'",
                           [r["id"], r["source"].get("part", parent["id"])],
                           _ev(f"power_tree/{r['id']}", f"output {nom} V <= input maximum {p_hi} V", rid),
                           source="architecture")

    # PWR-001 / PWR-002 / PWR-003 / PWR-005: power budget --------------------------------

    def rail_current(self, rail_id: str, stack: tuple = ()) -> float:
        """Worst case output current of a rail: its loads plus the input current of its children."""
        if rail_id in self.currents:
            return self.currents[rail_id]
        if rail_id in stack:
            raise ValueError(f"power tree loop: {' -> '.join(stack + (rail_id,))}")
        r = self.rails[rail_id]
        total = sum(load["current"]["max_a"] for load in r.get("loads", []))
        for child in self.rails.values():
            if child["source"].get("from_rail") == rail_id:
                total += self.input_current(child, r, stack + (rail_id,))
        self.currents[rail_id] = total
        return total

    def input_current(self, child: dict, parent: dict, stack: tuple) -> float:
        i_out = self.rail_current(child["id"], stack)
        if child["source"]["type"] in PASS_THROUGH:
            return i_out
        eff = child["source"].get("efficiency", DEFAULT_EFFICIENCY)
        v_in = parent.get("min_v", parent["nominal_v"])
        return child["nominal_v"] * i_out / (eff * v_in) if v_in > 0 else 0.0

    def power_budget(self):
        try:
            for rail_id in self.rails:
                self.rail_current(rail_id)
        except ValueError as exc:
            self.f.add("ARC", "critical", "power tree has a loop", list(self.rails),
                       _ev("power_tree", str(exc), "PWR-001"), source="architecture")
            return

        ratio = self.electrical.get("rail_load_ratio", self.param("PWR-002", "max_ratio", 0.8))
        for r in self.rails.values():
            i = self.currents[r["id"]]
            cap = r.get("capacity_a")
            path = f"power_tree/{r['id']}"
            refs = [r["id"]] + ([r["source"]["part"]] if r["source"].get("part") else [])
            if cap is None:
                if r["source"]["type"] != "external" and i > 0:
                    self.f.add("ARC", self.sev("PWR-003", "minor"), f"rail '{r['id']}' has no capacity_a", refs,
                               _ev(path, f"budget {i:.3f} A cannot be compared to the source capacity", "PWR-003"),
                               source="architecture", confidence="medium")
                continue
            calc = f"worst case load {i:.3f} A vs capacity {cap:.3f} A ({i / cap:.0%})" if cap else "capacity is 0 A"
            ev = [{"kind": "calculation", "calculation": calc}] + _ev(path, "rail budget from spec loads and child rails")
            if i > cap:
                ev.append({"kind": "rule", "rule_id": "PWR-001"})
                self.f.add("ARC", self.sev("PWR-001", "critical"), f"rail '{r['id']}' is overloaded", refs, ev,
                           source="architecture",
                           suggestion="Pick a source with more current, or move loads to another rail.")
            elif i > ratio * cap:
                ev.append({"kind": "rule", "rule_id": "PWR-002"})
                self.f.add("ARC", self.sev("PWR-002", "major"), f"rail '{r['id']}' load above {ratio:.0%} of capacity",
                           refs, ev, source="architecture")

            parent = self.rails.get(r["source"].get("from_rail", ""))
            if r["source"]["type"] == "ldo" and parent and i > 0:
                v_in = parent.get("max_v", parent["nominal_v"])
                p = (v_in - r["nominal_v"]) * i
                self.f.add("ARC", self.sev("PWR-005", "info"), f"LDO '{r['id']}' dissipates up to {p:.2f} W", refs,
                           [{"kind": "calculation",
                             "calculation": f"({v_in} V - {r['nominal_v']} V) x {i:.3f} A = {p:.2f} W"},
                            {"kind": "rule", "rule_id": "PWR-005"}],
                           source="architecture", confidence="high")


def check_spec(spec: dict, project: str, rules: dict | None = None) -> tuple[list[str], Findings]:
    """Validate the schema, then run the deterministic checks. Returns (schema errors, findings)."""
    findings = Findings(project)
    errors = validate("spec", spec)
    if errors:
        return errors, findings
    SpecChecker(spec, findings, rules).run()
    return [], findings
