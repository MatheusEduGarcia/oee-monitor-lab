"""
Contract v1: topics and payloads between a collection node and whatever consumes it.

The written version is docs/protocol.md. This module is the same contract as code:
it builds and parses topics, builds payloads and validates them against the
JSON Schemas in schemas/.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
VERSION = 1

# signal -> (schema, retained)
SIGNALS = {
    "start": ("event", False),
    "stop": ("event", False),
    "output-good": ("counter", True),
    "output-defect": ("counter", True),
    "state": ("state", True),
    "status": ("status", True),
}
RELAY_SET = re.compile(r"^relay/([1-8])/set$")
RELAY_ACK = re.compile(r"^relay/([1-8])$")
SEGMENT = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def slug(text: str) -> str:
    """'Linha 1 / Envase' -> 'linha-1-envase'. Lower case, ASCII, hyphens only."""
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")


@dataclass(frozen=True)
class Machine:
    area: str
    line: str
    cell: str
    machine: str
    prefix: str = "oee"

    @property
    def base(self) -> str:
        return f"{self.prefix}/uns/{self.area}/{self.line}/{self.cell}/{self.machine}"

    def topic(self, signal: str) -> str:
        if signal not in SIGNALS and not RELAY_SET.match(signal) and not RELAY_ACK.match(signal):
            raise ValueError(f"unknown signal {signal!r}")
        return f"{self.base}/{signal}"


def parse_topic(topic: str) -> tuple[Machine, str] | None:
    """Split a v1 topic into (machine, signal). None when it is not a v1 topic."""
    parts = topic.split("/")
    if "uns" not in parts:
        return None
    i = parts.index("uns")
    prefix, rest = "/".join(parts[:i]), parts[i + 1:]
    if len(rest) < 5 or not all(SEGMENT.match(p) for p in rest[:4]):
        return None
    signal = "/".join(rest[4:])
    if signal not in SIGNALS and not RELAY_SET.match(signal) and not RELAY_ACK.match(signal):
        return None
    return Machine(*rest[:4], prefix=prefix), signal


def schema_for(signal: str) -> str:
    if signal in SIGNALS:
        return SIGNALS[signal][0]
    if RELAY_SET.match(signal):
        return "command"
    if RELAY_ACK.match(signal):
        return "command"
    raise ValueError(signal)


def retained(signal: str) -> bool:
    return SIGNALS[signal][1] if signal in SIGNALS else bool(RELAY_ACK.match(signal))


@lru_cache
def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text()))


def validate(signal: str, payload: object) -> list[str]:
    """Return the list of problems. Empty means the payload honours the contract."""
    if not isinstance(payload, dict):
        return ["payload is not a JSON object"]
    errors = [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}"
              for e in _validator(schema_for(signal)).iter_errors(payload)]
    if schema_for(signal) == "counter" and not errors and payload["value"] > payload["total"]:
        errors.append("total: cannot be smaller than value")
    return errors


def utc(ts: datetime) -> str:
    """Format a datetime the way the contract requires: UTC, milliseconds, Z."""
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def parse_ts(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def dumps(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode()
