// =============================================================================
// ESP32 - OEE Monitor: Multi-Sinal MQTT (start / stop / peça / refugo / estado)
// Sistema OEE - Integração IoT Completa
// =============================================================================
//
// FUNÇÃO:
//   Publica até 5 sinais distintos no broker MQTT do OEE Monitor, cada um
//   em um tópico separado com seu papel (signal_role) já mapeado no sistema.
//
//   Sinal       Papel no OEE      Disparado por
//   ─────────   ───────────────   ──────────────────────────────────────────
//   START       start             Botão/sensor em PIN_START (borda de descida)
//   STOP        stop              Botão/sensor em PIN_STOP  (borda de descida)
//   PEÇA BOA    output_good       Pulso em PIN_GOOD  (sensor ótico/encoder)
//   REFUGO      output_defect     Botão em PIN_DEFECT (operador)
//   ESTADO      status            Relé/contato em PIN_STATE (nível lógico)
//
// CONFIGURAÇÃO:
//   1. Copie config.example.h → config.h
//   2. Preencha WiFi, broker e descomente o PERFIL da máquina
//   3. Grave no ESP32 - não altere este arquivo
//
// TÓPICOS PUBLICADOS (exemplo: perfil FILLER-01, prefixo oee/):
//   oee/uns/packaging/line-1/cell-a/filler-01/start   → { "ts":"...", "value":1 }
//   oee/uns/packaging/line-1/cell-a/filler-01/stop    → { "ts":"...", "value":1 }
//   oee/uns/packaging/line-1/cell-a/filler-01/output  → { "ts":"...", "value":1 }  (pulso)
//   oee/uns/packaging/line-1/cell-a/filler-01/defect  → { "ts":"...", "value":1 }  (pulso)
//   oee/uns/packaging/line-1/cell-a/filler-01/state   → { "ts":"...", "value":1, "running":true }
//
// PAYLOAD:
//   value = 1  → sinal ativo / ON / pulso recebido
//   value = 0  → sinal inativo / OFF
//   running    → presente apenas no tópico /state
//
// HARDWARE (pinos definidos em config.h):
//   PIN_START  (GPIO32) - botão NO entre GPIO e GND  (pull-up interno)
//   PIN_STOP   (GPIO33) - botão NO entre GPIO e GND  (pull-up interno)
//   PIN_GOOD   (GPIO25) - sensor ótico / encoder     (pull-up interno)
//   PIN_DEFECT (GPIO26) - botão manual de refugo     (pull-up interno)
//   PIN_STATE  (GPIO27) - contato de relé NA         (pull-up interno)
//   PIN_LED    (GPIO2)  - LED onboard de status MQTT
//
// DEPENDÊNCIAS (instale pelo Library Manager do Arduino IDE):
//   - PubSubClient  by Nick O'Leary
//
// =============================================================================

#include <WiFi.h>
#include <PubSubClient.h>
#include <time.h>
#include "config.h"

// =============================================================================
// Tópicos por perfil de máquina
// =============================================================================

#if defined(PERFIL_FILLER_01)
  #define MACHINE_ID       "FILLER-01"
  #define TOPIC_START      "oee/uns/packaging/line-1/cell-a/filler-01/start"
  #define TOPIC_STOP       "oee/uns/packaging/line-1/cell-a/filler-01/stop"
  #define TOPIC_GOOD       "oee/uns/packaging/line-1/cell-a/filler-01/output"
  #define TOPIC_DEFECT     "oee/uns/packaging/line-1/cell-a/filler-01/defect"
  #define TOPIC_STATE      "oee/uns/packaging/line-1/cell-a/filler-01/state"
  #define TEM_START        true
  #define TEM_GOOD         true
  #define TEM_DEFECT       true

