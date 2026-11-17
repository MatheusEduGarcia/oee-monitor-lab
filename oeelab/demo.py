"""
The whole lab in one command, against a real broker:

    python -m oeelab.demo            # needs an MQTT broker on 127.0.0.1:1883

Three virtual nodes replay a shift through the broker, the reference collector
stores it, and the result is checked against what the script says really happened.
"""
from __future__ import annotations

import sys
import time
from datetime import timedelta

from .collector import Collector
from .lab import play_step
from .node import Node
from .oee import compute
from .scenario import MACHINES, SHIFT_HOURS, SHIFT_START, script


def main(host: str = "127.0.0.1", port: int = 1883) -> int:
    collector = Collector()
    listener = collector.listen(host, port)
    time.sleep(0.5)
    truths, nodes = {}, []
    for name, (machine, _) in MACHINES.items():
        steps, truths[name] = script(name)
        node = Node(machine, "v1", host, port)
        node.connect(steps[0][0])
        nodes.append(node)
        for i, (t, action) in enumerate(steps):
            play_step(node, t, action)
            if i % 200 == 0:
                time.sleep(0.05)              # let the broker and the collector breathe
        print(f"{name}: replayed {len(steps)} steps")
    time.sleep(2.0)

    end = SHIFT_START + timedelta(hours=SHIFT_HOURS)
    ok = True
    print(f"\n{'machine':11s} {'good':>13s} {'defect':>11s}   A      P      Q      OEE")
    for name, (machine, cycle) in MACHINES.items():
        o, t = compute(collector, machine.base, SHIFT_START, end, cycle), truths[name]
        match = (o.good, o.defect) == (t.good, t.defect)
        ok &= match
        print(f"{name:11s} {o.good:6d}/{t.good:<6d} {o.defect:5d}/{t.defect:<5d} "
              f"{o.availability:6.1%} {o.performance:6.1%} {o.quality:6.1%} {o.oee:6.1%}  {'ok' if match else 'MISMATCH'}")
    gaps = collector.rows("SELECT COALESCE(SUM(missing),0) m FROM gaps")[0]["m"]
    rec = collector.rows("SELECT COALESCE(SUM(recovered),0) r FROM pieces")[0]["r"]
    print(f"\nmessages lost in transit: {gaps}   pieces recovered from `total`: {rec}   refused: "
          f"{collector.rows('SELECT COUNT(*) n FROM dlq')[0]['n']}")
    for node in nodes:
        for signal in ("state", "status", "output-good", "output-defect"):     # leave the broker clean
            node.client.publish(node.m.topic(signal), b"", retain=True)
        time.sleep(0.2)
        node.disconnect(graceful=True)
    listener.loop_stop()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
