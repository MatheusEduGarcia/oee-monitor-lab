"""
Figures for the README, the docs and the notebooks.

Diagrams are Graphviz DOT rendered by the `dot` binary; charts are matplotlib.
Run:  python -m oeelab.figures      -> writes docs/img/*.png
"""
from __future__ import annotations

import subprocess
from datetime import timedelta
from pathlib import Path

import matplotlib.pyplot as plt

from .contract import ROOT
from .lab import bench, counted, play_step, pulses, run_shift
from .oee import compute
from .scenario import MACHINES, SHIFT_HOURS, SHIFT_START, script

IMG = ROOT / "docs" / "img"
RED, BLUE, GREEN, GREY, ORANGE = "#c0392b", "#2980b9", "#27ae60", "#7f8c8d", "#e67e22"
NODE = 'node [shape=box style="rounded,filled" fontname="Helvetica" fontsize=11 fontcolor=white]; edge [fontname="Helvetica" fontsize=9 color="#555555"];'


def render(dot: str, name: str) -> Path:
    IMG.mkdir(parents=True, exist_ok=True)
    out = IMG / f"{name}.png"
    subprocess.run(["dot", "-Tpng", "-Gdpi=130", "-o", str(out)], input=dot.encode(), check=True)
    return out


ARCHITECTURE = f"""digraph A {{ rankdir=LR; nodesep=0.3; ranksep=0.6; {NODE}
  subgraph cluster_m {{ label="Machine"; fontname="Helvetica"; style=dashed; color="{GREY}";
    start [label="start / stop\\nbuttons" fillcolor="{GREY}"]; sensor [label="piece sensor\\n(optical, inductive)" fillcolor="{GREY}"];
    run [label="running contact\\n(relay, dry)" fillcolor="{GREY}"]; }}
  node1 [label="Collection node\\nESP32 + opto-isolated inputs\\ncounts, timestamps, numbers" fillcolor="{ORANGE}"];
  broker [label="MQTT broker\\nretained state\\nlast will" fillcolor="{BLUE}"];
  subgraph cluster_s {{ label="Consumers"; fontname="Helvetica"; style=dashed; color="{GREY}";
    col [label="Collector\\nvalidates, dedups by seq,\\nrecovers from total" fillcolor="{GREEN}"];
    dash [label="OEE dashboard" fillcolor="{GREEN}"]; other [label="historian, UNS,\\nanything else" fillcolor="{GREEN}"]; }}
  start -> node1 [label="24 V"]; sensor -> node1 [label="pulse"]; run -> node1 [label="level"];
  node1 -> broker [label="Wi-Fi, MQTT\\ncontract v1"]; broker -> col; broker -> dash; broker -> other;
  broker -> node1 [label="relay/n/set" style=dashed];
}}"""

WIRING = f"""digraph W {{ rankdir=LR; nodesep=0.25; ranksep=0.9; {NODE}
  subgraph cluster_f {{ label="Field, 24 V DC"; fontname="Helvetica"; style=dashed; color="{GREY}";
    b1 [label="START button (NO)" fillcolor="{GREY}"]; b2 [label="STOP button (NO)" fillcolor="{GREY}"];
    s1 [label="piece sensor (NPN/PNP)" fillcolor="{GREY}"]; b3 [label="reject button (NO)" fillcolor="{GREY}"];
    k1 [label="machine running relay (NO)" fillcolor="{GREY}"]; }}
  opto [label="Opto-isolated input stage\\n24 V in, 3.3 V out\\nactive LOW" fillcolor="{RED}"];
  subgraph cluster_e {{ label="ESP32 (INPUT_PULLUP, LOW = active)"; fontname="Helvetica"; style=dashed; color="{ORANGE}";
    g32 [label="GPIO32  start" fillcolor="{ORANGE}"]; g33 [label="GPIO33  stop" fillcolor="{ORANGE}"];
    g25 [label="GPIO25  output-good" fillcolor="{ORANGE}"]; g26 [label="GPIO26  output-defect" fillcolor="{ORANGE}"];
    g27 [label="GPIO27  state" fillcolor="{ORANGE}"]; g2 [label="GPIO2  LED: MQTT connected" fillcolor="{ORANGE}"]; }}
  b1 -> opto; b2 -> opto; s1 -> opto; b3 -> opto; k1 -> opto;
  opto -> g32; opto -> g33; opto -> g25; opto -> g26; opto -> g27;
}}"""

