"""Deterministic rule engine. Python computes; agents judge."""

from __future__ import annotations

from pathlib import Path

import yaml

from ..datasheet.library import SheetLibrary
from ..findings import Findings
from ..kicad_import import Netlist, is_ground, is_unconnected
from ..values import parse_value

DEFAULT_RULES = Path(__file__).resolve().parents[3] / "rules" / "checklist.yaml"


def load_rules(path: Path | None = None) -> dict:
    data = yaml.safe_load((path or DEFAULT_RULES).read_text())
    rules = {r["id"]: r for r in data.get("rules", [])}
    return {"rules": rules, "rails": data.get("rails") or {}}


class RuleEngine:
    def __init__(self, netlist: Netlist, library: SheetLibrary, findings: Findings,
                 rules: dict, rails: dict[str, float] | None = None):
        self.n = netlist
        self.lib = library
        self.f = findings
        self.rules = rules["rules"]
        self.rails = {**rules.get("rails", {}), **(rails or {})}

    # helpers ---------------------------------------------------------------

    def rail(self, net: str | None) -> float | None:
        if net is None:
            return None
        if is_ground(net):
            return 0.0
        return self.rails.get(net, self.rails.get(net.lstrip("/")))

    def sev(self, rule_id: str) -> str:
        return self.rules.get(rule_id, {}).get("severity", "major")

    def param(self, rule_id: str, key: str, default):
        return self.rules.get(rule_id, {}).get("params", {}).get(key, default)

    def enabled(self, rule_id: str) -> bool:
        return rule_id in self.rules

    # rules -----------------------------------------------------------------

    def run(self) -> Findings:
        for rid, fn in [("SYM-001", self.sym_001), ("PIN-001", self.pin_rules),
                        ("CAP-001", self.cap_001), ("ABS-001", self.abs_001),
                        ("EQ-001", self.eq_001)]:
            if self.enabled(rid):
                fn()
        return self.f

    def sym_001(self):
        for ref, c in sorted(self.n.components.items()):
            if not c.is_passive and not c.mpn:
                self.f.add("SYM", self.sev("SYM-001"), f"{ref} has no MPN field", [ref],
                           [{"kind": "rule", "rule_id": "SYM-001",
                             "summary": "Without an MPN, no component sheet can be built for this part."}],
                           source="rules", suggestion="Add an MPN field to the symbol.")

    def pin_rules(self):
        for ref, c in sorted(self.n.components.items()):
            sheet = self.lib.get(c.mpn)
            if not sheet:
                continue
            for pin in sheet["pins"]:
                req = pin.get("requirement", "none")
                if req == "none":
                    continue
                net, _node = self.n.node(ref, pin_name=pin["name"], pin_number=pin["number"])
                nodes = self.n.nets.get(net) if net else None
                floating = is_unconnected(net, nodes)
                ev = [{"kind": "datasheet", "mpn": c.mpn, "page": pin["page"],
                       "summary": f"Pin {pin['name']} requirement: {req}"
                                  + (f" ({pin['notes']})" if pin.get("notes") else "")}]
                if net:
                    ev.append({"kind": "netlist", "net": net,
                               "summary": f"{len(nodes or [])} node(s) on this net"})
                if req in ("must_connect", "no_float") and floating and self.enabled("PIN-001"):
                    self.f.add("PIN", self.sev("PIN-001"), f"{ref}.{pin['name']} is floating",
                               [ref], ev, source="rules", nets=[net] if net else None)
                elif req == "must_not_connect" and not floating and self.enabled("PIN-002"):
                    self.f.add("PIN", self.sev("PIN-002"), f"{ref}.{pin['name']} must not be connected",
                               [ref], ev, source="rules", nets=[net])
                elif req == "tie_to_ground" and not is_ground(net) and self.enabled("PIN-001"):
                    self.f.add("PIN", self.sev("PIN-001"), f"{ref}.{pin['name']} must be tied to ground",
                               [ref], ev, source="rules", nets=[net] if net else None)

    def cap_001(self):
        min_ratio = self.param("CAP-001", "min_ratio", 1.5)
        rec_ratio = self.param("CAP-001", "recommended_ratio", 2.0)
        for ref, c in sorted(self.n.components.items()):
            if c.prefix != "C":
                continue
            rated = parse_value(c.fields.get("Voltage") or c.fields.get("voltage"))
            nets = list(self.n.nets_of(ref).values())
            volts = [v for v in (self.rail(n) for n in nets) if v is not None]
            if len(volts) < 2 or rated is None:
                if rated is None and any(v for v in volts):
                    self.f.add("CAP", "minor", f"{ref} has no Voltage field", [ref],
                               [{"kind": "rule", "rule_id": "CAP-001",
                                 "summary": "Derating cannot be checked without a voltage rating."}],
                               source="rules", nets=nets)
                continue
            applied = max(volts) - min(volts)
            if applied <= 0:
                continue
            ratio = rated / applied
            calc = f"{rated:g} V rated / {applied:g} V applied = {ratio:.2f}"
            if ratio < 1:
                sev, title = "critical", f"{ref} rated below applied voltage"
            elif ratio < min_ratio:
                sev, title = self.sev("CAP-001"), f"{ref} insufficient voltage derating"
            elif ratio < rec_ratio:
                sev, title = "minor", f"{ref} derating below recommended ratio"
            else:
                continue
            self.f.add("CAP", sev, title, [ref],
                       [{"kind": "calculation", "rule_id": "CAP-001", "calculation": calc,
                         "summary": f"Minimum ratio {min_ratio}, recommended {rec_ratio}. "
                                    "Ceramic capacitors also lose capacitance under DC bias."}],
                       source="rules", nets=nets,
                       suggestion=f"Use a part rated at least {applied * rec_ratio:g} V.")

    def abs_001(self):
        for ref, c in sorted(self.n.components.items()):
            sheet = self.lib.get(c.mpn)
            if not sheet:
                continue
            for lim in sheet.get("absolute_maximum", []):
                if "max" not in lim or lim.get("unit") != "V":
                    continue
                net, _ = self.n.node(ref, pin_name=lim["param"])
                v = self.rail(net)
                if v is None or v <= lim["max"]:
                    continue
                self.f.add("ABS", self.sev("ABS-001"),
                           f"{ref}.{lim['param']} rail exceeds absolute maximum", [ref],
                           [{"kind": "datasheet", "mpn": c.mpn, "page": lim["page"],
                             "summary": f"Absolute maximum {lim['param']} = {lim['max']:g} V"},
                            {"kind": "calculation", "net": net,
                             "calculation": f"{v:g} V on {net} > {lim['max']:g} V"}],
                           source="rules", nets=[net])

    def eq_001(self):
        tol = self.param("EQ-001", "tolerance_percent", 2) / 100
        for ref, c in sorted(self.n.components.items()):
            sheet = self.lib.get(c.mpn)
            if not sheet:
                continue
            for eq in sheet.get("equations", []):
                self._check_equation(ref, c.mpn, eq, tol)

    def _endpoint_net(self, ref: str, endpoint: str) -> str | None:
        if endpoint.startswith("@"):
            return endpoint
        net, _ = self.n.node(ref, pin_name=endpoint)
        return net

    def _check_equation(self, ref: str, mpn: str, eq: dict, tol: float):
        env = dict(eq.get("constants", {}))
        parts, target_net = [], None
        for var, (a, b) in eq.get("variables", {}).items():
            na, nb = self._endpoint_net(ref, a), self._endpoint_net(ref, b)
            found = None
            for pref, pc in self.n.components.items():
                if not pc.is_passive or pref == ref:
                    continue
                pnets = set(self.n.nets_of(pref).values())
                if len(pnets) != 2:
                    continue
                ok, tgt = True, None
                for want in (na, nb):
                    if want == "@GND":
                        ok &= any(is_ground(x) for x in pnets)
                    elif want == "@TARGET":
                        others = [x for x in pnets if x not in (na, nb) and not is_ground(x)]
                        ok &= len(others) == 1
                        tgt = others[0] if others else None
                    else:
                        ok &= want in pnets
                if ok:
                    found = (pref, pc, tgt)
                    break
            if not found:
                return  # cannot resolve, the conformity agent will look at it
            pref, pc, tgt = found
            value = parse_value(pc.value)
            if value is None:
                return
            env[var] = value
            parts.append(f"{var}={pref} ({pc.value})")
            target_net = target_net or tgt
        try:
            result = eval(eq["expression"], {"__builtins__": {}}, env)  # noqa: S307, expression from validated sheet
        except Exception:
            return
        target = self.rail(target_net)
        if target is None or target == 0:
            return
        err = (result - target) / target
        if abs(err) <= tol:
            return
        unit = eq.get("unit", "")
        self.f.add("EQ", self.sev("EQ-001"),
                   f"{ref} {eq['name']} off target", [ref] + [p.split("=")[1].split()[0] for p in parts],
                   [{"kind": "datasheet", "mpn": mpn, "page": eq["page"],
                     "summary": f"{eq['name']}: {eq['expression']}"},
                    {"kind": "calculation", "net": target_net,
                     "calculation": f"{', '.join(parts)} gives {result:.4g} {unit}, "
                                    f"target {target:g} {unit} on {target_net} ({err:+.1%})"}],
                   source="rules", nets=[target_net])
