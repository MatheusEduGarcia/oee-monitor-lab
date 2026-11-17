// =============================================================
// config.example.h - Referência dos valores padrão e opções
// =============================================================
// Este arquivo é apenas documentação. A configuração real é
// feita via interface web (http://192.168.4.1 no modo AP) e
// salva na NVS interna do ESP32.
//
// Para restaurar os defaults: Factory Reset na aba "Visão Geral"
// Para forçar modo AP: segure a Entrada 1 (bt_pins[0]) ao ligar.
// =============================================================

// WiFi (sem padrão - configure via web)
// SSID: ""
// PASS: ""
// Nota: apenas redes 2.4 GHz são suportadas pelo ESP32

// MQTT
// HOST:       192.168.1.100   (broker local padrão)
// PORT:       1883            (sem TLS) | 8883 (com TLS)
// TLS:        0               (0=off | 1=TLS/insecure | 2=TLS+CA no firmware)
// USER:       ""              (vazio = sem autenticação)
// PASS:       ""
// TOPIC:      fabrica/linha1/m1
// CLIENT_ID:  esp32-AABBCC   (gerado pelo MAC)
//
// HiveMQ Cloud (exemplo):
//   HOST: xxxxxxxx.s1.eu.hivemq.cloud
//   PORT: 8883
//   TLS:  1  (sem verificação de CA - funciona para nuvem)
//   USER: <seu-usuario-hivemq>
//   PASS: <sua-senha-hivemq>

// GPIO - Entradas (INPUT_PULLUP · LOW = sinal ativo)
// Papel OEE  → Pino  Label padrão
// Start      → 32    "Start"
// Stop       → 33    "Stop"
// Saida Boa  →  4    "Output"
// Refugo     → 15    "Defect"
// (livre)    → 27    "BT5"
// (livre)    → 14    "BT6"
// (livre)    → 12    "BT7"
// (livre)    → 13    "BT8"
// Pino 0 = desabilitado

// GPIO - Saídas (OUTPUT · HIGH = ligado)
// RL1 → 23   "Start LED"
// RL2 → 16   "Stop LED"
// RL3 → 17   "Output LED"
// RL4 → 19   "Defect LED"
// RL5 → 18   "RL5"
// RL6 →  2   "RL6"
// RL7 → 25   "RL7"
// RL8 → 26   "RL8"

// Tópicos MQTT publicados pelo ESP32:
//   {topic_base}/input/1..8  → {"label":"Start","state":1,"ts":12345}
//   {topic_base}/status      → {"online":true,"ip":"...","rssi":-65}  [retain=true]
//
// Tópicos MQTT subscritos:
//   {topic_base}/relay/1..8  ← {"state":1}  ou payload "1"/"0"/"t"/"f"

// Bibliotecas necessárias (Arduino IDE → Library Manager):
//   PubSubClient (Nick O'Leary) >= 2.8
//   WiFi, WebServer, Preferences, DNSServer, WiFiClientSecure: incluídas no ESP32 core
