"""Netlist graph and functional group proposal."""

from __future__ import annotations

import networkx as nx

from .kicad_import import Netlist, is_ground


def build_graph(netlist: Netlist, ignore_nets: list[str] | None = None) -> nx.Graph:
    """Bipartite graph: component nodes ('C:U1') and net nodes ('N:/VIN')."""
    ignore = {n.upper() for n in (ignore_nets or [])}
    g = nx.Graph()
    for ref, comp in netlist.components.items():
        g.add_node(f"C:{ref}", kind="component", passive=comp.is_passive)
    for net, nodes in netlist.nets.items():
        if net.upper() in ignore or is_ground(net):
            continue
        g.add_node(f"N:{net}", kind="net")
        for n in nodes:
            g.add_edge(f"C:{n.ref}", f"N:{net}")
    return g


def functional_groups(netlist: Netlist, depth: int = 2, ignore_nets: list[str] | None = None) -> list[dict]:
    """One group per active part: the part plus passives reachable within `depth` hops.

    A hop is component -> net -> component. Expansion stops at other active parts, which
    are listed as `boundary` so the orchestrator can merge groups when needed.
    """
    g = build_graph(netlist, ignore_nets)
    groups = []
    for ref, comp in sorted(netlist.components.items()):
        if comp.is_passive:
            continue
        members, boundary, nets = {ref}, set(), set()
        frontier = [f"C:{ref}"]
        for _ in range(depth):
            nxt = []
            for cnode in frontier:
                for net_node in g.neighbors(cnode):
                    nets.add(net_node[2:])
                    for other in g.neighbors(net_node):
                        oref = other[2:]
                        if oref in members:
                            continue
                        if netlist.components[oref].is_passive:
                            members.add(oref)
                            nxt.append(other)
                        else:
                            boundary.add(oref)
            frontier = nxt
        groups.append({
            "id": ref,
            "anchor": ref,
            "mpn": comp.mpn,
            "members": sorted(members),
            "boundary": sorted(boundary - members),
            "nets": sorted(nets),
        })
    return groups