#elif defined(PERFIL_PRESS_02)
  #define MACHINE_ID       "PRESS-02"
  #define TOPIC_START      ""    // PRESS_02 não tem sinal de start IoT
  #define TOPIC_STOP       "oee/uns/stamping/line-2/cell-b/press-02/stop"
  #define TOPIC_GOOD       ""    // contagem manual
  #define TOPIC_DEFECT     ""    // refugo manual
  #define TOPIC_STATE      "oee/uns/stamping/line-2/cell-b/press-02/state"
  #define TEM_START        false
  #define TEM_GOOD         false
  #define TEM_DEFECT       false

#else
  #error "Nenhum perfil definido em config.h - descomente PERFIL_FILLER_01 ou PERFIL_PRESS_02"
#endif

// =============================================================================
// Estrutura de debounce
// =============================================================================

struct Botao {
  uint8_t       pin;
  bool          raw_anterior;   // leitura bruta anterior
  bool          confirmado;     // pronto para detectar próxima borda
  unsigned long t_borda;        // millis da última borda detectada
  bool          disparou;       // true por 1 ciclo de loop quando acionado
};

// =============================================================================
// Globais
// =============================================================================

static WiFiClient   wifi_client;
static PubSubClient mqtt(wifi_client);

static Botao btn_start  = { PIN_START,  HIGH, true, 0, false };
static Botao btn_stop   = { PIN_STOP,   HIGH, true, 0, false };
static Botao btn_good   = { PIN_GOOD,   HIGH, true, 0, false };
static Botao btn_defect = { PIN_DEFECT, HIGH, true, 0, false };

static bool          estado_maquina    = false;  // último estado publicado
static bool          sensor_state_ant  = HIGH;   // leitura anterior de PIN_STATE
static unsigned long t_heartbeat       = 0;
static unsigned long t_ultimo_good     = 0;
static unsigned long t_ultimo_defect   = 0;
static unsigned long t_mqtt_retry      = 0;

// =============================================================================
// Utilitários
// =============================================================================

/**
 * Retorna timestamp ISO8601 local (NTP).
 * Retorna "1970-01-01T00:00:00" se NTP ainda não sincronizado.
 */
static String iso8601_agora() {
  struct tm ti;
  if (!getLocalTime(&ti, 100)) return "1970-01-01T00:00:00";
  char buf[24];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", &ti);
  return String(buf);
}

/**
 * Publica payload { "ts":"...", "value": v } no tópico.
 * Para o tópico /state acrescenta "running" e usa retain=true.
 * Retorna true se o publish teve sucesso.
 */
static bool publicar(const char* topico, int value, bool state_msg = false) {
  if (!topico || topico[0] == '\0' || !mqtt.connected()) return false;

  String ts = iso8601_agora();
  char payload[128];

  if (state_msg) {
    snprintf(payload, sizeof(payload),
      "{\"ts\":\"%s\",\"value\":%d,\"running\":%s,\"machine_id\":\"%s\"}",
      ts.c_str(), value,
      (value == 1) ? "true" : "false",
      MACHINE_ID);
  } else {
    snprintf(payload, sizeof(payload),
      "{\"ts\":\"%s\",\"value\":%d,\"machine_id\":\"%s\"}",
      ts.c_str(), value, MACHINE_ID);
  }

  bool retain = state_msg;   // apenas /state usa retain=true
  bool ok = mqtt.publish(topico, payload, retain);

  Serial.printf("  [MQTT] %-5s  %s\n         %s\n",
                ok ? "OK" : "FAIL", topico, payload);
  return ok;
}

// =============================================================================
// Debounce - detecta borda de descida (HIGH→LOW = botão pressionado)
// =============================================================================

static void botao_atualizar(Botao& b) {
  bool leitura = digitalRead(b.pin);
  b.disparou   = false;

  // Detecta início de borda
  if (leitura != b.raw_anterior) {
    b.t_borda      = millis();
    b.raw_anterior = leitura;
  }

  // Confirma após debounce
  if ((millis() - b.t_borda) >= DEBOUNCE_MS) {
    if (leitura == LOW && b.confirmado) {
      // Borda confirmada de HIGH→LOW = pressionado
      b.confirmado = false;
      b.disparou   = true;
    }
    if (leitura == HIGH) {
      b.confirmado = true;   // liberado - pronto para o próximo
    }
  }
}