LIFECYCLE = f"""digraph L {{ rankdir=TB; nodesep=0.5; ranksep=0.4; {NODE}
  boot [label="Power on\\nnew boot id, seq = 0" fillcolor="{GREY}"];
  ap [label="Setup portal\\nAP OEE-Config-XXXX\\n192.168.4.1" fillcolor="{ORANGE}"];
  wifi [label="Join Wi-Fi\\nsync clock (NTP)" fillcolor="{BLUE}"];
  mqtt [label="Connect to broker\\nregister last will" fillcolor="{BLUE}"];
  birth [label="Birth\\nstatus online (retained)\\nstate (retained)" fillcolor="{GREEN}"];
  run [label="Run\\nevents, counters with total,\\nstate on change" fillcolor="{GREEN}"];
  lost [label="Link lost\\nkeep counting locally" fillcolor="{RED}"];
  boot -> ap [label="no saved config"]; ap -> wifi [label="saved"]; boot -> wifi [label="config found"];
  wifi -> mqtt; mqtt -> birth; birth -> run; run -> lost [label="Wi-Fi or broker down"];
  lost -> mqtt [label="retry"]; lost -> boot [label="power cut:\\nbroker publishes\\nstatus offline" style=dashed];
}}"""

TOPICS = f"""digraph T {{ rankdir=LR; nodesep=0.12; ranksep=0.45; {NODE}
  p [label="oee" fillcolor="{GREY}"]; u [label="uns" fillcolor="{GREY}"]; a [label="{{area}}\\npackaging" fillcolor="{BLUE}"];
  l [label="{{line}}\\nline-1" fillcolor="{BLUE}"]; c [label="{{cell}}\\ncell-a" fillcolor="{BLUE}"]; m [label="{{machine}}\\nfiller-01" fillcolor="{BLUE}"];
  p -> u -> a -> l -> c -> m;
  s1 [label="start, stop\\nevent, not retained" fillcolor="{ORANGE}"]; s2 [label="output-good, output-defect\\ncounter with total, retained" fillcolor="{GREEN}"];
  s3 [label="state\\nrunning or not, retained" fillcolor="{GREEN}"]; s4 [label="status\\nnode health, retained, last will" fillcolor="{RED}"];
  s5 [label="relay/{{n}}/set  and  relay/{{n}}\\ncommand and acknowledgement" fillcolor="{GREY}"];
  m -> s1; m -> s2; m -> s3; m -> s4; m -> s5;
}}"""


def fast_pieces(path: Path | None = None):
    """Pieces counted against pieces made, as the machine gets faster."""
    rates = [0.2, 0.5, 1, 2, 3, 5, 10]
    made = 60
    res = {}
    for d in ("v0", "v1"):
        res[d] = []
        for r in rates:
            node, rx, clock = bench(d)
            pulses(node, clock, made, 1 / r)
            res[d].append(100 * counted(rx) / made)
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    ax.plot(range(len(rates)), res["v1"], "o-", color=GREEN, label="contract v1 (seq + total)")
    ax.plot(range(len(rates)), res["v0"], "o-", color=RED, label="v0 payload (ts in whole seconds)")
    for i, v in enumerate(res["v0"]):
        ax.annotate(f"{v:.0f} %", (i, v), textcoords="offset points", xytext=(0, -15), ha="center", fontsize=8, color=RED)
    ax.set_xticks(range(len(rates)), [f"{r:g}" for r in rates])
    ax.set_xlabel("pieces per second"); ax.set_ylabel("pieces counted (%)"); ax.set_ylim(0, 110)
    ax.set_title("Above one piece per second, the v0 payload stops telling pieces apart")
    ax.legend(frameon=False, fontsize=8, loc="lower left"); ax.spines[["top", "right"]].set_visible(False); fig.tight_layout()
    if path:
        fig.savefig(path, dpi=130)
    return fig


