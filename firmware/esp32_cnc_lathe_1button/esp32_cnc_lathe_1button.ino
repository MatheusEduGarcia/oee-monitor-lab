// =============================================================================
// ESP32 - Sinal Digital de Máquina Ligada/Desligada via MQTT
// Sistema OEE - Condition Monitoring
// =============================================================================
//
// FUNÇÃO:
//   Um único botão (ou sensor digital) controla o estado ON/OFF da máquina.
//   O ESP32 publica o estado no broker MQTT toda vez que muda, e também
//   envia um heartbeat periódico para manter o servidor informado.
//
// CONFIGURAÇÃO:
//   Edite config.h antes de gravar. Não altere este arquivo.
//
// TÓPICOS MQTT:
//   PUBLISH  lab/line1/cnc_lathe/button/start  retain=true
//            Payload: { "ts": "2026-03-24T19:00:00", "value": 1.0 }   → ON
//                     { "ts": "2026-03-24T19:00:00", "value": 0.0 }   → OFF
//
//   PUBLISH  lab/line1/cnc_lathe/status        retain=true
//            Payload: { "ts": "...", "running": true,  "machine_id": "CNC-001" }
//                     { "ts": "...", "running": false, "machine_id": "CNC-001" }
//
// HARDWARE (pinos definidos em config.h):
//   PIN_BOTAO  (GPIO32)  - botão NO entre GPIO e GND (usa pull-up interno)
//   PIN_LED_RUN (GPIO2)  - LED indica máquina rodando (LED onboard)
//
// MODOS DE OPERAÇÃO (config.h → MODO_BOTAO):
//   MODO_TOGGLE - cada pressão inverte o estado (padrão para botão físico)
//   MODO_NIVEL  - lê o nível lógico do pino diretamente (reed switch / sensor)
//
// DEPENDÊNCIAS (instale pelo Library Manager do Arduino IDE):
//   - PubSubClient  by Nick O'Leary  (https://github.com/knolleary/pubsubclient)
//
// =============================================================================

#include <WiFi.h>
#include <PubSubClient.h>
#include <time.h>
#include "config.h"

// ── Modos de botão ────────────────────────────────────────────────────────────
#define MODO_TOGGLE 0
#define MODO_NIVEL  1

// ── Tópicos montados a partir de config.h ────────────────────────────────────
#define _TOPIC_BASE   TOPIC_LINE "/" TOPIC_AREA "/" TOPIC_DEVICE
#define TOPIC_BUTTON  _TOPIC_BASE "/button/start"
#define TOPIC_STATUS  _TOPIC_BASE "/status"

// ── Estado global ─────────────────────────────────────────────────────────────
static bool   maquina_rodando  = false;  // estado atual da máquina
static bool   ultimo_btn_raw   = true;   // nível anterior do pino (pull-up → idle=HIGH)
static bool   btn_confirmado   = true;   // estado após debounce
static unsigned long t_borda   = 0;      // timestamp da última borda detectada
static unsigned long t_heartbt = 0;      // timestamp do último heartbeat

// ── Objetos WiFi e MQTT ───────────────────────────────────────────────────────
static WiFiClient   wifi_client;
static PubSubClient mqtt(wifi_client);

// =============================================================================
// Utilitários
// =============================================================================

/**
 * Retorna timestamp ISO8601 UTC do NTP.
 * Exemplo: "2026-03-24T19:45:11"
 */
static String iso8601_agora() {
  struct tm ti;
  if (!getLocalTime(&ti)) {
    // NTP ainda não sincronizado - retorna placeholder
    return "1970-01-01T00:00:00";
  }
  char buf[32];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", &ti);
  return String(buf);
}

/**
 * Monta payload JSON para o tópico /button/start.
 *   { "ts": "...", "value": 1.0, "machine_id": "CNC-001" }
 */
static String payload_button(bool ligada) {
  String ts  = iso8601_agora();
  float  val = ligada ? 1.0f : 0.0f;
  char   buf[128];
  snprintf(buf, sizeof(buf),
    "{\"ts\":\"%s\",\"value\":%.1f,\"machine_id\":\"%s\"}",
    ts.c_str(), val, MACHINE_ID);
  return String(buf);
}

/**
 * Monta payload JSON para o tópico /status.
 *   { "ts": "...", "running": true, "machine_id": "CNC-001" }
 */
static String payload_status(bool ligada) {
  String ts = iso8601_agora();
  const char* running = ligada ? "true" : "false";
  char buf[128];
  snprintf(buf, sizeof(buf),
    "{\"ts\":\"%s\",\"running\":%s,\"machine_id\":\"%s\"}",
    ts.c_str(), running, MACHINE_ID);
  return String(buf);
}

// =============================================================================
// WiFi
// =============================================================================

