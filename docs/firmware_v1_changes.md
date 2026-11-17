# Firmware changes for contract v1

The sketches in [`firmware/`](../firmware) are published as they run today (v0). This page lists what has to change in them to speak [contract v1](protocol.md).

**Status: specification only.** These changes were not compiled or flashed while writing this repository, because no ESP32 toolchain was available. The behaviour they describe is implemented and tested in the virtual node ([`oeelab/node.py`](../oeelab/node.py)), which is what the reference collector was validated against. Treat the snippets below as a guide for the change, and test on a board before trusting them.

## 1. Identity of the boot and of each message

```cpp
static char     bootId[7];        // 6 hex chars, drawn once in setup()
static uint32_t seq = 0;          // +1 on every publish that succeeds

void setup() {
  snprintf(bootId, sizeof(bootId), "%06x", (unsigned)(esp_random() & 0xFFFFFF));
  ...
}
```

`seq` advances only when `mqtt.publish()` returns true, so a hole in `seq` at the receiver always means a message lost in transit.

## 2. Cumulative counters

```cpp
static uint32_t totalGood = 0, pendingGood = 0;   // same pair for defects

void onGoodPiece() {              // called from the debounced edge
  totalGood++;
  pendingGood++;
  flushGood();
}

void flushGood() {
  if (pendingGood == 0 || !mqtt.connected()) return;   // keep counting while offline
  // {"v":1,"seq":..,"boot":"..","ts":"..","value":pendingGood,"total":totalGood}
  if (publishCounter(TOPIC_GOOD, pendingGood, totalGood)) pendingGood = 0;
}
```

Call `flushGood()` and `flushDefect()` right after every successful reconnect. Publish counters with `retain = true`.

Totals live in RAM, so pieces counted between the last delivered message and a power cut are lost. Persisting them is outside v1, see the open points in [protocol.md](protocol.md#9-open-points).

## 3. Time

```cpp
bool clockSynced() { return time(nullptr) > 1600000000; }   // after 2020

// UTC with milliseconds and Z. Returns false when the clock is not usable.
bool isoUtc(char* out, size_t n) {
  if (!clockSynced()) return false;
  struct timeval tv; gettimeofday(&tv, nullptr);
  struct tm t; gmtime_r(&tv.tv_sec, &t);
  size_t k = strftime(out, n, "%Y-%m-%dT%H:%M:%S", &t);
  snprintf(out + k, n - k, ".%03ldZ", tv.tv_usec / 1000);
  return true;
}
```

- Use `gmtime_r`, not `localtime_r`. The offset belongs to whoever displays the data.
- When `isoUtc()` returns false, leave `ts` out of the JSON. Never publish 1970.
- `esp32_oee_webconfig` publishes `millis()` in `ts`. Replace it with the function above.

## 4. Topics and names

| Sketch | Today | v1 |
|---|---|---|
| `esp32_oee_full_signals` | `.../output`, `.../defect` | `.../output-good`, `.../output-defect` |
| `esp32_oee_webconfig` | `{base}/input/{n}` with a label | one configured signal per input: `{base}/start`, `{base}/output-good`... |
| `esp32_cnc_lathe_1button` | `lab/line1/cnc_lathe/button/start`, `/status` | `{prefix}/uns/{area}/{line}/{cell}/{machine}/start`, `/state` |

In the setup portal of `esp32_oee_webconfig`, the free-text label of each input becomes a choice among the v1 signals.

## 5. Birth and last will

```cpp
// last will, registered in connect(): {"v":1,"online":false}, retained, QoS 1
// birth, first publish after connect:
// {"v":1,"online":true,"boot":"a1b2c3","fw":"oee-node 1.0.0","ip":"..","rssi":-61,"uptime_s":12,"clock_synced":true}
```

After the birth, republish `state` (retained) and flush the counters.

## 6. Debounce in `esp32_oee_webconfig`

`handleInputs()` publishes on every level change. The setup page says the debounce is 50 ms, the code has none. Port the `Botao` debounce of `esp32_oee_full_signals` (a level must hold for `DEBOUNCE_MS` before it counts), otherwise a bouncing contact becomes several pieces.

## 7. Buffer size

A v1 counter payload is about 95 bytes and the topic about 55. `PubSubClient` drops messages above its buffer (256 bytes by default, topic included). The current payloads fit; check `mqtt.setBufferSize()` if fields are added.

## Acceptance test on the bench

Point the board at a broker, run `python -m oeelab.check_node <machine topic base>` and operate the inputs. The tool validates every message against the schemas and reports duplicates, gaps and counter recovery, which is the same check the virtual node passes in CI.