// =============================================================================
// WiFi
// =============================================================================

static void wifi_conectar() {
  if (WiFi.status() == WL_CONNECTED) return;

  Serial.printf("[WiFi] Conectando a '%s'", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  uint8_t tentativas = 0;
  while (WiFi.status() != WL_CONNECTED && tentativas < 40) {
    delay(500);
    Serial.print(".");
    tentativas++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[WiFi] OK - IP: %s\n", WiFi.localIP().toString().c_str());
    configTime(GMT_OFFSET_S, DST_OFFSET_S, NTP_SERVER);
    Serial.println("[NTP]  Sincronizando...");
    delay(1500);
    Serial.println("[NTP]  OK");
  } else {
    Serial.println("\n[WiFi] FALHA - tentará novamente no próximo ciclo");
  }
}

// =============================================================================
// MQTT - conexão e reconexão
// =============================================================================

static void mqtt_conectar() {
  if (mqtt.connected()) return;

  // Client-ID único: nome da máquina + últimos 4 hex do MAC
  char client_id[48];
  snprintf(client_id, sizeof(client_id), "esp32-%s-%04X",
           MACHINE_ID, (uint16_t)(ESP.getEfuseMac() & 0xFFFF));

  Serial.printf("[MQTT] Conectando a %s:%d (id: %s)...",
                BROKER_HOST, BROKER_PORT, client_id);

  bool ok;
  if (strlen(BROKER_USER) > 0) {
    ok = mqtt.connect(client_id, BROKER_USER, BROKER_PASS);
  } else {
    ok = mqtt.connect(client_id);
  }

  if (ok) {
    Serial.println(" OK");
    // Publica estado atual com retain=true logo após reconectar
    publicar(TOPIC_STATE, estado_maquina ? 1 : 0, /*state_msg=*/true);
  } else {
    Serial.printf(" FALHA (rc=%d)\n", mqtt.state());
  }
}

// =============================================================================
// Setup
// =============================================================================

void setup() {
  Serial.begin(115200);
  delay(200);

  Serial.println();
  Serial.println("=====================================================");
  Serial.printf("  OEE Edge - %s  (multi-sinal)\n", MACHINE_ID);
  Serial.println("  Tópicos:");
#if TEM_START
  Serial.printf("    START  → %s\n", TOPIC_START);
#endif
  Serial.printf("    STOP   → %s\n", TOPIC_STOP);
#if TEM_GOOD
  Serial.printf("    GOOD   → %s\n", TOPIC_GOOD);
#endif
#if TEM_DEFECT
  Serial.printf("    DEFECT → %s\n", TOPIC_DEFECT);
#endif
  Serial.printf("    STATE  → %s\n", TOPIC_STATE);
  Serial.println("=====================================================");

  // Pinos de entrada (pull-up - ativo em LOW)
  pinMode(PIN_START,  INPUT_PULLUP);
  pinMode(PIN_STOP,   INPUT_PULLUP);
  pinMode(PIN_GOOD,   INPUT_PULLUP);
  pinMode(PIN_DEFECT, INPUT_PULLUP);
  pinMode(PIN_STATE,  INPUT_PULLUP);

  // LED de status MQTT
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);

  // Leitura inicial dos botões para evitar disparo no boot
  btn_start.raw_anterior  = digitalRead(PIN_START);
  btn_stop.raw_anterior   = digitalRead(PIN_STOP);
  btn_good.raw_anterior   = digitalRead(PIN_GOOD);
  btn_defect.raw_anterior = digitalRead(PIN_DEFECT);
  sensor_state_ant        = digitalRead(PIN_STATE);

  wifi_conectar();

  mqtt.setServer(BROKER_HOST, BROKER_PORT);
  mqtt.setKeepAlive(60);
  mqtt.setBufferSize(256);

  mqtt_conectar();

  Serial.println("[Sistema] Pronto - aguardando sinais");
}

