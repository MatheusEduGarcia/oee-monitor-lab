"""
Bench check for a real board: does it honour contract v1?

    python -m oeelab.check_node oee/uns/packaging/line-1/cell-a/filler-01 [--host 127.0.0.1] [--seconds 60]

Subscribes to everything under the machine path, runs each message through the
reference collector and prints a verdict per message and a summary at the end.
The exit code is 1 if any message was refused.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from .collector import Collector


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("base", help="machine topic base, e.g. oee/uns/packaging/line-1/cell-a/filler-01")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--seconds", type=float, default=60)
    args = ap.parse_args(argv)

    c = Collector()

    def on_message(client, userdata, msg):
        verdict = c.handle(msg.topic, msg.payload, datetime.now(timezone.utc))
        print(f"{verdict:28s} {msg.topic.removeprefix(args.base)}  {msg.payload.decode('utf-8', 'replace')[:110]}")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="oeelab-check-node")
    client.on_connect = lambda cl, *_: cl.subscribe(args.base.rstrip("/") + "/#", qos=1)
    client.on_message = on_message
    client.connect(args.host, args.port)
    client.loop_start()
    time.sleep(args.seconds)
    client.loop_stop()

    rejected = c.rows("SELECT topic, reason FROM dlq")
    node = c.rows("SELECT * FROM node")
    print("\nsummary")
    for n in node:
        print(f"  boot {n['boot']}  last seq {n['last_seq']}  reboots {n['reboots']}  duplicates {n['duplicates']}  totals {n['totals']}")
    print(f"  gaps: {c.rows('SELECT COALESCE(SUM(missing),0) m FROM gaps')[0]['m']} messages missing")
    print(f"  refused: {len(rejected)}")
    for r in rejected[:10]:
        print(f"    {r['topic']}: {r['reason']}")
    return 1 if rejected else 0


if __name__ == "__main__":
    sys.exit(main())
