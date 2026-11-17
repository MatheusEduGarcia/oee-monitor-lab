"""OEE from what the collector stored: states give time, counters give pieces."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .collector import Collector


@dataclass
class Oee:
    planned_s: float
    run_s: float
    good: int
    defect: int
    ideal_cycle_s: float

    @property
    def availability(self) -> float:
        return self.run_s / self.planned_s if self.planned_s else 0.0

    @property
    def performance(self) -> float:
        return (self.good + self.defect) * self.ideal_cycle_s / self.run_s if self.run_s else 0.0

    @property
    def quality(self) -> float:
        total = self.good + self.defect
        return self.good / total if total else 0.0

    @property
    def oee(self) -> float:
        return self.availability * self.performance * self.quality


def run_intervals(c: Collector, machine: str, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Periods inside [start, end] in which the machine reported running."""
    rows = c.rows("SELECT ts, running FROM states WHERE machine=? ORDER BY ts", machine)
    out, since = [], None
    for r in rows:
        ts = datetime.fromisoformat(r["ts"])
        if r["running"] and since is None:
            since = ts
        elif not r["running"] and since is not None:
            out.append((since, ts))
            since = None
    if since is not None:
        out.append((since, end))
    return [(max(a, start), min(b, end)) for a, b in out if b > start and a < end]


def compute(c: Collector, machine: str, start: datetime, end: datetime, ideal_cycle_s: float) -> Oee:
    run = sum((b - a).total_seconds() for a, b in run_intervals(c, machine, start, end))
    count = lambda s: c.rows("SELECT COALESCE(SUM(n),0) n FROM pieces WHERE machine=? AND signal=? AND ts>=? AND ts<=?",
                             machine, s, start.isoformat(), end.isoformat())[0]["n"]
    return Oee((end - start).total_seconds(), run, count("output-good"), count("output-defect"), ideal_cycle_s)
