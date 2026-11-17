// =============================================================================
// config.example.h - Template de configuração (SEM credenciais reais)
// =============================================================================
// Copie para config.h e preencha com os dados reais antes de gravar.
// Este arquivo SIM pode ser versionado no Git.
// =============================================================================

#pragma once

// ── WiFi ──────────────────────────────────────────────────────────────────────
#define WIFI_SSID     "NOME_DA_REDE"
#define WIFI_PASS     "SENHA_WIFI"

// ── Broker MQTT ───────────────────────────────────────────────────────────────
#define BROKER_HOST   "192.168.1.XXX"   // IP do servidor OEE
#define BROKER_PORT   1883
#define BROKER_USER   ""                // vazio se sem autenticação
#define BROKER_PASS   ""

// ── NTP ───────────────────────────────────────────────────────────────────────
#define NTP_SERVER    "pool.ntp.org"
#define GMT_OFFSET_S  -10800            // UTC-3 (Brasília)
#define DST_OFFSET_S  0

// ── Perfil da máquina ─────────────────────────────────────────────────────────
// Descomente UMA das linhas abaixo antes de gravar.
//
// #define PERFIL_FILLER_01
// #define PERFIL_PRESS_02

// ── Hardware - GPIO ───────────────────────────────────────────────────────────
#define PIN_START     32   // Início de produção  (pull-up, ativo em LOW)
#define PIN_STOP      33   // Parada              (pull-up, ativo em LOW)
#define PIN_GOOD      25   // Peça boa / pulso    (pull-up, ativo em LOW)
#define PIN_DEFECT    26   // Refugo              (pull-up, ativo em LOW)
#define PIN_STATE     27   // Estado geral        (relé NA - fecha = LOW = ON)
#define PIN_LED       2    // LED de status       (onboard na maioria das placas)

// ── Comportamento ─────────────────────────────────────────────────────────────
#define DEBOUNCE_MS        50
#define PULSE_COOLDOWN_MS  200
#define HEARTBEAT_MS       30000
