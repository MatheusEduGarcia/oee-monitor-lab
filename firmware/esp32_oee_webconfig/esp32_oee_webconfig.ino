// =============================================================
// esp32_oee_webconfig.ino
// OEE Monitor - Firmware Universal ESP32
// Funciona em qualquer placa ESP32. Configure tudo via browser.
// Suporta broker local (sem TLS) e nuvem (HiveMQ, EMQX, etc.)
// =============================================================
//
// FLUXO DE USO EM CAMPO:
//   1ª vez / sem config salva:
//     → ESP32 cria rede "OEE-Config-XXXX" (sem senha)
//     → Conecte ao "OEE-Config-XXXX"
//     → Abra http://192.168.4.1 no browser
//     → Configure GPIO → MQTT → WiFi
//
//   Após configurar WiFi:
//     → ESP32 sai do AP e entra na sua rede (conexão com 192.168.4.1 cai - normal)
//     → Acesse pelo IP exibido no Serial ou veja no roteador (DHCP)
//
//   Para reconfigurar (forçar modo AP):
//     → Segure a 1ª entrada configurada (bt_pins[0], padrão GPIO 32) ao ligar
//
// BIBLIOTECAS (Arduino IDE → Library Manager):
//   - PubSubClient  (Nick O'Leary) ≥ 2.8
//   WiFi, WebServer, Preferences, DNSServer, WiFiClientSecure: incluídas no ESP32 core
//
// PLACA RECOMENDADA: "ESP32 Dev Module" (compatível com todos os devkits ESP32)
// =============================================================

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <Preferences.h>
#include <PubSubClient.h>

#include "config.h"
#include "webui.h"

// ──────────────────────────────────────────────────────────────
// Objetos globais
// ──────────────────────────────────────────────────────────────
ConfigManager    cfgMgr;
WebServer        server(80);
DNSServer        dnsServer;
WiFiClient       plainClient;
WiFiClientSecure tlsClient;
PubSubClient     mqttClient(plainClient);  // cliente trocado em setupMQTT()

bool apMode = false;

unsigned long lastMqttReconnectMs = 0;
unsigned long lastStatusPublishMs = 0;
bool          lastInputState[NUM_IO];

// ──────────────────────────────────────────────────────────────
// Setup
// ──────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.println("\n[OEE] ── Firmware Universal v2 ──────────────────");

    cfgMgr.load();
    initGPIO();

    // Força modo AP se 1ª entrada estiver pressionada no boot
    bool forceAP = (digitalRead(cfgMgr.config.bt_pins[0]) == LOW);
    if (forceAP) Serial.println("[OEE] Entrada 1 pressionada no boot - modo config forçado");

    bool wifiOk = false;
    if (!forceAP && strlen(cfgMgr.config.wifi_ssid) > 0) {
        wifiOk = connectWiFi(cfgMgr.config.wifi_ssid, cfgMgr.config.wifi_pass, 12000);
    }

    if (wifiOk) {
        apMode = false;
        Serial.printf("[WiFi] Conectado → IP: %s\n", WiFi.localIP().toString().c_str());
        setupMQTT();
    } else {
        apMode = true;
        startAPMode();
    }

    setupWebServer(server, cfgMgr, apMode, mqttClient);
    server.begin();
    Serial.printf("[Web] http://%s\n",
                  apMode ? WiFi.softAPIP().toString().c_str()
                         : WiFi.localIP().toString().c_str());
}

// ──────────────────────────────────────────────────────────────
// Loop
// ──────────────────────────────────────────────────────────────
void loop() {
    if (apMode) dnsServer.processNextRequest();
    server.handleClient();

    if (!apMode) {
        unsigned long now = millis();

        if (!mqttClient.connected() && now - lastMqttReconnectMs > 5000) {
            lastMqttReconnectMs = now;
            reconnectMQTT();
        }
        if (mqttClient.connected()) mqttClient.loop();

        if (now - lastStatusPublishMs > 30000) {
            lastStatusPublishMs = now;
            publishStatus();
        }

        handleInputs();
    }
}

// ──────────────────────────────────────────────────────────────
// GPIO - totalmente baseado na config (sem pinos hardcoded)
// ──────────────────────────────────────────────────────────────
void initGPIO() {
    for (int i = 0; i < NUM_IO; i++) {
        if (cfgMgr.config.bt_pins[i] > 0)
            pinMode(cfgMgr.config.bt_pins[i], INPUT_PULLUP);
        if (cfgMgr.config.rl_pins[i] > 0) {
            pinMode(cfgMgr.config.rl_pins[i], OUTPUT);
            digitalWrite(cfgMgr.config.rl_pins[i], LOW);
        }
        lastInputState[i] = HIGH;
    }
    Serial.println("[GPIO] Pinos inicializados");
}

