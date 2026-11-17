"""Small helpers shared by the demo, the notebooks, the figures and the tests."""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from .collector import Collector, LegacyPipeline
from .contract import Machine
from .node import Node
from .scenario import MACHINES, SHIFT_START, play, script

LABELER = Machine("packaging", "line-1", "cell-a", "labeler-01")


class Clock:
    """The time of receipt, set by whoever drives the experiment."""
    def __init__(self):
        self.now: datetime = SHIFT_START


def bench(dialect: str, clock_synced: bool = True, loss: float = 0.0, seed: int = 1, machine: Machine = LABELER):
    """A node wired straight to a receiver, no broker. Returns (node, receiver, clock).

    v1 goes to the reference Collector, v0 to the model of the legacy rule.
    `loss` is the fraction of messages that vanish on the way (QoS 0 on bad Wi-Fi).
    """
    clock, rng = Clock(), random.Random(seed)
    rx = Collector() if dialect == "v1" else LegacyPipeline()

    def wire(topic: str, payload: bytes, retain: bool):
        if loss and rng.random() < loss:
            return
        if dialect == "v0" and not topic.endswith(("output-good", "output-defect")):
            return
        rx.handle(topic, payload, clock.now)

    node = Node(machine, dialect, clock_synced=clock_synced, boot="a1b2c3", wire=wire)
    return node, rx, clock


def counted(rx, machine: Machine = LABELER, signal: str = "output-good") -> int:
    if isinstance(rx, Collector):
        return rx.pieces(machine.base, signal)
    return rx.count.get(machine.topic(signal), 0)


def pulses(node: Node, clock: Clock, n: int, period_s: float, start: datetime = SHIFT_START):
    """n good pieces, one every period_s seconds."""
    node.connect(start)
    for i in range(n):
        clock.now = start + timedelta(seconds=i * period_s)
        node.piece(clock.now)


def run_shift(dialect: str = "v1", loss: float = 0.0):
    """Play the three-machine shift. Returns {name: (receiver, truth)}."""
    out = {}
    for name, (machine, _) in MACHINES.items():
        steps, truth = script(name)
        node, rx, clock = bench(dialect, loss=loss, machine=machine)
        node.connect(steps[0][0])
        for t, action in steps:
            clock.now = t
            play_step(node, t, action)
        out[name] = (rx, truth)
    return out


def play_step(node: Node, t: datetime, action: str):
    if action == "start":
        node.press_start(t)
    elif action == "stop":
        node.press_stop(t)
    elif action in ("good", "defect"):
        node.piece(t, good=action == "good")
    elif action == "link_down":
        node.link(False, t)
    elif action == "link_up":
        node.link(True, t)
