"""End to end through a real broker. Skipped when nothing listens on 1883."""
import json
import socket
import time

import paho.mqtt.client as mqtt
import pytest

from oeelab.collector import Collector
from oeelab.contract import Machine
from oeelab.node import Node, now_utc


def broker_up() -> bool:
    try:
        socket.create_connection(("127.0.0.1", 1883), timeout=0.5).close()
        return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not broker_up(), reason="no MQTT broker on 127.0.0.1:1883")


def wait(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_node_to_collector_and_last_will():
    m = Machine("test", f"line-{int(time.time()) % 100000}", "cell-a", "m-01", prefix="oeetest")
    c = Collector()
    listener = c.listen(prefix="oeetest")
    time.sleep(0.4)
    node = Node(m, "v1")
    node.connect(now_utc())
    node.press_start(now_utc())
    for _ in range(5):
        node.piece(now_utc())
    assert wait(lambda: c.pieces(m.base) == 5)
    assert c.rows("SELECT online, fw FROM node WHERE machine=?", m.base) == [{"online": 1, "fw": "oee-node-sim 1.0.0"}]

    # a subscriber that arrives late still learns state, count and health from retained messages
    got = {}
    late = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    late.on_message = lambda cl, u, msg: msg.payload and got.__setitem__(msg.topic.rsplit("/", 1)[1], json.loads(msg.payload))
    late.connect("127.0.0.1", 1883); late.subscribe(m.base + "/#"); late.loop_start()
    assert wait(lambda: {"state", "status", "output-good"} <= set(got))
    assert got["state"]["running"] is True and got["output-good"]["total"] == 5 and got["status"]["online"] is True

    node.disconnect(graceful=False)                      # power cut: the broker speaks for the node
    assert wait(lambda: got["status"]["online"] is False, timeout=8)
    assert wait(lambda: c.rows("SELECT online FROM node WHERE machine=?", m.base)[0]["online"] == 0)

    for sig in ("state", "status", "output-good"):       # leave the broker clean
        late.publish(f"{m.base}/{sig}", b"", retain=True)
    time.sleep(0.3); late.loop_stop(); listener.loop_stop()
