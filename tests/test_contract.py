import json
from datetime import datetime, timezone

import pytest

from oeelab.contract import Machine, parse_topic, parse_ts, retained, slug, utc, validate

M = Machine("packaging", "line-1", "cell-a", "filler-01")
OK = {"v": 1, "seq": 7, "boot": "a1b2c3", "ts": "2026-11-10T09:00:00.123Z"}


def test_topic_round_trip():
    topic = M.topic("output-good")
    assert topic == "oee/uns/packaging/line-1/cell-a/filler-01/output-good"
    assert parse_topic(topic) == (M, "output-good")
    assert parse_topic(M.topic("relay/3/set")) == (M, "relay/3/set")


@pytest.mark.parametrize("topic", [
    "fabrica/linha1/m1/input/1",                              # v0, no uns marker
    "oee/uns/packaging/line-1/cell-a/filler-01",              # no signal
    "oee/uns/Packaging/line-1/cell-a/filler-01/start",        # upper case
    "oee/uns/packaging/line-1/cell-a/filler-01/speed",        # unknown signal
    "oee/uns/packaging/line-1/cell-a/filler-01/relay/9/set",  # relay out of range
])
def test_topics_outside_the_contract_are_refused(topic):
    assert parse_topic(topic) is None


def test_slug():
    assert slug("Linha 1 / Envase") == "linha-1-envase"
    assert slug("Prensa Nº 2") == "prensa-no-2"


def test_valid_payloads():
    assert validate("start", {**OK, "value": 1}) == []
    assert validate("output-good", {**OK, "value": 1, "total": 42}) == []
    assert validate("state", {**OK, "value": 1, "running": True}) == []
    assert validate("status", {"v": 1, "online": False}) == []
    assert validate("status", {"v": 1, "online": True, "boot": "a1b2c3", "fw": "1.0.0"}) == []
    assert validate("relay/1/set", {"v": 1, "value": 1, "id": "c-17"}) == []


def test_ts_is_optional_but_never_local_or_epoch_style():
    no_ts = {k: v for k, v in OK.items() if k != "ts"}
    assert validate("start", {**no_ts, "value": 1}) == []
    assert validate("start", {**OK, "ts": "2026-11-10T06:00:00", "value": 1})          # no Z: refused
    assert validate("start", {**OK, "ts": 123456, "value": 1})                         # millis: refused


@pytest.mark.parametrize("payload", [
    {"ts": "2026-11-10T09:00:00", "value": 1, "machine_id": "X"},      # v0 full
    {"label": "Start", "state": 1, "ts": 123456},                       # v0 webconfig
    {**OK, "value": 1},                                                 # counter without total
    {**OK, "value": 5, "total": 3},                                     # total smaller than value
    {**OK, "value": 0, "total": 3},                                     # a counter message counts something
])
def test_bad_counters_are_refused(payload):
    assert validate("output-good", payload)


def test_birth_needs_boot_and_firmware():
    assert validate("status", {"v": 1, "online": True})


def test_retained_flags():
    assert retained("state") and retained("status") and retained("output-good")
    assert not retained("start") and not retained("relay/1/set") and retained("relay/1")


def test_utc_format_round_trip():
    t = datetime(2026, 11, 10, 9, 0, 0, 123000, tzinfo=timezone.utc)
    assert utc(t) == "2026-11-10T09:00:00.123Z" and parse_ts(utc(t)) == t


def test_schemas_are_valid_json_schema():
    from jsonschema import Draft202012Validator
    from oeelab.contract import ROOT
    for f in (ROOT / "schemas").glob("*.schema.json"):
        Draft202012Validator.check_schema(json.loads(f.read_text()))
