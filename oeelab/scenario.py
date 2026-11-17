"""
A reproducible shift for three machines, used by the demo, the figures and the tests.

Each machine gets a script of (time, action) built from a seeded random generator:
it runs, stops for a while, makes mostly good pieces, loses the network once.
The script is the ground truth: what really happened on the floor, against which
whatever the collector stored can be checked.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .contract import Machine
from .node import Node

SHIFT_START = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)      # 06:00 in São Paulo
SHIFT_HOURS = 8

MACHINES = {
    "filler-01": (Machine("packaging", "line-1", "cell-a", "filler-01"), 2.0),
    "capper-01": (Machine("packaging", "line-1", "cell-a", "capper-01"), 2.0),
    "press-02": (Machine("stamping", "line-2", "cell-b", "press-02"), 6.0),
}


@dataclass
class Truth:
    good: int = 0
    defect: int = 0
    run_s: float = 0.0
    offline_s: float = 0.0
    stops: list = field(default_factory=list)


def script(name: str, seed: int = 7) -> tuple[list[tuple[datetime, str]], Truth]:
    """Build the list of (time, action) for one machine and the truth it implies."""
    _, cycle = MACHINES[name]
    rng = random.Random(f"{seed}-{name}")
    end = SHIFT_START + timedelta(hours=SHIFT_HOURS)
    t, steps, truth = SHIFT_START + timedelta(minutes=rng.uniform(2, 8)), [], Truth()
    outage_at = SHIFT_START + timedelta(hours=rng.uniform(2, 5))
    outage_s, outage_done = rng.uniform(120, 420), False
    while t < end:
        steps.append((t, "start"))
        run_until = min(t + timedelta(minutes=rng.uniform(25, 80)), end)
        run_from = t
        while t < run_until:
            if not outage_done and t >= outage_at:
                steps.append((t, "link_down"))
                steps.append((t + timedelta(seconds=outage_s), "link_up"))
                truth.offline_s, outage_done = outage_s, True
            t += timedelta(seconds=cycle * rng.uniform(1.0, 1.35))
            if t >= end:
                t = end
                break
            good = rng.random() > 0.03
            steps.append((t, "good" if good else "defect"))
            truth.good += good
            truth.defect += not good
        truth.run_s += (t - run_from).total_seconds()
        steps.append((t, "stop"))
        if t >= end:
            break
        stop_s = rng.choice([45, 90, 180, 420, 900])
        truth.stops.append((t, stop_s))
        t += timedelta(seconds=stop_s)
    return sorted(steps, key=lambda s: s[0]), truth


def play(node: Node, steps: list[tuple[datetime, str]]):
    """Feed a script to a node, in order, with the script's own clock."""
    from .lab import play_step
    node.connect(steps[0][0])
    for t, action in steps:
        play_step(node, t, action)
