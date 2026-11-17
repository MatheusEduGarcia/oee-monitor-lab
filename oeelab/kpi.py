"""
Indicators beyond OEE, computed from what the collector stored.

All of the OEE family share performance and quality. They differ only in the time
that availability is measured against, so here each one is written in its
"valuable time" form:

    indicator = (pieces good × ideal cycle) / reference time

which is exactly availability × performance × quality with that reference time.

    reference time                                         indicator
    calendar time                                          TEEP
    calendar − closed (plant shut, no demand)              OAE
    calendar − closed − unscheduled (no shift programmed)  OOE
    OOE time − planned stops (meal, changeover, PM)        OEE

OAE, OPE and OFE have no single definition in the literature. The ones used here
are stated in docs/indicators.md, and every number in this repository uses them.

Line and plant:
    OPE (line)  = good pieces leaving the line × ideal cycle of the bottleneck / planned time of the line
    OFE (plant) = Σ line valuable time / Σ line planned time      (lines weighted by their planned time)

Reliability, from stops whose category is `failure` only:
    MTBF = run time / number of failures
    MTTR = time in failure / number of failures
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from .collector import Collector

CATEGORIES = ("closed", "unscheduled", "planned", "failure", "unplanned")


@dataclass
class Times:
    calendar: float
    seconds: dict            # run + every category, in seconds
    good: int
    defect: int
    failures: list           # (reason, seconds)
    ideal_cycle_s: float

    @property
    def valuable(self) -> float:
        return self.good * self.ideal_cycle_s

    def base(self, name: str) -> float:
        s, c = self.seconds, self.calendar
        return {"TEEP": c,
                "OAE": c - s["closed"],
                "OOE": c - s["closed"] - s["unscheduled"],
                "OEE": c - s["closed"] - s["unscheduled"] - s["planned"]}[name]

    def indicator(self, name: str) -> float:
        b = self.base(name)
        return self.valuable / b if b else 0.0

    @property
    def availability(self) -> float:
        return self.seconds["run"] / self.base("OEE")

    @property
    def performance(self) -> float:
        return (self.good + self.defect) * self.ideal_cycle_s / self.seconds["run"]

    @property
    def quality(self) -> float:
        return self.good / (self.good + self.defect)

    @property
    def mtbf_h(self) -> float:
        return self.seconds["run"] / len(self.failures) / 3600 if self.failures else float("inf")

    @property
    def mttr_min(self) -> float:
        return sum(s for _, s in self.failures) / len(self.failures) / 60 if self.failures else 0.0

    def by_mode(self) -> dict:
        out = defaultdict(lambda: [0, 0.0])
        for mode, s in self.failures:
            out[mode][0] += 1
            out[mode][1] += s
        return {m: {"failures": n, "downtime_min": s / 60, "mttr_min": s / n / 60} for m, (n, s) in out.items()}


def times(c: Collector, machine: str, start: datetime, end: datetime, ideal_cycle_s: float) -> Times:
    """Walk the stored states of one machine and put every second of [start, end] in a bucket."""
    rows = c.rows("SELECT ts, running, category, reason FROM states WHERE machine=? ORDER BY ts, rowid", machine)
    seconds = defaultdict(float)
    failures = []
    cur, since = None, start
    for r in rows + [{"ts": end.isoformat(), "running": None, "category": None, "reason": None}]:
        ts = min(max(datetime.fromisoformat(r["ts"]), start), end)
        if cur is not None:
            span = (ts - since).total_seconds()
            key = "run" if cur["running"] else (cur["category"] or "unplanned")
            seconds[key] += span
            if key == "failure" and span > 0:
                if failures and failures[-1][2] == since:          # same failure, state repeated
                    failures[-1] = (failures[-1][0], failures[-1][1] + span, ts)
                else:
                    failures.append((cur["reason"] or "unknown", span, ts))
        cur, since = r, ts
    for k in ("run",) + CATEGORIES:
        seconds.setdefault(k, 0.0)
    count = lambda s: c.rows("SELECT COALESCE(SUM(n),0) n FROM pieces WHERE machine=? AND signal=? AND ts>=? AND ts<=?",
                             machine, s, start.isoformat(), end.isoformat())[0]["n"]
    return Times((end - start).total_seconds(), dict(seconds), count("output-good"), count("output-defect"),
                 [(m, s) for m, s, _ in failures], ideal_cycle_s)


def line_ope(machines: dict[str, Times], last: str, bottleneck_cycle_s: float) -> float:
    """OPE of a line: what left the line, at the pace of its slowest machine, against the line's planned time."""
    planned = max(t.base("OEE") for t in machines.values())
    return machines[last].good * bottleneck_cycle_s / planned if planned else 0.0


def plant_ofe(lines: dict[str, tuple[float, float]]) -> float:
    """OFE: {line: (valuable seconds, planned seconds)} -> plant figure, lines weighted by planned time."""
    v = sum(a for a, _ in lines.values())
    p = sum(b for _, b in lines.values())
    return v / p if p else 0.0