static void wifi_conectar() {
  if (WiFi.status() == WL_CONNECTED) return;

  Serial.printf("[WiFi] Conectando a '%s'", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  int tentativas = 0;
  while (WiFi.status() != WL_CONNECTED && tentativas < 30) {
    delay(500);
    Serial.print(".");
    tentativas++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[WiFi] OK - IP: %s\n", WiFi.localIP().toString().c_str());
    // Sincroniza NTP após conectar
    configTime(GMT_OFFSET_S, DST_OFFSET_S, NTP_SERVER);
    Serial.println("[NTP] Sincronizando...");
    delay(1500);
    Serial.println("[NTP] OK");
  } else {
    Serial.println("\n[WiFi] FALHA - tentará novamente no próximo ciclo");
  }
}

// =============================================================================
// MQTT
// =============================================================================

/**
 * Publica o estado atual nos dois tópicos com retain=true.
 * Chamado sempre que o estado muda e no heartbeat periódico.
 */
static void mqtt_publicar_estado(bool ligada) {
  if (!mqtt.connected()) return;

  String pb = payload_button(ligada);
  String ps = payload_status(ligada);

  // retain=true → servidor sempre sabe o último estado mesmo após reconexão
  mqtt.publish(TOPIC_BUTTON, pb.c_str(), /*retain=*/true);
  mqtt.publish(TOPIC_STATUS, ps.c_str(), /*retain=*/true);

  Serial.printf("[MQTT] Publicado - %s | running=%s\n",
    TOPIC_BUTTON, ligada ? "true" : "false");
}

/**
 * Conecta (ou reconecta) ao broker MQTT.
 * Bloqueia até conectar ou esgotar 5 tentativas.
 */
static void mqtt_conectar() {
  if (mqtt.connected()) return;

  mqtt.setServer(BROKER_HOST, BROKER_PORT);
  mqtt.setKeepAlive(60);

  // client_id único por device para evitar colisões no broker
  char client_id[48];
  snprintf(client_id, sizeof(client_id), "esp32-%s-%04X",
    MACHINE_ID, (uint16_t)(ESP.getEfuseMac() & 0xFFFF));

  int tentativas = 0;
  while (!mqtt.connected() && tentativas < 5) {
    Serial.printf("[MQTT] Conectando ao broker %s:%d ...", BROKER_HOST, BROKER_PORT);

    bool ok;
    if (strlen(BROKER_USER) > 0) {
      ok = mqtt.connect(client_id, BROKER_USER, BROKER_PASS);
    } else {
      ok = mqtt.connect(client_id);
    }

    if (ok) {
      Serial.println(" OK");
      // Publica estado atual imediatamente após reconexão
      mqtt_publicar_estado(maquina_rodando);
    } else {
      Serial.printf(" FALHA (rc=%d), aguardando 3s...\n", mqtt.state());
      delay(3000);
      tentativas++;
    }
  }
}

// =============================================================================
// Lógica do botão
// =============================================================================

/**
 * Lê o botão com debounce e atualiza o estado da máquina.
 * Suporta MODO_TOGGLE e MODO_NIVEL conforme config.h.
 *
 * Retorna true se o estado da máquina mudou nesta chamada.
 */
static bool botao_processar() {
  bool leitura = digitalRead(PIN_BOTAO);   // HIGH = solto (pull-up), LOW = pressionado

#if MODO_BOTAO == MODO_NIVEL
  // ── Modo nível: pino LOW = máquina ON, HIGH = máquina OFF ────────────────
  bool novo_estado = (leitura == LOW);
  if (novo_estado != maquina_rodando) {
    maquina_rodando = novo_estado;
    return true;
  }
  return false;

#else
  // ── Modo toggle: borda de descida (pressionou) inverte estado ────────────
  unsigned long agora = millis();

  // Detecta borda de descida (solto → pressionado)
  if (leitura == LOW && ultimo_btn_raw == HIGH) {
    t_borda = agora;  // marca início do debounce
  }

  // Confirma borda após período de debounce
  if (leitura == LOW && btn_confirmado == true) {
    if ((agora - t_borda) >= DEBOUNCE_MS) {
      btn_confirmado  = false;     // aguarda soltar para próximo toggle
      maquina_rodando = !maquina_rodando;
      ultimo_btn_raw  = leitura;
      return true;                 // estado mudou
    }
  }

  // Botão solto: permite próximo toggle
  if (leitura == HIGH) {
    btn_confirmado = true;
  }

  ultimo_btn_raw = leitura;
  return false;
#endif
}

// =============================================================================
// Setup
// =============================================================================

void setup() {
  Serial.begin(115200);
  delay(200);

  Serial.println();
  Serial.println("============================================");
  Serial.printf("  OEE Edge - %s\n", MACHINE_ID);
  Serial.printf("  Tópico: %s\n", TOPIC_BUTTON);
  Serial.println("============================================");

  // Configura GPIO
  pinMode(PIN_BOTAO,  INPUT_PULLUP);
  pinMode(PIN_LED_RUN, OUTPUT);
  digitalWrite(PIN_LED_RUN, LOW);  // LED apagado no boot

  // Conecta WiFi e sincroniza NTP
  wifi_conectar();

  // Conecta MQTT
  mqtt_conectar();

  Serial.println("[Sistema] Pronto - aguardando botão");
}

// =============================================================================
// Loop principal
// =============================================================================

void loop() {
  // ── Manutenção de conexões ─────────────────────────────────────────────────
  if (WiFi.status() != WL_CONNECTED) {
    wifi_conectar();
  }
  if (!mqtt.connected()) {
    mqtt_conectar();
  }
  mqtt.loop();  // processa mensagens MQTT pendentes (keep-alive, etc.)

  // ── Lê botão e publica se o estado mudou ──────────────────────────────────
  if (botao_processar()) {
    mqtt_publicar_estado(maquina_rodando);

    // Atualiza LED de status
    digitalWrite(PIN_LED_RUN, maquina_rodando ? HIGH : LOW);

    Serial.printf("[Estado] Máquina %s\n", maquina_rodando ? "LIGADA" : "DESLIGADA");
  }

  // ── Heartbeat periódico ────────────────────────────────────────────────────
  // Republica o estado mesmo sem mudança para manter o servidor informado
  unsigned long agora = millis();
  if ((agora - t_heartbt) >= HEARTBEAT_MS) {
    t_heartbt = agora;
    mqtt_publicar_estado(maquina_rodando);
    Serial.printf("[Heartbeat] running=%s\n", maquina_rodando ? "true" : "false");
  }

  delay(10);  // cede CPU por 10ms
}
