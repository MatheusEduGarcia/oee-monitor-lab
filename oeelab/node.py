"""
A virtual collection node: what the ESP32 does, without the ESP32.

It has the same inputs as the board (start, stop, good piece, defect, running
contact) and publishes over MQTT exactly what a real node would. Two dialects:

    dialect="v0"   the payloads of the firmware in firmware/, as it runs today
    dialect="v1"   the contract in docs/protocol.md

Time is passed in by the caller, so a whole shift can be replayed in seconds
and every test is deterministic. The link can be cut with `link_up = False`:
the machine keeps producing, the node keeps counting, nothing is published.
That is the Wi-Fi dropping, and it is where the two dialects differ most.

Pass `wire=` to deliver messages to a function instead of a broker.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from .contract import Machine, dumps, retained, utc

FW = "oee-node-sim 1.0.0"


class Node:
    def __init__(self, machine: Machine, dialect: str = "v1", host: str = "127.0.0.1", port: int = 1883,
                 clock_synced: bool = True, boot: str | None = None, machine_id: str | None = None, wire=None):
        assert dialect in ("v0", "v1")
        self.m, self.dialect, self.host, self.port = machine, dialect, host, port
        self.clock_synced = clock_synced
        self.machine_id = machine_id or machine.machine.upper()
        self.boot = boot or secrets.token_hex(3)
        self.seq = 0
        self.total = {"output-good": 0, "output-defect": 0}
        self.unsent = {"output-good": 0, "output-defect": 0}
        self.running = False
        self.link_up = True
        self.sent: list[tuple[str, dict]] = []
        # wire(topic, payload_bytes, retain): deliver without a broker, for fast deterministic runs
        self.wire = wire
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"node-{machine.machine}-{self.boot}")
        will = {"v": 1, "online": False} if dialect == "v1" else {"online": False}
        self.client.will_set(self.m.topic("status"), dumps(will), qos=1, retain=True)

    # ------------------------------------------------------------------ link
    def connect(self, now: datetime):
        if self.wire is None:
            self.client.connect(self.host, self.port, keepalive=30)
            self.client.loop_start()
        self.link_up = True
        self._birth(now)

    def disconnect(self, graceful: bool = False):
        """graceful=False is a power cut: the broker publishes the last will."""
        if self.wire is not None:
            return
        if not graceful:
            sock = self.client.socket()
            if sock is not None:
                sock.close()
        self.client.loop_stop()
        if graceful:
            self.client.disconnect()

    def link(self, up: bool, now: datetime):
        """Cut or restore the network without rebooting the node."""
        was_down, self.link_up = not self.link_up, up
        if up and was_down:
            self._birth(now)
            self._state(now)
            if self.dialect == "v1":
                for signal, n in self.unsent.items():
                    if n:
                        self._counter(signal, now)

    # ------------------------------------------------------------------ inputs
    def press_start(self, now: datetime):
        self._event("start", now)
        self.set_running(True, now)

    def press_stop(self, now: datetime):
        self._event("stop", now)
        self.set_running(False, now)

    def set_running(self, running: bool, now: datetime):
        if running != self.running:
            self.running = running
            self._state(now)

    def piece(self, now: datetime, good: bool = True, n: int = 1):
        signal = "output-good" if good else "output-defect"
        self.total[signal] += n
        self.unsent[signal] += n
        self._counter(signal, now)

    # ------------------------------------------------------------------ payloads
    def _ts(self, now: datetime) -> str | None:
        if self.dialect == "v0":
            # second resolution, local time without offset, epoch when not synchronised
            return now.strftime("%Y-%m-%dT%H:%M:%S") if self.clock_synced else "1970-01-01T00:00:00"
        return utc(now) if self.clock_synced else None

    def _envelope(self, now: datetime, **fields) -> dict:
        if self.dialect == "v0":
            return {"ts": self._ts(now), **fields, "machine_id": self.machine_id}
        p = {"v": 1, "seq": self.seq, "boot": self.boot, **fields}
        if self.clock_synced:
            p["ts"] = self._ts(now)
        return p

    def _event(self, signal: str, now: datetime):
        self._publish(signal, self._envelope(now, value=1))

    def _counter(self, signal: str, now: datetime):
        if self.dialect == "v0":
            # one message per pulse, nothing cumulative: a pulse that is not sent is gone
            self.unsent[signal] = 0
            self._publish(signal, self._envelope(now, value=1))
            return
        if not self.link_up:
            return
        n, self.unsent[signal] = self.unsent[signal], 0
        self._publish(signal, self._envelope(now, value=n, total=self.total[signal]))

    def _state(self, now: datetime):
        self._publish("state", self._envelope(now, value=int(self.running), running=self.running))

    def _birth(self, now: datetime):
        if self.dialect == "v0":
            self._publish("status", {"online": True, "ip": "192.168.0.50", "rssi": -61, "client": self.client._client_id.decode()})
            return
        p = {"v": 1, "online": True, "boot": self.boot, "fw": FW, "ip": "192.168.0.50", "rssi": -61,
             "uptime_s": 0, "clock_synced": self.clock_synced}
        if self.clock_synced:
            p["ts"] = utc(now)
        self._publish("status", p, count=False)

    def _publish(self, signal: str, payload: dict, count: bool = True):
        if not self.link_up:
            return
        topic = self.m.topic(signal)
        # v0 only retains state and status; PubSubClient can only publish with QoS 0
        retain = retained(signal) if self.dialect == "v1" else signal in ("state", "status")
        if self.wire is not None:
            self.wire(topic, dumps(payload), retain)
        else:
            self.client.publish(topic, dumps(payload), qos=0, retain=retain)
        self.sent.append((topic, json.loads(dumps(payload))))
        if count and self.dialect == "v1":
            self.seq = (self.seq + 1) % 2**32


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
