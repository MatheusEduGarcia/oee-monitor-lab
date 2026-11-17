"""Run the simulated week through the collector and return the indicators, measured and true."""
from __future__ import annotations

from datetime import timedelta

from .collector import Collector
from .kpi import Times, line_ope, plant_ofe, times
from .lab import Clock
from .node import Node
from .week import DAYS, FLEET, LINE_LAST, WEEK_START, play_week, week_script

END = WEEK_START + timedelta(days=DAYS)


def run_week(seed: int = 11):
    """Returns (measured, truth): {machine: Times} each, the truth built from the script itself."""
    c, clock = Collector(), Clock()
    measured, truth = {}, {}
    for name, (machine, line, cycle, *_ ) in FLEET.items():
        steps, t = week_script(name, seed)
        node = Node(machine, "v1", boot="a1b2c3", wire=lambda tp, p, r: c.handle(tp, p, clock.now))
        play_week(node, steps, clock)
        measured[name] = times(c, machine.base, WEEK_START, END, cycle)
        truth[name] = Times((END - WEEK_START).total_seconds(), dict(t.seconds), t.good, t.defect, list(t.failures), cycle)
    return measured, truth, c


def lines(ts: dict[str, Times]) -> dict:
    """OPE per line and the plant OFE."""
    out, ofe_in = {}, {}
    for line, last in LINE_LAST.items():
        members = {n: ts[n] for n, f in FLEET.items() if f[1] == line}
        bottleneck = max(FLEET[n][2] for n in members)
        ope = line_ope(members, last, bottleneck)
        planned = max(t.base("OEE") for t in members.values())
        out[line] = ope
        ofe_in[line] = (ope * planned, planned)
    out["plant"] = plant_ofe(ofe_in)
    return out