// =============================================================================
// Loop principal
// =============================================================================

void loop() {
  unsigned long agora = millis();

  // ── 1. Manutenção de conexões ──────────────────────────────────────────────
  if (WiFi.status() != WL_CONNECTED) {
    digitalWrite(PIN_LED, LOW);
    Serial.println("[WiFi] Conexão perdida - reconectando...");
    wifi_conectar();
  }

  if (!mqtt.connected()) {
    digitalWrite(PIN_LED, LOW);
    if ((agora - t_mqtt_retry) > 5000) {
      t_mqtt_retry = agora;
      mqtt_conectar();
    }
    delay(10);
    return;   // sem MQTT, não processa sinais
  }

  mqtt.loop();
  digitalWrite(PIN_LED, HIGH);   // LED aceso = MQTT conectado

  // ── 2. Atualiza debounce de todos os botões ────────────────────────────────
  botao_atualizar(btn_start);
  botao_atualizar(btn_stop);
  botao_atualizar(btn_good);
  botao_atualizar(btn_defect);

  // ── 3. ESTADO - leitura por nível do relé/contato ─────────────────────────
  // PIN_STATE LOW = relé fechado = máquina energizada
  bool sensor_state_now = (digitalRead(PIN_STATE) == LOW);
  if (sensor_state_now != sensor_state_ant) {
    sensor_state_ant = sensor_state_now;
    estado_maquina   = sensor_state_now;
    Serial.printf("[ESTADO] Máquina %s\n", sensor_state_now ? "ON" : "OFF");
    publicar(TOPIC_STATE, sensor_state_now ? 1 : 0, /*state_msg=*/true);
  }

  // ── 4. START ───────────────────────────────────────────────────────────────
#if TEM_START
  if (btn_start.disparou) {
    Serial.println("[START] Início de produção");
    publicar(TOPIC_START, 1);
    // Sincroniza estado geral se ainda não estava ON
    if (!estado_maquina) {
      estado_maquina = true;
      publicar(TOPIC_STATE, 1, /*state_msg=*/true);
    }
  }
#endif

  // ── 5. STOP ────────────────────────────────────────────────────────────────
  if (btn_stop.disparou) {
    Serial.println("[STOP]  Sinal de parada");
    publicar(TOPIC_STOP, 1);
    // Sincroniza estado geral se ainda estava ON
    if (estado_maquina) {
      estado_maquina = false;
      publicar(TOPIC_STATE, 0, /*state_msg=*/true);
    }
  }

  // ── 6. PEÇA BOA - pulso com cooldown anti-ruído ───────────────────────────
#if TEM_GOOD
  if (btn_good.disparou && (agora - t_ultimo_good) >= PULSE_COOLDOWN_MS) {
    t_ultimo_good = agora;
    Serial.println("[GOOD]  Peça boa contada");
    publicar(TOPIC_GOOD, 1);
  }
#endif

  // ── 7. REFUGO - pulso com cooldown ────────────────────────────────────────
#if TEM_DEFECT
  if (btn_defect.disparou && (agora - t_ultimo_defect) >= PULSE_COOLDOWN_MS) {
    t_ultimo_defect = agora;
    Serial.println("[DEFECT] Refugo registrado");
    publicar(TOPIC_DEFECT, 1);
  }
#endif

  // ── 8. HEARTBEAT - republica estado a cada HEARTBEAT_MS ───────────────────
  if ((agora - t_heartbeat) >= HEARTBEAT_MS) {
    t_heartbeat = agora;
    Serial.println("[HB]    Heartbeat de estado");
    publicar(TOPIC_STATE, estado_maquina ? 1 : 0, /*state_msg=*/true);
  }

  delay(5);   // cede CPU por 5 ms
}