void handleInputs() {
    for (int i = 0; i < NUM_IO; i++) {
        if (cfgMgr.config.bt_pins[i] == 0) continue;
        bool state = digitalRead(cfgMgr.config.bt_pins[i]);
        if (state != lastInputState[i]) {
            lastInputState[i] = state;
            bool active = (state == LOW);
            Serial.printf("[GPIO] %s → %s\n",
                          cfgMgr.config.bt_labels[i], active ? "ATIVO" : "inativo");

            if (mqttClient.connected()) {
                char topic[96], payload[120];
                snprintf(topic,   sizeof(topic),
                         "%s/input/%d", cfgMgr.config.mqtt_topic_base, i + 1);
                snprintf(payload, sizeof(payload),
                         "{\"label\":\"%s\",\"state\":%d,\"ts\":%lu}",
                         cfgMgr.config.bt_labels[i], active ? 1 : 0, millis());
                mqttClient.publish(topic, payload);
            }
        }
    }
}

// ──────────────────────────────────────────────────────────────
// WiFi
// ──────────────────────────────────────────────────────────────
void startAPMode() {
    uint8_t mac[6];
    WiFi.macAddress(mac);
    char ssid[32];
    snprintf(ssid, sizeof(ssid), "OEE-Config-%02X%02X", mac[4], mac[5]);
    WiFi.mode(WIFI_AP);
    WiFi.softAP(ssid);
    delay(100);
    dnsServer.start(53, "*", WiFi.softAPIP());
    Serial.printf("[AP] Rede: %s  |  http://%s\n", ssid, WiFi.softAPIP().toString().c_str());
}

bool connectWiFi(const char* ssid, const char* pass, unsigned long timeoutMs) {
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid, pass);
    Serial.printf("[WiFi] Conectando a '%s'", ssid);
    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < timeoutMs) {
        delay(400); Serial.print(".");
    }
    Serial.println();
    return WiFi.status() == WL_CONNECTED;
}

// ──────────────────────────────────────────────────────────────
// MQTT - suporte a TLS (0=off, 1=TLS/insecure, 2=TLS+CA)
// ──────────────────────────────────────────────────────────────
void setupMQTT() {
    if (cfgMgr.config.mqtt_tls > 0) {
        if (cfgMgr.config.mqtt_tls == 1) {
            // TLS sem verificação de certificado (HiveMQ Cloud, EMQX Cloud, etc.)
            tlsClient.setInsecure();
        }
        // mqtt_tls == 2: TLS com CA - adicione tlsClient.setCACert(CA_CERT) aqui
        // e declare const char* CA_CERT = "-----BEGIN CERTIFICATE-----\n..." no topo
        mqttClient.setClient(tlsClient);
        Serial.println("[MQTT] Modo TLS ativado");
    } else {
        mqttClient.setClient(plainClient);
        Serial.println("[MQTT] Modo plain (sem TLS)");
    }

    mqttClient.setServer(cfgMgr.config.mqtt_host, cfgMgr.config.mqtt_port);
    mqttClient.setCallback(mqttCallback);
    reconnectMQTT();
}

bool reconnectMQTT() {
    Serial.printf("[MQTT] Conectando a %s:%d (TLS=%d) ...",
                  cfgMgr.config.mqtt_host, cfgMgr.config.mqtt_port, cfgMgr.config.mqtt_tls);

    char willTopic[96];
    snprintf(willTopic, sizeof(willTopic), "%s/status", cfgMgr.config.mqtt_topic_base);

    const char* user = (cfgMgr.config.mqtt_user[0] != '\0') ? cfgMgr.config.mqtt_user : nullptr;
    const char* pass = (cfgMgr.config.mqtt_pass[0] != '\0') ? cfgMgr.config.mqtt_pass : nullptr;

    bool ok = mqttClient.connect(cfgMgr.config.mqtt_client_id,
                                  user, pass,
                                  willTopic, 1, true, "{\"online\":false}");
    if (ok) {
        Serial.println(" OK");
        char subTopic[96];
        snprintf(subTopic, sizeof(subTopic), "%s/relay/+", cfgMgr.config.mqtt_topic_base);
        mqttClient.subscribe(subTopic);
        publishStatus();
    } else {
        Serial.printf(" FALHOU (rc=%d)\n", mqttClient.state());
    }
    return ok;
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
    char* slash = strrchr(topic, '/');
    if (!slash) return;
    int idx = atoi(slash + 1) - 1;
    if (idx < 0 || idx >= NUM_IO) return;
    if (cfgMgr.config.rl_pins[idx] == 0) return;

    int state = (length > 0 && (payload[0] == '1' || payload[0] == 't')) ? HIGH : LOW;
    digitalWrite(cfgMgr.config.rl_pins[idx], state);
    Serial.printf("[MQTT] Relay %d (%s) → %s\n",
                  idx + 1, cfgMgr.config.rl_labels[idx], state ? "ON" : "OFF");
}

void publishStatus() {
    if (!mqttClient.connected()) return;
    char topic[96], payload[160];
    snprintf(topic,   sizeof(topic), "%s/status", cfgMgr.config.mqtt_topic_base);
    snprintf(payload, sizeof(payload),
             "{\"online\":true,\"ip\":\"%s\",\"rssi\":%d,\"client\":\"%s\"}",
             WiFi.localIP().toString().c_str(), WiFi.RSSI(), cfgMgr.config.mqtt_client_id);
    mqttClient.publish(topic, payload, true);
}
