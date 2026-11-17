# Firmware (v0, as it runs today)

Arduino sketches for the ESP32. They are published as they are in use, before [contract v1](../docs/protocol.md). The changes that take them to v1 are listed in [docs/firmware_v1_changes.md](../docs/firmware_v1_changes.md), and until a board is reflashed, [`oeelab/adapter.py`](../oeelab/adapter.py) translates their messages.

| Sketch | For | Configuration |
|---|---|---|
| `esp32_oee_full_signals` | a machine with start, stop, piece sensor, reject button and running contact | compile-time, `config.h` |
| `esp32_oee_webconfig` | configurable inputs and relay outputs, installed without recompiling | setup portal on the board, saved in flash |
| `esp32_cnc_lathe_1button` | the smallest case: one button that toggles running | compile-time, `config.h` |

## Build

1. Arduino IDE or `arduino-cli` with the ESP32 core, and the `PubSubClient` library.
2. In the sketch folder, copy `config.example.h` to `config.h` and fill in Wi-Fi and broker. `config.h` is git-ignored: credentials never go into the repository.
3. Select your ESP32 board and upload.

**Known gap:** `esp32_oee_webconfig` includes a `config.h` that defines its `ConfigManager` class and `NUM_IO`. That file is not in the repository yet (the example header only has notes), so this sketch does not build from a clean clone. The other two do not depend on it.

Comments and serial messages in the sketches are in Portuguese.
