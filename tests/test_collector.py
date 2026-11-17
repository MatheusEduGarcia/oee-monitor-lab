from datetime import timedelta

from oeelab.adapter import Adapter, Route
from oeelab.collector import Collector
from oeelab.contract import Machine, dumps, validate
from oeelab.lab import LABELER, bench, counted, pulses, run_shift
from oeelab.oee import compute
from oeelab.scenario import MACHINES, SHIFT_HOURS, SHIFT_START

T0 = SHIFT_START
M = LABELER


def msg(seq, total, value=1, boot="a1b2c3"):
    return dumps({"v": 1, "seq": seq, "boot": boot, "value": value, "total": total})


def test_fast_pieces_v0_undercounts_v1_does_not():
    node, rx, clock = bench("v0"); pulses(node, clock, 30, 1 / 3)
    assert counted(rx) == 10                       # one per second survives
    node, rx, clock = bench("v1"); pulses(node, clock, 30, 1 / 3)
    assert counted(rx) == 30


def test_node_without_clock():
    node, rx, clock = bench("v0", clock_synced=False); pulses(node, clock, 8, 2.0)
    assert counted(rx) == 3                        # every payload is the same bytes
    node, rx, clock = bench("v1", clock_synced=False); pulses(node, clock, 8, 2.0)
    assert counted(rx) == 8
    assert all("ts" not in p for _, p in node.sent)


def test_repeated_delivery_is_dropped_by_seq():
    c = Collector()
    assert c.handle(M.topic("output-good"), msg(0, 1), T0) == "counted 1"
    assert c.handle(M.topic("output-good"), msg(0, 1), T0) == "duplicate"
    assert c.pieces(M.base) == 1


def test_lost_messages_are_detected_and_their_pieces_recovered():
    c = Collector()
    c.handle(M.topic("output-good"), msg(0, 1), T0)
    assert c.handle(M.topic("output-good"), msg(4, 5), T0) == "counted 4 (recovered 3)"
    assert c.rows("SELECT missing FROM gaps") == [{"missing": 3}]
    assert c.pieces(M.base) == 5


def test_reboot_restarts_the_count_without_going_negative():
    c = Collector()
    c.handle(M.topic("output-good"), msg(0, 40, boot="aaaa"), T0)
    assert c.handle(M.topic("output-good"), msg(0, 2, value=2, boot="bbbb"), T0) == "counted 2"
    assert c.pieces(M.base) == 42
    assert c.rows("SELECT reboots FROM node")[0]["reboots"] == 1


def test_bad_messages_go_to_the_dead_letter_table_with_the_reason():
    c = Collector()
    assert c.handle(M.topic("output-good"), b'{"ts":"2026-11-10T09:00:00","value":1}', T0) == "rejected"
    assert c.handle("fabrica/linha1/m1/input/1", b"1", T0) == "rejected"
    reasons = [r["reason"] for r in c.rows("SELECT reason FROM dlq")]
    assert "required property" in reasons[0] and reasons[1] == "topic is not a v1 topic"


def test_network_outage_v1_keeps_every_piece_v0_loses_them():
    for name, (rx, truth) in run_shift("v1").items():
        machine = MACHINES[name][0]
        assert counted(rx, machine) == truth.good
        assert counted(rx, machine, "output-defect") == truth.defect
    lost = {name: truth.good - counted(rx, MACHINES[name][0]) for name, (rx, truth) in run_shift("v0").items()}
    assert all(n > 0 for n in lost.values())


def test_five_percent_message_loss_costs_almost_nothing_in_v1():
    for name, (rx, truth) in run_shift("v1", loss=0.05).items():
        assert truth.good - counted(rx, MACHINES[name][0]) <= 2      # only a lost final message can cost pieces
        assert rx.rows("SELECT COALESCE(SUM(missing),0) m FROM gaps")[0]["m"] > 0


def test_oee_matches_the_ground_truth_of_the_script():
    end = SHIFT_START + timedelta(hours=SHIFT_HOURS)
    for name, (rx, truth) in run_shift("v1").items():
        machine, cycle = MACHINES[name]
        o = compute(rx, machine.base, SHIFT_START, end, cycle)
        assert abs(o.run_s - truth.run_s) < 1
        assert (o.good, o.defect) == (truth.good, truth.defect)
        assert 0.80 < o.availability < 1 and 0.75 < o.performance < 1 and 0.95 < o.quality < 1
        assert abs(o.oee - o.availability * o.performance * o.quality) < 1e-12


def test_adapter_turns_the_three_v0_dialects_into_valid_v1():
    m = Machine("machining", "line-1", "cell-a", "lathe-01")
    a = Adapter({"lab/line1/lathe/output": Route(m, "output-good"),
                 "fabrica/linha1/m1/input/1": Route(m, "start"),
                 "lab/line1/lathe/running": Route(m, "state")}, boot="c0ffee")
    out = [a.translate("lab/line1/lathe/output", b'{"ts":"2026-11-10T09:00:00","value":1,"machine_id":"X"}', T0),
           a.translate("lab/line1/lathe/output", b'{"ts":"2026-11-10T09:00:00","value":1,"machine_id":"X"}', T0),
           a.translate("fabrica/linha1/m1/input/1", b'{"label":"Start","state":1,"ts":123456}', T0),
           a.translate("lab/line1/lathe/running", b"ON", T0)]
    for topic, payload in out:
        signal = topic.rsplit("/", 1)[1]
        assert validate(signal, payload) == [], (topic, payload)
    assert [p["seq"] for _, p in out] == [0, 1, 2, 3]
    assert out[1][1]["total"] == 2                                   # identical bytes, two pieces
    assert a.translate("fabrica/linha1/m1/input/1", b'{"label":"Start","state":0,"ts":1}', T0) is None
    assert a.translate("unknown/topic", b"1", T0) is None


def test_retained_counter_is_a_baseline_for_a_new_collector_and_a_recovery_for_a_restarted_one():
    fresh = Collector()
    assert fresh.handle(M.topic("output-good"), msg(900, 500), T0, retained=True) == "baseline"
    assert fresh.pieces(M.base) == 0                       # made before we listened: not ours to place in time
    assert fresh.handle(M.topic("output-good"), msg(901, 501), T0) == "counted 1"

    restarted = Collector()
    restarted.handle(M.topic("output-good"), msg(10, 100), T0)             # before going down
    assert restarted.handle(M.topic("output-good"), msg(60, 150), T0, retained=True) == "counted 50 (recovered 50)"
    assert restarted.pieces(M.base) == 150