def outage(path: Path | None = None):
    """Running count around the network outage of one machine: truth, v0 and v1."""
    name = "filler-01"
    machine, _ = MACHINES[name]
    steps, truth = script(name)
    down = next(t for t, a in steps if a == "link_down")
    up = next(t for t, a in steps if a == "link_up")
    lo, hi = down - timedelta(minutes=3), up + timedelta(minutes=3)
    series = {"truth": [], "v0": [], "v1": []}
    benches = {d: bench(d, machine=machine) for d in ("v0", "v1")}
    for node, _, _ in benches.values():
        node.connect(steps[0][0])
    made = 0
    for t, action in steps:
        for node, _, clock in benches.values():
            clock.now = t
            play_step(node, t, action)
        made += action == "good"
        if lo <= t <= hi:
            series["truth"].append((t, made))
            for d, (_, rx, _) in benches.items():
                series[d].append((t, counted(rx, machine)))
    base = series["truth"][0][1]
    fig, ax = plt.subplots(figsize=(8, 3.6))
    mins = lambda t: (t - down).total_seconds() / 60
    ax.axvspan(0, mins(up), color=GREY, alpha=0.15, label="network down")
    ax.plot([mins(t) for t, _ in series["truth"]], [v - base for _, v in series["truth"]], color="black", lw=1, ls=":", label="pieces really made")
    ax.plot([mins(t) for t, _ in series["v1"]], [v - base for _, v in series["v1"]], color=GREEN, label="counted, contract v1")
    ax.plot([mins(t) for t, _ in series["v0"]], [v - base for _, v in series["v0"]], color=RED, label="counted, v0")
    gap = series["truth"][-1][1] - series["v0"][-1][1]
    ax.annotate(f"{gap} pieces never counted", (mins(hi), series["v0"][-1][1] - base), textcoords="offset points",
                xytext=(-8, -22), ha="right", fontsize=9, color=RED)
    ax.set_xlabel("minutes since the network dropped"); ax.set_ylabel("good pieces in the window")
    ax.set_title("A Wi-Fi outage: v1 catches up from `total`, v0 has nothing to catch up from")
    ax.legend(frameon=False, fontsize=8, loc="upper left"); ax.spines[["top", "right"]].set_visible(False); fig.tight_layout()
    if path:
        fig.savefig(path, dpi=130)
    return fig


