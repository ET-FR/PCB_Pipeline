"""Parsing of component values as written in KiCad (10k, 4k7, 100nF, 25V)."""

from __future__ import annotations

import re

_PREFIX = {
    "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3,
    "": 1.0, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9,
}
_UNITS = ("F", "H", "V", "A", "W", "Ω", "ohm", "Ohm", "R")

_PLAIN = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([pnuµμmkKMG]?)\s*([A-Za-zΩ]*)\s*$")
_INFIX = re.compile(r"^\s*([0-9]+)([pnuµμmkKMGR])([0-9]+)\s*([A-Za-zΩ]*)\s*$")


def parse_value(text: str | None) -> float | None:
    """Return the value in base SI units, or None if it cannot be parsed."""
    if not text:
        return None
    text = text.strip().split()[0] if text.strip() else text
    m = _INFIX.match(text)
    if m:
        whole, mid, frac, _unit = m.groups()
        mult = 1.0 if mid == "R" else _PREFIX[mid]
        return float(f"{whole}.{frac}") * mult
    m = _PLAIN.match(text)
    if not m:
        return None
    number, prefix, unit = m.groups()
    if unit and not any(unit.startswith(u) for u in _UNITS):
        # e.g. "10uF" is fine, "10mil" is not a value we handle
        if prefix == "m" and unit.startswith("il"):
            return None
    return float(number) * _PREFIX.get(prefix, 1.0)
