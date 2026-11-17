"""
A reproducible week for three machines on two lines, with the reasons behind every stop.

The shift scenario of notebook 03 only knows "running" and "stopped". To tell OEE
from OOE, TEEP and the others, and to compute MTBF and MTTR, the simulator needs
what a plant really has:

  * a calendar: line 1 runs three shifts Monday to Friday and one on Saturday;
    line 2 runs two shifts Monday to Friday; Sunday the plant is closed;
  * planned stops inside every shift: a 30 min meal break and one changeover a day,
    plus a 2 h preventive maintenance on Wednesday;
  * failures, each with a mode, drawn with a mean time between failures per machine,
    and repair times per mode;
  * other unplanned stops that are not failures (no material).

Every stop is published with its category and reason (contract v1, optional fields
of `state`). The script also returns the truth: seconds in each time category,
pieces made, and every failure with its duration.
"""
from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .contract import Machine
from .node import Node

WEEK_START = datetime(2026, 11, 9, 3, 0, tzinfo=timezone.utc)      # Monday 00:00 in São Paulo
DAYS = 7
SHIFTS = {"A": (6, 14), "B": (14, 22), "C": (22, 30)}             # local hours, C ends 06:00 next day
LOCAL = timedelta(hours=-3)

# name: (machine, line, ideal cycle s, MTBF h, failure modes {mode: (weight, mean repair min)})
FLEET = {
    "filler-01": (Machine("packaging", "line-1", "cell-a", "filler-01"), "line-1", 2.0, 6.0,
                  {"jam": (6, 8), "seal-wear": (2, 45), "sensor-fault": (2, 20)}),
    "capper-01": (Machine("packaging", "line-1", "cell-a", "capper-01"), "line-1", 2.0, 9.0,
                  {"jam": (5, 6), "torque-head": (3, 35), "sensor-fault": (2, 20)}),
    "press-02": (Machine("stamping", "line-2", "cell-b", "press-02"), "line-2", 6.0, 12.0,
                 {"die-change-fault": (3, 60), "hydraulic-leak": (1, 120), "jam": (6, 10)}),
}
CALENDAR = {   # line -> {weekday: shifts}; Monday = 0
    "line-1": {0: "ABC", 1: "ABC", 2: "ABC", 3: "ABC", 4: "ABC", 5: "A"},
    "line-2": {0: "AB", 1: "AB", 2: "AB", 3: "AB", 4: "AB"},
}
LINE_LAST = {"line-1": "capper-01", "line-2": "press-02"}         # where finished goods leave each line


@dataclass
class WeekTruth:
    seconds: dict = field(default_factory=lambda: defaultdict(float))   # run, closed, unscheduled, planned, failure, unplanned
    good: int = 0
    defect: int = 0
    failures: list = field(default_factory=list)                        # (mode, seconds)


def _shift_windows(line: str):
    """Scheduled (start, end) in UTC for the week."""
    out = []
    for d in range(DAYS):
        day = WEEK_START + timedelta(days=d)
        for code in CALENDAR[line].get(d, ""):
            a, b = SHIFTS[code]
            out.append((day + timedelta(hours=a), day + timedelta(hours=b), code))
    return out


def week_script(name: str, seed: int = 11):
    """(steps, truth). A step is (time, action, *args) with action in
    stop(category, reason) | run | pieces(good, defect)."""
    machine, line, cycle, mtbf_h, modes = FLEET[name]
    rng = random.Random(f"{seed}-{name}")
    end = WEEK_START + timedelta(days=DAYS)
    truth, steps = WeekTruth(), []
    t = WEEK_START

    def off(until):
        """Time with no shift, split at local midnight: Sunday is closed, the rest unscheduled."""
        nonlocal t
        last = None
        while t < until:
            local = t + LOCAL
            midnight = (local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)) - LOCAL
            seg = min(until, midnight)
            category, reason = ("closed", "plant-closed") if local.weekday() == 6 else ("unscheduled", "no-shift")
            if category != last:
                steps.append((t, "stop", category, reason))
                last = category
            truth.seconds[category] += (seg - t).total_seconds()
            t = seg

    names, weights = list(modes), [w for w, _ in modes.values()]
    next_failure = rng.expovariate(1 / (mtbf_h * 3600))            # run seconds until the next failure
    for start, stop, code in _shift_windows(line):
        weekday = (start + LOCAL).weekday()
        off(start)
        # planned events inside the shift, as (offset min, duration min, reason)
        plan = [(225 + rng.uniform(-20, 20), 30, "meal")]
        if code == "A":
            plan.append((5, 25, "changeover"))
            if weekday == 2:
                plan.append((60, 120, "preventive"))
        if rng.random() < 0.15:
            plan.append((rng.uniform(60, 400), rng.uniform(15, 40), "no-material"))
        plan.sort()
        events = [(start + timedelta(minutes=o), timedelta(minutes=d), r) for o, d, r in plan]
        steps.append((t, "run"))
        while t < stop:
            nxt = max(events[0][0], t) if events else stop
            # run until the next planned event, a failure, or the end of the shift
            run_until = min(nxt, stop, t + timedelta(seconds=next_failure))
            span = (run_until - t).total_seconds()
            n = int(span / (cycle * rng.uniform(1.05, 1.3)))
            d = sum(rng.random() < 0.03 for _ in range(n))
            good, defect = n - d, d
            if n:
                steps.append((run_until, "pieces", good, defect))
                truth.good += good
                truth.defect += defect
            truth.seconds["run"] += span
            next_failure -= span
            t = run_until
            if t >= stop:
                break
            if next_failure <= 0.001 or not events or events[0][0] > t:   # breakdown
                mode = rng.choices(names, weights)[0]
                repair = min(rng.expovariate(1 / (modes[mode][1] * 60)), (stop - t).total_seconds())
                repair = max(repair, 60)
                steps.append((t, "stop", "failure", mode))
                truth.seconds["failure"] += min(repair, (stop - t).total_seconds())
                truth.failures.append((mode, min(repair, (stop - t).total_seconds())))
                t = min(t + timedelta(seconds=repair), stop)
                next_failure = rng.expovariate(1 / (mtbf_h * 3600))
            else:
                at, dur, reason = events.pop(0)
                category = "unplanned" if reason == "no-material" else "planned"
                done = min(max(at, t) + dur, stop)            # an event delayed by a repair starts now
                steps.append((t, "stop", category, reason))
                truth.seconds[category] += (done - t).total_seconds()
                t = done
            if t < stop:
                steps.append((t, "run"))
    off(end)
    return steps, truth


def play_week(node: Node, steps, clock=None):
    node.connect(steps[0][0])
    for t, action, *args in steps:
        if clock is not None:
            clock.now = t
        if action == "stop":
            node.set_running(False, t, *args)
        elif action == "run":
            node.set_running(True, t)
        else:
            g, d = args
            if g:
                node.piece(t, True, g)
            if d:
                node.piece(t, False, d)
