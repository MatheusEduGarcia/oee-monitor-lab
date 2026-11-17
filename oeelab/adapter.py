"""
v0 to v1 at the edge: upgrade the protocol without reflashing a single board.

A small process sits next to the broker, subscribes to the topics the boards
already publish and republishes each message as contract v1. It can add what
only needs the message itself (a receipt timestamp, a sequence, a running
total) and it cannot add what was never sent: a pulse lost between the board
and the broker stays lost. That limit is the argument for doing the firmware
change described in docs/firmware_v1_changes.md.

Three dialects found in the field are understood:

    full     {"ts": "2026-11-10T09:00:00", "value": 1, "machine_id": "X"}
    webcfg   {"label": "Start", "state": 1, "ts": 123456}   on <base>/input/<n>
    bare     1   or   ON
"""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime

from .contract import Machine, utc

ON = {"1", "true", "on", "high"}


@dataclass
class Route:
    """Where a legacy topic goes in the v1 namespace."""
    machine: Machine
    signal: str


@dataclass
class Adapter:
    routes: dict[str, Route]
    boot: str = field(default_factory=lambda: secrets.token_hex(3))
    seq: dict[str, int] = field(default_factory=dict)
    totals: dict[tuple[str, str], int] = field(default_factory=dict)

    def translate(self, topic: str, raw: bytes, received: datetime) -> tuple[str, dict] | None:
        """Return (v1 topic, v1 payload), or None when the message carries no event."""
        route = self.routes.get(topic)
        if route is None:
            return None
        active = self._active(raw)
        if active is None:
            return None
        base, signal = route.machine.base, route.signal
        if signal != "state" and not active:
            return None                      # release edge of a button or of a pulse
        p = {"v": 1, "seq": self.seq.get(base, 0), "boot": self.boot, "ts": utc(received)}
        self.seq[base] = p["seq"] + 1
        if signal in ("output-good", "output-defect"):
            total = self.totals.get((base, signal), 0) + 1
            self.totals[(base, signal)] = total
            p |= {"value": 1, "total": total}
        elif signal == "state":
            p |= {"value": int(active), "running": active}
        else:
            p |= {"value": 1}
        return route.machine.topic(signal), p

    @staticmethod
    def _active(raw: bytes) -> bool | None:
        text = raw.decode("utf-8", "replace").strip()
        try:
            data = json.loads(text)
        except ValueError:
            data = text
        if isinstance(data, dict):
            for k in ("value", "state", "val", "v"):
                if k in data:
                    data = data[k]
                    break
            else:
                return None
        return str(data).strip().lower() in ON or (isinstance(data, (int, float)) and data > 0)
