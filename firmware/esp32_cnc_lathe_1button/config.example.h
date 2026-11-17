// =============================================================================
// config.example.h - Template de configuração (SEM credenciais reais)
// =============================================================================
// Copie para config.h e preencha com os dados reais antes de gravar.
// Este arquivo SIM pode ser versionado no Git.
// =============================================================================

#pragma once

// ── WiFi ─────────────────────────────────────────────────────────────────────
#define WIFI_SSID     "NOME_DA_REDE"
#define WIFI_PASS     "SENHA_WIFI"

// ── Broker MQTT ──────────────────────────────────────────────────────────────
#define BROKER_HOST   "192.168.1.XXX"   // IP do servidor OEE
#define BROKER_PORT   1883
#define BROKER_USER   ""                // vazio se sem autenticação
#define BROKER_PASS   ""

// ── Identificação da Máquina ──────────────────────────────────────────────────
#define MACHINE_ID    "CNC-001"         // deve bater com o machine_id no OEE
#define TOPIC_LINE    "lab"
#define TOPIC_AREA    "line1"
#define TOPIC_DEVICE  "cnc_lathe"

// ── NTP ───────────────────────────────────────────────────────────────────────
#define NTP_SERVER    "pool.ntp.org"
#define GMT_OFFSET_S  -10800            // UTC-3 (Brasília)
#define DST_OFFSET_S  0

// ── Hardware ──────────────────────────────────────────────────────────────────
#define PIN_BOTAO     32                // GPIO do botão (NO, com pull-up interno)
#define PIN_LED_RUN   2                 // GPIO do LED de status (onboard = 2)

// ── Comportamento ─────────────────────────────────────────────────────────────
#define MODO_BOTAO    MODO_TOGGLE       // ou MODO_NIVEL para sensor digital
#define DEBOUNCE_MS   50
#define HEARTBEAT_MS  30000