def oee(path: Path | None = None):
    end = SHIFT_START + timedelta(hours=SHIFT_HOURS)
    res = {name: compute(rx, MACHINES[name][0].base, SHIFT_START, end, MACHINES[name][1])
           for name, (rx, _) in run_shift("v1").items()}
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    keys = [("availability", BLUE), ("performance", ORANGE), ("quality", GREEN), ("oee", "#2c3e50")]
    for j, (k, col) in enumerate(keys):
        vals = [100 * getattr(o, k) for o in res.values()]
        xs = [i + (j - 1.5) * 0.2 for i in range(len(res))]
        ax.bar(xs, vals, 0.2, color=col, label=k if k != "oee" else "OEE")
        for x, v in zip(xs, vals):
            ax.text(x, v + 1, f"{v:.0f}", ha="center", fontsize=8)
    ax.set_xticks(range(len(res)), list(res)); ax.set_ylim(0, 112); ax.set_ylabel("%")
    ax.set_title("The shift, computed from what the collector stored")
    ax.legend(frameon=False, fontsize=8, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    ax.spines[["top", "right"]].set_visible(False); fig.tight_layout()
    if path:
        fig.savefig(path, dpi=130)
    return fig


def waterfall(path: Path | None = None, name: str = "press-02"):
    """From calendar time to valuable time for one machine, with each indicator at its step."""
    from .weeklab import run_week
    t = run_week()[0][name]
    s, h = t.seconds, 3600
    perf_loss = s["run"] - (t.good + t.defect) * t.ideal_cycle_s
    qual_loss = t.defect * t.ideal_cycle_s
    steps = [("calendar", t.calendar, None), ("plant closed", -s["closed"], GREY), ("no shift", -s["unscheduled"], GREY),
             ("planned stops", -s["planned"], ORANGE), ("failures", -s["failure"], RED), ("other unplanned", -s["unplanned"], RED),
             ("speed loss", -perf_loss, BLUE), ("defects", -qual_loss, BLUE), ("valuable", t.valuable, None)]
    marks = {"calendar": "TEEP", "plant closed": "OAE", "no shift": "OOE", "planned stops": "OEE"}
    fig, ax = plt.subplots(figsize=(10, 4))
    level = 0.0
    for i, (label, v, col) in enumerate(steps):
        if col is None:
            ax.bar(i, v / h, color="#2c3e50"); level = v
            ax.text(i, v / h + 2, f"{v / h:.0f} h", ha="center", fontsize=8)
        else:
            ax.bar(i, -v / h, bottom=(level + v) / h, color=col); level += v
            ax.text(i, level / h - 2, f"{v / h:.1f}", ha="center", va="top", fontsize=8, color=col)
        if label in marks:
            k = marks[label]
            base = t.base(k)
            ax.annotate(f"{k} base {base / h:.0f} h\n{k} = {t.indicator(k):.0%}", (i + 0.5, base / h), fontsize=8,
                        xytext=(0, 12), textcoords="offset points", ha="center", color="#2c3e50",
                        arrowprops=dict(arrowstyle="-", color="#999999"))
    ax.set_xticks(range(len(steps)), [x[0] for x in steps], rotation=20, fontsize=8)
    ax.set_ylabel("hours in the week"); ax.set_ylim(0, t.calendar / h * 1.25)
    ax.set_title(f"{name}: where the 168 hours of the week went")
    ax.spines[["top", "right"]].set_visible(False); fig.tight_layout()
    if path:
        fig.savefig(path, dpi=130)
    return fig


def family(path: Path | None = None):
    """TEEP, OAE, OOE and OEE side by side for every machine."""
    from .weeklab import run_week
    measured = run_week()[0]
    keys = [("TEEP", GREY), ("OAE", "#95a5a6"), ("OOE", ORANGE), ("OEE", GREEN)]
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    for j, (k, col) in enumerate(keys):
        xs = [i + (j - 1.5) * 0.2 for i in range(len(measured))]
        vals = [100 * m.indicator(k) for m in measured.values()]
        ax.bar(xs, vals, 0.2, color=col, label=k)
        for x, v in zip(xs, vals):
            ax.text(x, v + 1, f"{v:.0f}", ha="center", fontsize=8)
    ax.set_xticks(range(len(measured)), list(measured)); ax.set_ylim(0, 100); ax.set_ylabel("%")
    ax.set_title("Same pieces, same week, four reference times")
    ax.legend(frameon=False, fontsize=8, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    ax.spines[["top", "right"]].set_visible(False); fig.tight_layout()
    if path:
        fig.savefig(path, dpi=130)
    return fig


if __name__ == "__main__":
    for name, dot in (("architecture", ARCHITECTURE), ("wiring", WIRING), ("lifecycle", LIFECYCLE), ("topics", TOPICS)):
        print(render(dot, name))
    for name, fn in (("fast_pieces", fast_pieces), ("outage", outage), ("oee", oee), ("waterfall", waterfall), ("family", family)):
        fn(IMG / f"{name}.png"); print(IMG / f"{name}.png")
