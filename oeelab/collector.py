"""
Reference collector for contract v1, and a model of the v0 pipeline for comparison.

`Collector.handle()` is plain Python: topic, payload bytes and the time of
receipt go in, rows come out in SQLite. `Collector.listen()` wires it to a
broker. Keeping the two apart is what makes every rule testable without MQTT.

What v1 lets the collector do, that v0 cannot:
  * drop a repeated message by (boot, seq) instead of guessing from its content
  * know that messages went missing (a hole in seq)
  * recover the pieces of the missing messages (the difference in `total`)
  * tell a node reboot from a counter going backwards (a new `boot`)
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from .contract import parse_topic, parse_ts, schema_for, validate

SCHEMA = """
CREATE TABLE IF NOT EXISTS pieces(machine TEXT, signal TEXT, ts TEXT, n INTEGER, recovered INTEGER);
CREATE TABLE IF NOT EXISTS states(machine TEXT, ts TEXT, running INTEGER, category TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS events(machine TEXT, signal TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS gaps(machine TEXT, ts TEXT, missing INTEGER);
CREATE TABLE IF NOT EXISTS dlq(topic TEXT, payload TEXT, reason TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS node(machine TEXT PRIMARY KEY, boot TEXT, last_seq INTEGER, online INTEGER,
                                fw TEXT, totals TEXT, reboots INTEGER DEFAULT 0, duplicates INTEGER DEFAULT 0);
"""


class Collector:
    def __init__(self, db: str = ":memory:"):
        self.db = sqlite3.connect(db, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ------------------------------------------------------------------ core
    def handle(self, topic: str, raw: bytes, received: datetime, retained: bool = False) -> str:
        """Process one message. Returns what was done with it, for logs and tests.

        `retained=True` means the broker delivered it from its retained store when we
        subscribed: it is old news of unknown age, not something that just happened.
        """
        parsed = parse_topic(topic)
        if parsed is None:
            return self._dlq(topic, raw, "topic is not a v1 topic", received)
        machine, signal = parsed
        try:
            p = json.loads(raw)
        except ValueError:
            return self._dlq(topic, raw, "payload is not JSON", received)
        errors = validate(signal, p)
        if errors:
            return self._dlq(topic, raw, "; ".join(errors), received)

        key = machine.base
        ts = (parse_ts(p["ts"]) if "ts" in p else received).isoformat()
        node = self._node(key)
        kind = schema_for(signal)

        if kind == "status":
            if p["online"] and p["boot"] != node["boot"]:
                self._new_boot(key, node, p["boot"])
            self.db.execute("UPDATE node SET online=?, fw=COALESCE(?, fw) WHERE machine=?",
                            (int(p["online"]), p.get("fw"), key))
            self.db.commit()
            return "online" if p["online"] else "offline"
        if kind == "command":
            return "ignored"

        if retained:
            return self._retained(key, node, kind, signal, p, ts)

        if p["boot"] != node["boot"]:
            node = self._new_boot(key, node, p["boot"])
        elif node["last_seq"] is not None:
            if p["seq"] <= node["last_seq"]:
                self.db.execute("UPDATE node SET duplicates=duplicates+1 WHERE machine=?", (key,))
                self.db.commit()
                return "duplicate"
            if p["seq"] > node["last_seq"] + 1:
                self.db.execute("INSERT INTO gaps VALUES(?,?,?)", (key, ts, p["seq"] - node["last_seq"] - 1))
        self.db.execute("UPDATE node SET last_seq=? WHERE machine=?", (p["seq"], key))

        done = "stored"
        if kind == "counter":
            totals = json.loads(node["totals"])
            delta = p["total"] - totals.get(signal, 0)
            if delta > 0:
                recovered = max(delta - p["value"], 0)
                self.db.execute("INSERT INTO pieces VALUES(?,?,?,?,?)", (key, signal, ts, delta, recovered))
                totals[signal] = p["total"]
                self.db.execute("UPDATE node SET totals=? WHERE machine=?", (json.dumps(totals), key))
                done = f"counted {delta}" + (f" (recovered {recovered})" if recovered else "")
            else:
                done = "counted 0"
        elif kind == "state":
            self.db.execute("INSERT INTO states VALUES(?,?,?,?,?)", (key, ts, int(p["running"]), p.get("category"), p.get("reason")))
        else:
            self.db.execute("INSERT INTO events VALUES(?,?,?)", (key, signal, ts))
        self.db.commit()
        return done

    def _retained(self, key, node, kind, signal, p, ts) -> str:
        """A retained message is a level, not an event: it has no place in the seq order."""
        if kind == "state":
            self.db.execute("INSERT INTO states VALUES(?,?,?,?,?)", (key, ts, int(p["running"]), p.get("category"), p.get("reason")))
            self.db.commit()
            return "stored"
        if kind != "counter":
            return "ignored"
        totals = json.loads(node["totals"])
        if p["boot"] != node["boot"] or signal not in totals:
            # First sight of this counter: pieces made before we were listening cannot be
            # placed in time, so the total becomes the baseline and nothing is counted.
            if p["boot"] != node["boot"]:
                node = self._new_boot(key, node, p["boot"])
                totals = {}
            totals[signal] = p["total"]
            self.db.execute("UPDATE node SET totals=? WHERE machine=?", (json.dumps(totals), key))
            self.db.commit()
            return "baseline"
        delta = p["total"] - totals[signal]
        if delta <= 0:
            return "counted 0"
        # Same boot, and the total moved while we were away: those pieces are ours to recover.
        self.db.execute("INSERT INTO pieces VALUES(?,?,?,?,?)", (key, signal, ts, delta, delta))
        totals[signal] = p["total"]
        self.db.execute("UPDATE node SET totals=? WHERE machine=?", (json.dumps(totals), key))
        self.db.commit()
        return f"counted {delta} (recovered {delta})"

    def _node(self, key: str) -> sqlite3.Row:
        self.db.execute("INSERT OR IGNORE INTO node(machine, totals) VALUES(?, '{}')", (key,))
        return self.db.execute("SELECT * FROM node WHERE machine=?", (key,)).fetchone()

    def _new_boot(self, key: str, node: sqlite3.Row, boot: str) -> sqlite3.Row:
        reboot = int(node["boot"] is not None)
        self.db.execute("UPDATE node SET boot=?, last_seq=NULL, totals='{}', reboots=reboots+? WHERE machine=?",
                        (boot, reboot, key))
        return self._node(key)

    def _dlq(self, topic: str, raw: bytes, reason: str, received: datetime) -> str:
        self.db.execute("INSERT INTO dlq VALUES(?,?,?,?)",
                        (topic, raw.decode("utf-8", "replace")[:500], reason, received.isoformat()))
        self.db.commit()
        return "rejected"

    # ------------------------------------------------------------------ reading
    def pieces(self, machine_base: str, signal: str = "output-good") -> int:
        row = self.db.execute("SELECT COALESCE(SUM(n),0) FROM pieces WHERE machine=? AND signal=?",
                              (machine_base, signal)).fetchone()
        return row[0]

    def rows(self, sql: str, *args) -> list[dict]:
        return [dict(r) for r in self.db.execute(sql, args)]

    # ------------------------------------------------------------------ broker
    def listen(self, host: str = "127.0.0.1", port: int = 1883, prefix: str = "oee") -> mqtt.Client:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="oeelab-collector")
        client.on_connect = lambda c, *_: c.subscribe(f"{prefix}/uns/#", qos=1)
        client.on_message = lambda c, u, msg: msg.payload and self.handle(
            msg.topic, msg.payload, datetime.now(timezone.utc), retained=bool(msg.retain))
        client.connect(host, port)
        client.loop_start()
        return client


class LegacyPipeline:
    """
    The rule a v0 pulse has to survive on the receiving side, as plain code:
    a message whose topic and bytes are identical to one accepted in the last
    `window_s` seconds of receipt time is treated as a repeat and dropped.

    The rule is sensible: it protects against a broker or a bridge delivering
    the same message twice. The trouble is the v0 payload. With `ts` in whole
    seconds and nothing else that changes, two real pieces in the same second
    are byte-identical, and so is every piece while the node clock reads 1970.

    This model was checked against a production backend that applies the same
    rule: 30 pieces at 3 per second were counted as 11, and 8 pieces from a
    node without clock, one every 2 s, were counted as 3.
    """

    def __init__(self, window_s: float = 5.0):
        self.window_s = window_s
        self.seen: dict[str, datetime] = {}
        self.count: dict[str, int] = {}
        self.dropped = 0

    def handle(self, topic: str, raw: bytes, received: datetime) -> str:
        key = hashlib.blake2b(topic.encode() + b"|" + raw, digest_size=8).hexdigest()
        last = self.seen.get(key)
        if last is not None and (received - last).total_seconds() < self.window_s:
            self.dropped += 1
            return "duplicate"
        self.seen[key] = received
        self.count[topic] = self.count.get(topic, 0) + 1
        return "counted 1"
