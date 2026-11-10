"""Import a KiCad schematic through kicad-cli and parse the XML netlist."""

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Node:
    ref: str
    pin: str
    pin_function: str = ""
    pin_type: str = ""


@dataclass
class Component:
    ref: str
    value: str = ""
    footprint: str = ""
    lib: str = ""
    part: str = ""
    fields: dict[str, str] = field(default_factory=dict)

    @property
    def mpn(self) -> str | None:
        for key in ("MPN", "mpn", "Manufacturer_Part_Number", "MFN"):
            if self.fields.get(key):
                return self.fields[key].strip()
        return None

    @property
    def prefix(self) -> str:
        return "".join(ch for ch in self.ref if ch.isalpha())

    @property
    def is_passive(self) -> bool:
        return self.prefix in {"R", "C", "L", "FB", "TP", "J", "H", "MH"}


@dataclass
class Netlist:
    components: dict[str, Component]
    nets: dict[str, list[Node]]

    def nets_of(self, ref: str) -> dict[str, str]:
        """Map pin number to net name for one component."""
        out = {}
        for net, nodes in self.nets.items():
            for n in nodes:
                if n.ref == ref:
                    out[n.pin] = net
        return out

    def node(self, ref: str, pin_name: str | None = None, pin_number: str | None = None):
        """Find the (net, node) of a component pin by function name, then by number."""
        candidates = []
        for net, nodes in self.nets.items():
            for n in nodes:
                if n.ref != ref:
                    continue
                if pin_name and _pin_name_matches(n.pin_function, pin_name):
                    return net, n
                if pin_number and n.pin == pin_number:
                    candidates.append((net, n))
        return candidates[0] if candidates else (None, None)


def _pin_name_matches(pin_function: str, name: str) -> bool:
    if not pin_function:
        return False
    # KiCad may suffix duplicated names: "GND_1", "GND_2"
    pf = pin_function.upper()
    nm = name.upper()
    return pf == nm or pf.split("_")[0] == nm


def export_netlist(schematic: Path, out_dir: Path, kicad_cli: str = "kicad-cli") -> Path:
    """Export the XML netlist with kicad-cli (KiCad resolves hierarchy and labels)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "netlist.xml"
    cmd = [kicad_cli, "sch", "export", "netlist", "--format", "kicadxml",
           "--output", str(out), str(schematic)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"'{kicad_cli}' not found. Install KiCad 8+ or pass --netlist with an exported netlist."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"kicad-cli failed: {exc.stderr.strip()}") from exc
    return out


def parse_netlist_xml(path: Path) -> Netlist:
    root = ET.parse(path).getroot()
    components: dict[str, Component] = {}
    for comp in root.iter("comp"):
        ref = comp.get("ref", "")
        lib = comp.find("libsource")
        fields = {}
        fields_el = comp.find("fields")
        if fields_el is not None:
            for f in fields_el.iter("field"):
                fields[f.get("name", "")] = (f.text or "").strip()
        # KiCad 8 also writes <property name=... value=...>
        for prop in comp.iter("property"):
            fields.setdefault(prop.get("name", ""), prop.get("value", ""))
        components[ref] = Component(
            ref=ref,
            value=(comp.findtext("value") or "").strip(),
            footprint=(comp.findtext("footprint") or "").strip(),
            lib=lib.get("lib", "") if lib is not None else "",
            part=lib.get("part", "") if lib is not None else "",
            fields=fields,
        )
    nets: dict[str, list[Node]] = {}
    for net in root.iter("net"):
        name = net.get("name", "")
        nets[name] = [
            Node(ref=n.get("ref", ""), pin=n.get("pin", ""),
                 pin_function=n.get("pinfunction", ""), pin_type=n.get("pintype", ""))
            for n in net.iter("node")
        ]
    return Netlist(components=components, nets=nets)


def is_ground(net: str | None) -> bool:
    if not net:
        return False
    name = net.strip("/").upper()
    return name in {"0", "GND", "AGND", "DGND", "PGND", "GNDA", "GNDD", "GNDPWR"} or name.startswith("GND")


def is_unconnected(net: str | None, nodes: list[Node] | None) -> bool:
    """A pin is floating if KiCad marks it unconnected or nothing else is on its net."""
    if net is None or net.startswith("unconnected-"):
        return True
    return nodes is not None and len(nodes) < 2
