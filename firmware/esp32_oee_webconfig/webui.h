#pragma once
// =============================================================
// webui.h - Servidor HTTP + Interface Wizard de Configuração
// =============================================================
// Endpoints:
//   GET  /                → Página HTML completa (wizard 4 steps)
//   GET  /api/config      → Config atual (JSON, sem senhas)
//   GET  /api/status      → Status WiFi/MQTT/IP
//   POST /api/save/wifi   → Salvar SSID + senha
//   POST /api/connect     → Conectar ao WiFi configurado
//   POST /api/save/mqtt   → Salvar config MQTT (TLS, user, pass)
//   POST /api/test/mqtt   → Testar conexão MQTT (respeita TLS e auth)
//   POST /api/save/gpio   → Salvar mapeamento de pinos
//   GET  /api/gpio/state  → Estado atual de todos os pinos
//   POST /api/gpio/output → Acionar saída (teste)
//   POST /api/reset       → Factory reset + reboot
// =============================================================

#include <WebServer.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include "config.h"

// =============================================================
// Parser JSON minimalista - sem biblioteca externa
// =============================================================
static String _jsonStr(const String& json, const String& key, const String& def = "") {
    String search = "\"" + key + "\":\"";
    int s = json.indexOf(search);
    if (s < 0) return def;
    s += search.length();
    int e = json.indexOf("\"", s);
    return (e < 0) ? def : json.substring(s, e);
}
static int _jsonInt(const String& json, const String& key, int def = 0) {
    String search = "\"" + key + "\":";
    int s = json.indexOf(search);
    if (s < 0) return def;
    s += search.length();
    while (s < (int)json.length() && json[s] == ' ') s++;
    int e = s;
    while (e < (int)json.length() && (isDigit(json[e]) || json[e] == '-')) e++;
    return (e == s) ? def : json.substring(s, e).toInt();
}
static void _jsonIntArr(const String& json, const String& key, uint8_t* arr, int len) {
    String search = "\"" + key + "\":[";
    int s = json.indexOf(search);
    if (s < 0) return;
    s += search.length();
    for (int i = 0; i < len; i++) {
        int comma = json.indexOf(',', s);
        int close = json.indexOf(']', s);
        int e = (comma >= 0 && comma < close) ? comma : close;
        if (e < 0) break;
        arr[i] = (uint8_t)json.substring(s, e).toInt();
        s = e + 1;
    }
}
static void _jsonStrArr(const String& json, const String& key, char dst[][24], int len) {
    String search = "\"" + key + "\":[";
    int s = json.indexOf(search);
    if (s < 0) return;
    s += search.length();
    for (int i = 0; i < len; i++) {
        int q1 = json.indexOf('"', s);
        if (q1 < 0) break; q1++;
        int q2 = json.indexOf('"', q1);
        if (q2 < 0) break;
        strlcpy(dst[i], json.substring(q1, q2).c_str(), 24);
        s = q2 + 1;
    }
}

static WebServer*     _srv    = nullptr;
static ConfigManager* _cfg    = nullptr;
static bool*          _apMode = nullptr;
static PubSubClient*  _mqtt   = nullptr;

// =============================================================
// HTML da interface - Wizard 4 passos
// =============================================================
static const char WEB_HTML[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OEE · Config ESP32</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0f172a;color:#e2e8f0;font-family:system-ui,-apple-system,sans-serif;min-height:100vh;padding-bottom:4rem}
header{background:#1e293b;border-bottom:1px solid #334155;padding:.8rem 1.25rem;display:flex;align-items:center;gap:.6rem;position:sticky;top:0;z-index:20}
header h1{font-size:.95rem;font-weight:700;color:#f8fafc;flex:1}
.badge{display:inline-block;padding:.15rem .5rem;border-radius:4px;font-size:.7rem;font-weight:600;line-height:1.4}
.bg{background:#14532d;color:#86efac}.br{background:#7f1d1d;color:#fca5a5}
.by{background:#713f12;color:#fde68a}.bk{background:#1e293b;color:#94a3b8;border:1px solid #334155}
/* ── Stepper ── */
.stepper{display:flex;background:#1e293b;border-bottom:1px solid #334155;overflow-x:auto;padding:.2rem .5rem 0}
.step{display:flex;align-items:center;gap:.4rem;padding:.55rem .9rem;font-size:.78rem;cursor:pointer;
      border-bottom:2px solid transparent;color:#64748b;white-space:nowrap;margin-bottom:-1px;transition:all .15s}
.step .num{width:18px;height:18px;border-radius:50%;background:#334155;color:#94a3b8;
           display:flex;align-items:center;justify-content:center;font-size:.65rem;font-weight:700;flex-shrink:0}
.step.done .num{background:#059669;color:#fff}
.step.active{color:#10b981;border-bottom-color:#10b981;font-weight:600}
.step.active .num{background:#10b981;color:#fff}
/* ── Layout ── */
.page{display:none;padding:1.1rem;max-width:740px;margin:0 auto}
.page.active{display:block}
.card{background:#1e293b;border:1px solid #334155;border-radius:8px;padding:1.1rem;margin-bottom:.9rem}
.card h2{font-size:.85rem;font-weight:600;color:#f1f5f9;margin-bottom:.9rem;padding-bottom:.5rem;
         border-bottom:1px solid #334155;display:flex;align-items:center;gap:.45rem}
.warn{background:rgba(245,158,11,.1);border:1px solid rgba(245,158,11,.35);border-radius:8px;
      padding:.8rem 1rem;font-size:.82rem;color:#fde68a;line-height:1.6;margin-bottom:.9rem}
.info-box{background:rgba(16,185,129,.08);border:1px solid rgba(16,185,129,.25);border-radius:8px;
          padding:.8rem 1rem;font-size:.82rem;color:#6ee7b7;line-height:1.6;margin-bottom:.9rem}
label{display:block;font-size:.77rem;color:#94a3b8;margin:.65rem 0 .2rem;font-weight:500}
label:first-of-type{margin-top:0}
input[type=text],input[type=password],input[type=number],select{
  width:100%;background:#0f172a;border:1px solid #334155;color:#e2e8f0;
  padding:.48rem .7rem;border-radius:6px;font-size:.85rem;outline:none;transition:border-color .15s}
input:focus,select:focus{border-color:#10b981;box-shadow:0 0 0 2px rgba(16,185,129,.12)}
.btn{display:inline-flex;align-items:center;gap:.3rem;padding:.45rem .85rem;border-radius:6px;
     font-size:.8rem;font-weight:600;cursor:pointer;border:none;transition:all .15s;user-select:none}
.g{background:#059669;color:#fff}.g:hover{background:#047857}
.b{background:#2563eb;color:#fff}.b:hover{background:#1d4ed8}
.r{background:#dc2626;color:#fff}.r:hover{background:#b91c1c}
.dk{background:#334155;color:#e2e8f0}.dk:hover{background:#475569}
.btn:disabled{opacity:.45;cursor:not-allowed}
.row{display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.9rem}
table{width:100%;border-collapse:collapse;font-size:.8rem}
th{text-align:left;padding:.4rem .4rem;color:#64748b;font-weight:600;font-size:.73rem;
   text-transform:uppercase;letter-spacing:.03em;border-bottom:1px solid #334155}
td{padding:.3rem .4rem;border-bottom:1px solid #1e293b;vertical-align:middle}
tr:last-child td{border-bottom:none}
td input[type=number]{width:62px;padding:.25rem .3rem;font-size:.77rem}
td input[type=text]{padding:.25rem .4rem;font-size:.77rem}
td select{padding:.25rem .3rem;font-size:.77rem}
.son{color:#34d399;font-weight:700}.soff{color:#475569}
.mono{font-family:ui-monospace,monospace;font-size:.78rem;color:#94a3b8;
      background:#0f172a;padding:.65rem;border-radius:6px;line-height:1.9}
#status-bar{position:fixed;bottom:0;left:0;right:0;background:#1e293b;border-top:1px solid #334155;
            padding:.35rem 1.25rem;font-size:.73rem;color:#64748b;display:flex;gap:1.2rem;flex-wrap:wrap;z-index:10}
#status-bar b{color:#94a3b8}
.toast{position:fixed;top:3.8rem;right:.9rem;padding:.6rem .95rem;border-radius:6px;font-size:.8rem;
       font-weight:600;z-index:999;opacity:0;transition:opacity .25s;pointer-events:none;max-width:290px}
.toast.show{opacity:1}
.tok{background:#064e3b;color:#6ee7b7;border:1px solid #059669}
.terr{background:#7f1d1d;color:#fca5a5;border:1px solid #dc2626}
.hint{font-size:.73rem;color:#64748b;margin-top:.3rem}
.sep{height:1px;background:#334155;margin:.65rem 0}
.nav-row{display:flex;gap:.5rem;margin-top:1.1rem;justify-content:space-between;align-items:center}
.step-lbl{font-size:.75rem;color:#64748b}
/* status cards */
.sc-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:.65rem;margin-bottom:.9rem}
.sc{background:#0f172a;border:1px solid #334155;border-radius:7px;padding:.7rem .9rem}
.sc .sc-title{font-size:.73rem;color:#64748b;margin-bottom:.35rem}
.sc .sc-val{font-size:.95rem;font-weight:700;color:#f1f5f9}
.sc .sc-sub{font-size:.7rem;color:#64748b;margin-top:.2rem}
/* FAQ accordion */
.faq-item{border-bottom:1px solid #1e293b;cursor:pointer}
.faq-item:last-child{border-bottom:none}
.faq-q{padding:.6rem .2rem;color:#cbd5e1;display:flex;justify-content:space-between;align-items:center;user-select:none}
.faq-q::after{content:'▸';color:#475569;font-size:.75rem;flex-shrink:0;transition:transform .2s}
.faq-item.open .faq-q::after{transform:rotate(90deg)}
.faq-a{display:none;padding:.1rem .2rem .8rem;line-height:1.8;color:#94a3b8}
.faq-item.open .faq-a{display:block}
</style>
</head>
<body>

<header>
  <h1>⚙ OEE Monitor · Config ESP32</h1>
  <span class="badge bk" id="hdr-mode">...</span>
  <span class="badge bk" id="hdr-ip">...</span>
</header>

<!-- ═══ Stepper ═══════════════════════════════════════════════ -->
<div class="stepper">
  <div class="step active" id="st0" onclick="goStep(0)">
    <span class="num" id="sn0">1</span> Visão Geral
  </div>
  <div class="step" id="st1" onclick="goStep(1)">
    <span class="num" id="sn1">2</span> GPIO
  </div>
  <div class="step" id="st2" onclick="goStep(2)">
    <span class="num" id="sn2">3</span> WiFi
  </div>
  <div class="step" id="st3" onclick="goStep(3)">
    <span class="num" id="sn3">4</span> MQTT
  </div>
  <div class="step" id="st4" onclick="goStep(4)">
    <span class="num" id="sn4">5</span> Teste
  </div>
</div>

<!-- ═══ PASSO 0 - Visão Geral / Documentação ══════════════════ -->
<div class="page active" id="page-0">

  <!-- Status ao vivo -->
  <div class="sc-grid" id="overview-cards">
    <div class="sc">
      <div class="sc-title">Modo</div>
      <div class="sc-val" id="ov-mode">-</div>
      <div class="sc-sub" id="ov-ip">-</div>
    </div>
    <div class="sc">
      <div class="sc-title">WiFi</div>
      <div class="sc-val" id="ov-wifi">-</div>
      <div class="sc-sub" id="ov-rssi">-</div>
    </div>
    <div class="sc">
      <div class="sc-title">MQTT</div>
      <div class="sc-val" id="ov-mqtt">-</div>
      <div class="sc-sub" id="ov-broker">-</div>
    </div>
    <div class="sc">
      <div class="sc-title">MAC / ID</div>
      <div class="sc-val" style="font-size:.75rem;font-family:monospace" id="ov-mac">-</div>
      <div class="sc-sub" id="ov-client">-</div>
    </div>
  </div>

  <!-- Sobre o dispositivo -->
  <div class="card">
    <h2>📌 Sobre este dispositivo</h2>
    <div style="font-size:.82rem;line-height:1.85;color:#94a3b8">
      Coletador de sinais industriais baseado em <b style="color:#e2e8f0">ESP32</b>.
      Lê até 8 entradas digitais (botões, sensores, reed switches) e aciona até 8 saídas
      (relés, LEDs), publicando cada evento via <b style="color:#e2e8f0">MQTT</b> para o
      servidor OEE em tempo real.<br><br>
      <div style="display:flex;align-items:center;gap:.3rem;flex-wrap:wrap;font-size:.8rem">
        <span style="background:#1e3a5f;color:#93c5fd;padding:.2rem .55rem;border-radius:4px">Máquina</span>
        <span style="color:#475569">→</span>
        <span style="background:#1e3a2f;color:#86efac;padding:.2rem .55rem;border-radius:4px">GPIO</span>
        <span style="color:#475569">→</span>
        <span style="background:#2d1f4e;color:#c4b5fd;padding:.2rem .55rem;border-radius:4px">ESP32</span>
        <span style="color:#475569">→</span>
        <span style="background:#1e3a5f;color:#67e8f9;padding:.2rem .55rem;border-radius:4px">MQTT</span>
        <span style="color:#475569">→</span>
        <span style="background:#3b1f1f;color:#fca5a5;padding:.2rem .55rem;border-radius:4px">OEE Server</span>
        <span style="color:#475569">→</span>
        <span style="background:#2d3000;color:#fde68a;padding:.2rem .55rem;border-radius:4px">Dashboard</span>
      </div>
    </div>
  </div>

  <!-- Fluxo de configuração -->
  <div class="card">
    <h2>🗺 Fluxo de configuração - ordem obrigatória</h2>
    <div style="font-size:.82rem;color:#94a3b8">
      <div style="display:grid;gap:.5rem;margin-top:.3rem">
        <div style="display:flex;gap:.75rem;align-items:flex-start;padding:.5rem .6rem;background:#0f172a;border-radius:6px;border-left:3px solid #10b981">
          <span style="color:#10b981;font-weight:800;font-size:.9rem;min-width:18px">2</span>
          <div><b style="color:#e2e8f0">GPIO</b> - Defina os pinos de cada entrada/saída e o papel OEE (Start, Stop, Saída Boa, Refugo, Estado). Pino 0 = desabilitado.</div>
        </div>
        <div style="display:flex;gap:.75rem;align-items:flex-start;padding:.5rem .6rem;background:#0f172a;border-radius:6px;border-left:3px solid #3b82f6">
          <span style="color:#3b82f6;font-weight:800;font-size:.9rem;min-width:18px">3</span>
          <div><b style="color:#e2e8f0">MQTT</b> - Informe o broker (local ou nuvem), porta, credenciais e tópico base. <b style="color:#fde68a">Salve sem testar</b> - o teste só funciona após o WiFi estar conectado.</div>
        </div>
        <div style="display:flex;gap:.75rem;align-items:flex-start;padding:.5rem .6rem;background:#0f172a;border-radius:6px;border-left:3px solid #f59e0b">
          <span style="color:#f59e0b;font-weight:800;font-size:.9rem;min-width:18px">4</span>
          <div><b style="color:#e2e8f0">WiFi</b> - Informe SSID e senha, clique Conectar. <b style="color:#fde68a">A página ficará inacessível</b> enquanto o ESP32 troca de rede - isso é normal. Use o comando <code>arp -a</code> para encontrar o novo IP.</div>
        </div>
        <div style="display:flex;gap:.75rem;align-items:flex-start;padding:.5rem .6rem;background:#0f172a;border-radius:6px;border-left:3px solid #a855f7">
          <span style="color:#a855f7;font-weight:800;font-size:.9rem;min-width:18px">3★</span>
          <div><b style="color:#e2e8f0">MQTT (voltar)</b> - Pelo novo IP, teste a conexão com o broker. Agora o ESP32 está na rede e consegue alcançar o broker.</div>
        </div>
        <div style="display:flex;gap:.75rem;align-items:flex-start;padding:.5rem .6rem;background:#0f172a;border-radius:6px;border-left:3px solid #06b6d4">
          <span style="color:#06b6d4;font-weight:800;font-size:.9rem;min-width:18px">5</span>
          <div><b style="color:#e2e8f0">Teste</b> - Acione as entradas físicas e verifique o estado ao vivo. Comande as saídas manualmente para validar relés/LEDs.</div>
        </div>
      </div>
    </div>
  </div>

  <!-- Diagnóstico / Solução de problemas -->
  <div class="card">
    <h2>🔧 Diagnóstico de falhas - o que fazer</h2>
    <div style="font-size:.81rem;color:#94a3b8">

      <div class="faq-item" onclick="toggleFaq(this)">
        <div class="faq-q">⚠ WiFi não conecta - timeout ou "verifique SSID e senha"</div>
        <div class="faq-a">
          <b style="color:#e2e8f0">Verificar:</b><br>
          • SSID digitado corretamente? (maiúsculas/minúsculas importam)<br>
          • A rede é <b>2.4 GHz</b>? ESP32 <u>não suporta</u> 5 GHz<br>
          • Sinal fraco? Aproxime o ESP32 do roteador durante a configuração<br>
          • Roteador com MAC filter? Adicione o MAC <code id="diag-mac1">-</code><br><br>
          <b style="color:#e2e8f0">Ação:</b> Corrija o SSID/senha → clique Salvar → clique Conectar novamente.
        </div>
      </div>

      <div class="faq-item" onclick="toggleFaq(this)">
        <div class="faq-q">⚠ Teste MQTT falha - "conexão recusada"</div>
        <div class="faq-a">
          <b style="color:#e2e8f0">Verificar em sequência:</b><br>
          1. ESP32 está na rede WiFi? (Modo deve ser <b>Station</b>, não AP)<br>
          2. Broker Mosquitto rodando? No PC do servidor execute:<br>
          <code style="display:block;margin:.3rem 0;padding:.3rem .5rem;background:#0f172a;border-radius:4px;color:#38bdf8">
            sc query mosquitto &nbsp; ou &nbsp; netstat -ano | findstr :1883
          </code>
          3. Host configurado é o IP correto do broker? (não use <code>localhost</code>)<br>
          4. Porta certa? Sem TLS = <b>1883</b> · Com TLS = <b>8883</b><br>
          5. Firewall do PC bloqueia a porta? Libere a porta 1883 no Windows Defender<br><br>
          <b style="color:#e2e8f0">Teste rápido no PC do broker:</b><br>
          <code style="display:block;margin:.3rem 0;padding:.3rem .5rem;background:#0f172a;border-radius:4px;color:#38bdf8">
            mosquitto_pub -h 127.0.0.1 -p 1883 -t oee/teste -m "ping"
          </code>
        </div>
      </div>

      <div class="faq-item" onclick="toggleFaq(this)">
        <div class="faq-q">⚠ Página sumiu após clicar Conectar - como achar o ESP32?</div>
        <div class="faq-a">
          <b style="color:#e2e8f0">Isso é comportamento esperado.</b> O ESP32 saiu da rede AP e entrou na sua rede WiFi.<br><br>
          <b style="color:#e2e8f0">Passo a passo:</b><br>
          1. Reconecte seu computador/celular à rede WiFi normal<br>
          2. Execute no terminal do computador:<br>
          <code id="diag-arp" style="display:block;margin:.3rem 0;padding:.3rem .5rem;background:#0f172a;border-radius:4px;color:#38bdf8">
            arp -a | findstr XX-XX-XX
          </code>
          3. O IP retornado é o endereço do ESP32 - acesse <code>http://[IP]</code><br>
          4. Se não encontrar: verifique tabela DHCP do roteador (procure por "esp32")
        </div>
      </div>

      <div class="faq-item" onclick="toggleFaq(this)">
        <div class="faq-q">⚠ Sinal não aparece no OEE Dashboard</div>
        <div class="faq-a">
          <b style="color:#e2e8f0">Verificar:</b><br>
          1. MQTT conectado? (status bar inferior deve mostrar "Conectado")<br>
          2. Tópico base configurado aqui coincide com o <b>vínculo de tópico</b> criado no OEE Server?<br>
          3. Entrada está sendo detectada? Acesse <b>Passo 5 (Teste)</b> e pressione a entrada - o estado deve mudar<br>
          4. Verifique com MQTT Explorer no PC: conecte ao broker e monitore os tópicos em tempo real<br>
          5. Sinal muito rápido? O debounce do firmware é 50ms - o pulso deve durar ao menos 50ms
        </div>
      </div>

      <div class="faq-item" onclick="toggleFaq(this)">
        <div class="faq-q">⚠ Relé / LED não aciona</div>
        <div class="faq-a">
          <b style="color:#e2e8f0">Verificar:</b><br>
          1. Pino da saída está configurado? (pino 0 = desabilitado)<br>
          2. Teste no <b>Passo 5</b>: clique "Ligar" no botão manual da saída - o relé deve ativar<br>
          3. Se o teste manual funcionar mas o MQTT não: verifique o tópico de comando:<br>
          <code style="display:block;margin:.3rem 0;padding:.3rem .5rem;background:#0f172a;border-radius:4px;color:#38bdf8">
            {tópico-base}/relay/N ← {"state":1}
          </code>
          4. Payload incorreto? Aceita também: <code>"1"</code>, <code>"t"</code> (ativar) · <code>"0"</code>, <code>"f"</code> (desativar)
        </div>
      </div>

      <div class="faq-item" onclick="toggleFaq(this)">
        <div class="faq-q">⚠ ESP32 não inicia em modo AP - não encontro a rede OEE-Config</div>
        <div class="faq-a">
          <b style="color:#e2e8f0">Para forçar modo de configuração:</b><br>
          1. Desligue o ESP32<br>
          2. Segure pressionada a <b>Entrada 1</b> (pino <b id="diag-bt0">?</b>)<br>
          3. Ligue o ESP32 com o botão pressionado<br>
          4. Solte após 2 segundos - a rede <code>OEE-Config-XXXX</code> irá aparecer<br><br>
          <b style="color:#e2e8f0">Factory Reset completo (apaga tudo):</b><br>
          Use o botão abaixo - o dispositivo reinicia sem nenhuma configuração salva.
        </div>
      </div>

    </div>
  </div>

  <!-- Referência técnica -->
  <div class="card">
    <h2>🔩 Referência técnica</h2>
    <table style="font-size:.8rem">
      <tr><td style="color:#64748b;padding:.3rem .4rem;width:140px">MAC Address</td><td><code id="ref-mac">-</code></td></tr>
      <tr><td style="color:#64748b;padding:.3rem .4rem">Client ID MQTT</td><td><code id="ref-client">-</code></td></tr>
      <tr><td style="color:#64748b;padding:.3rem .4rem">Força modo AP</td><td>Segurar <b>Entrada 1</b> (pino <b id="bt0-pin-info">?</b>) ao ligar</td></tr>
      <tr><td style="color:#64748b;padding:.3rem .4rem">AP padrão</td><td><code>OEE-Config-XXXX</code> · IP <code>192.168.4.1</code> · Sem senha</td></tr>
      <tr><td style="color:#64748b;padding:.3rem .4rem">Tópicos pub</td><td><code>{base}/input/1..8</code> · <code>{base}/status</code></td></tr>
      <tr><td style="color:#64748b;padding:.3rem .4rem">Tópicos sub</td><td><code>{base}/relay/1..8</code></td></tr>
      <tr><td style="color:#64748b;padding:.3rem .4rem">Debounce</td><td>50 ms · Heartbeat 30 s</td></tr>
      <tr><td style="color:#64748b;padding:.3rem .4rem">Entradas</td><td>INPUT_PULLUP · LOW = ativo</td></tr>
    </table>
    <div class="sep"></div>
    <button class="btn r" onclick="factoryReset()" style="font-size:.78rem">⚠ Factory Reset - apaga toda configuração</button>
  </div>

  <div class="nav-row">
    <span class="step-lbl">Documentação · Passo 1 de 5</span>
    <button class="btn g" onclick="goStep(1)">Iniciar configuração - GPIO →</button>
  </div>
</div>

<!-- ═══ PASSO 1 - GPIO + Monitor de Sinais ═══════════════════════ -->
<div class="page" id="page-1">
  <div class="info-box">
    <b>Fluxo do técnico:</b> conecte os sensores/botões → configure os pinos →
    use o <b>Monitor ao Vivo</b> abaixo para confirmar o sinal antes de prosseguir.
    Pino <b>0</b> = desabilitado.
  </div>

  <div class="card">
    <h2>⬇ Entradas - Sensores / Botões (INPUT_PULLUP · LOW = ativo)</h2>
    <table>
      <thead><tr><th>#</th><th>Pino GPIO</th><th>Papel OEE</th><th>Label (tópico)</th></tr></thead>
      <tbody id="bt-table"></tbody>
    </table>
  </div>

  <div class="card">
    <h2>⬆ Saídas - Relés / LEDs (OUTPUT)</h2>
    <table>
      <thead><tr><th>#</th><th>Pino GPIO</th><th>Papel OEE</th><th>Label</th></tr></thead>
      <tbody id="rl-table"></tbody>
    </table>
  </div>

  <div class="row">
    <button class="btn g" onclick="saveGpio()">💾 Salvar GPIO</button>
    <button class="btn dk" onclick="reloadGpio()">🔄 Recarregar</button>
  </div>
  <p class="hint" style="margin-top:.5rem">Após salvar, os pinos são reinicializados sem reiniciar o ESP32.</p>

  <!-- ── Monitor ao Vivo ── -->
  <div class="card" style="margin-top:1rem">
    <h2>🔴 Monitor ao Vivo - teste de entradas e saídas</h2>
    <p style="font-size:.78rem;color:#64748b;margin-bottom:.9rem">
      Acione os sensores fisicamente e veja o estado mudar. Use para confirmar fiação
      e ajustar os pinos antes de configurar WiFi e MQTT.
    </p>

    <div style="font-size:.73rem;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.45rem">Entradas</div>
    <div id="gmon-inputs" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:.45rem;margin-bottom:.9rem"></div>

    <div style="font-size:.73rem;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.45rem">Saídas</div>
    <div id="gmon-outputs" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:.45rem;margin-bottom:.9rem"></div>

    <div style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap">
      <button class="btn g" id="gmon-start-btn" onclick="gmonStart()" style="font-size:.78rem;padding:.35rem .7rem">▶ Iniciar Monitor</button>
      <button class="btn dk" id="gmon-stop-btn" onclick="gmonStop()" style="font-size:.78rem;padding:.35rem .7rem" disabled>■ Parar</button>
      <button class="btn dk" onclick="gmonResetCounters()" style="font-size:.78rem;padding:.35rem .7rem">↺ Zerar</button>
      <span id="gmon-hz" style="font-size:.71rem;color:#475569"></span>
      <span id="gmon-status" style="font-size:.72rem;color:#64748b;margin-left:.3rem"></span>
    </div>
  </div>

  <div class="nav-row">
    <button class="btn dk" onclick="goStep(0)">← Voltar</button>
    <button class="btn g" onclick="goStep(2)">Conectar WiFi →</button>
  </div>
</div>

<!-- ═══ PASSO 2 - WiFi ══════════════════════════════════════════ -->
<div class="page" id="page-2">

  <div id="wifi-connected-overlay" style="display:none;position:fixed;inset:0;background:#0f172a;z-index:100;
       flex-direction:column;align-items:center;justify-content:center;padding:1.5rem;text-align:center">
    <div style="font-size:2.5rem;margin-bottom:.75rem">✅</div>
    <h2 style="color:#34d399;font-size:1.1rem;margin-bottom:.5rem">ESP32 conectou ao WiFi!</h2>
    <p style="color:#94a3b8;font-size:.85rem;max-width:420px;line-height:1.7;margin-bottom:1rem">
      A rede <b style="color:#fde68a">OEE-Config-XXXX</b> foi encerrada - isso é normal.
    </p>

    <!-- Bloco IP automático (visível quando IP foi retornado) -->
    <div id="ov-ip-block" style="display:none;background:#064e3b;border:1px solid #059669;border-radius:10px;
         padding:1rem 1.5rem;max-width:460px;width:100%;margin-bottom:1rem">
      <p style="color:#6ee7b7;font-size:.82rem;margin-bottom:.5rem">Novo endereço do painel de configuração:</p>
      <a id="ov-ip-link" href="#" target="_blank"
         style="font-size:1.35rem;font-weight:700;color:#34d399;word-break:break-all;text-decoration:none">
        http://...
      </a>
      <p style="color:#94a3b8;font-size:.78rem;margin-top:.6rem">
        Redirecionando em <b id="ov-countdown" style="color:#fde68a">10</b>s…
        <button onclick="_ovCancelRedirect()" style="background:none;border:none;color:#64748b;
                font-size:.75rem;cursor:pointer;text-decoration:underline;margin-left:.4rem">cancelar</button>
      </p>
    </div>

    <!-- Bloco fallback manual (visível quando IP não foi retornado) -->
    <div id="ov-manual-block" style="display:none;background:#1e293b;border:1px solid #334155;border-radius:10px;
         padding:1rem 1.25rem;text-align:left;max-width:460px;width:100%;font-size:.82rem;line-height:2;color:#e2e8f0">
      <b style="color:#10b981">1.</b> Reconecte este dispositivo à sua rede WiFi<br>
      <b style="color:#10b981">2.</b> Descubra o IP do ESP32 no terminal:<br>
      <code id="arp-cmd" style="background:#0f172a;padding:.3rem .6rem;border-radius:4px;font-size:.8rem;
            color:#38bdf8;display:block;margin:.3rem 0">arp -a | findstr XX-XX-XX</code>
      <b style="color:#10b981">3.</b> Acesse: <code style="color:#38bdf8">http://[IP encontrado]</code><br>
      <b style="color:#10b981">4.</b> Continue no <b>Passo 4 - MQTT</b>
    </div>
  </div>

  <div class="warn">
    ⚠ <b>Importante:</b> ao clicar <b>Conectar</b>, o ESP32 entra na sua rede e
    a rede <b>OEE-Config-XXXX desaparece</b>. Esta tela mostrará o que fazer logo em seguida.
  </div>

  <div class="card">
    <h2>📶 Credenciais WiFi</h2>
    <label>SSID (nome da rede)</label>
    <input type="text" id="wifi-ssid" placeholder="MinhaRede2.4GHz" autocomplete="off">
    <label>Senha</label>
    <input type="password" id="wifi-pass" placeholder="••••••••" autocomplete="new-password">
    <p class="hint">Use redes 2.4 GHz - ESP32 não suporta 5 GHz.</p>
    <div class="row">
      <button class="btn g" onclick="saveWifi()">💾 Salvar</button>
      <button class="btn b" onclick="connectWifi()" id="btn-connect">🔗 Conectar →</button>
    </div>
  </div>

  <div class="card">
    <h2>📊 Status atual</h2>
    <div id="wifi-status-detail" style="font-size:.85rem;line-height:2">Carregando...</div>
  </div>

  <div class="card">
    <h2>🔍 Como achar o ESP32 depois de conectar</h2>
    <div style="font-size:.82rem;color:#94a3b8;line-height:1.9">
      Execute no terminal do computador:<br>
      <code id="arp-cmd2" style="display:block;background:#0f172a;padding:.4rem .7rem;border-radius:5px;
            color:#38bdf8;margin:.35rem 0">arp -a | findstr XX-XX-XX</code>
      <b style="color:#e2e8f0">MAC do ESP32:</b> <code id="esp-mac-display">carregando...</code>
    </div>
  </div>

  <div class="nav-row">
    <button class="btn dk" onclick="goStep(1)">← Voltar</button>
    <button class="btn g" onclick="goStep(3)">Configurar MQTT →</button>
  </div>
</div>

<!-- ═══ PASSO 3 - MQTT ══════════════════════════════════════════ -->
<div class="page" id="page-3">
  <div class="card">
    <h2>📡 Broker MQTT</h2>

    <label>Modo de conexão</label>
    <select id="mqtt-tls" onchange="onTlsChange()">
      <option value="0">🔓 Sem TLS - broker local (Mosquitto / EMQX on-prem)</option>
      <option value="1">🔒 TLS sem verificação - nuvem (HiveMQ Cloud, EMQX Cloud…)</option>
      <option value="2">🔐 TLS + CA embutida - produção (AWS IoT, broker corporativo)</option>
    </select>
    <p class="hint" id="tls-hint">Broker na rede local, sem criptografia. Porta padrão: 1883.</p>

    <label>Host / IP do broker</label>
    <input type="text" id="mqtt-host" placeholder="192.168.1.100  ou  xxxx.s1.eu.hivemq.cloud">

    <label>Porta</label>
    <input type="number" id="mqtt-port" value="1883" min="1" max="65535">

    <div class="sep"></div>
    <label>Usuário <span style="color:#475569;font-weight:400">(deixe vazio se broker não exige)</span></label>
    <input type="text" id="mqtt-user" placeholder="usuario" autocomplete="off">

    <label>Senha <span style="color:#475569;font-weight:400">(campo vazio = mantém senha salva)</span></label>
    <input type="password" id="mqtt-pass" placeholder="••••••••" autocomplete="new-password">

    <div class="sep"></div>
    <label>Tópico Base</label>
    <input type="text" id="mqtt-topic" placeholder="fabrica/linha1/maquina1" oninput="updateTopicsPreview()">
    <p class="hint">Ex: <code>oee/uns/di/linha1/celula/maquina01</code> - sem espaços ou acentos.</p>

    <label>Client ID</label>
    <input type="text" id="mqtt-client" placeholder="esp32-oee-001">

    <div id="mqtt-ap-warn" class="warn" style="display:none;margin-top:.8rem">
      ⚠ <b>Teste indisponível em modo AP.</b> O ESP32 não tem rota para o broker.
      <b>Salve</b> → conecte WiFi (Passo 3) → acesse pelo novo IP → volte aqui para testar.
    </div>

    <div class="row">
      <button class="btn g" onclick="saveMqtt()">💾 Salvar configuração</button>
      <button class="btn b" id="btn-mqtt-test" onclick="testMqtt()">🔗 Testar Conexão</button>
    </div>
  </div>

  <div class="card" id="cloud-hint-card" style="display:none">
    <h2>☁ Referência rápida - brokers em nuvem</h2>
    <div style="font-size:.79rem;line-height:1.9;color:#94a3b8">
      <b style="color:#e2e8f0">HiveMQ Cloud (gratuito):</b><br>
      Host: <code>xxxxxxxx.s1.eu.hivemq.cloud</code> · Porta: <code>8883</code><br>
      <div class="sep"></div>
      <b style="color:#e2e8f0">EMQX Cloud:</b><br>
      Host: <code>xxxxxxxx.emqxsl.com</code> · Porta: <code>8883</code><br>
      <div class="sep"></div>
      <b style="color:#e2e8f0">AWS IoT Core:</b><br>
      TLS+CA · Requer certificado de dispositivo no firmware.
    </div>
  </div>

  <div class="card">
    <h2>📋 Tópicos que serão publicados</h2>
    <div class="mono" id="mqtt-topics-preview">-</div>
  </div>

  <div class="nav-row">
    <button class="btn dk" onclick="goStep(2)">← Voltar</button>
    <button class="btn g" onclick="goStep(4)">Ver Teste Final →</button>
  </div>
</div>

<!-- ═══ PASSO 4 - Teste ════════════════════════════════════════ -->
<div class="page" id="page-4">
  <div class="info-box" id="test-status-box">
    Verificando status do sistema...
  </div>

  <div class="card">
    <h2>⬇ Entradas - Estado Atual</h2>
    <table>
      <thead><tr><th>#</th><th>Label</th><th>Pino</th><th>Estado</th></tr></thead>
      <tbody id="test-inputs"><tr><td colspan="4" style="color:#64748b">Abrindo aba de teste...</td></tr></tbody>
    </table>
  </div>
  <div class="card">
    <h2>⬆ Saídas - Controle Manual</h2>
    <table>
      <thead><tr><th>#</th><th>Label</th><th>Pino</th><th>Estado</th><th>Ação</th></tr></thead>
      <tbody id="test-outputs"></tbody>
    </table>
    <p class="hint" style="margin-top:.5rem">Controle manual para validação. Não interfere com lógica MQTT.</p>
  </div>
  <div style="font-size:.72rem;color:#64748b;margin-top:.4rem">↺ Atualização automática a cada 600ms</div>

  <div class="nav-row">
    <button class="btn dk" onclick="goStep(3)">← Voltar</button>
    <span class="step-lbl">Configuração concluída ✓</span>
  </div>
</div>

<!-- ═══ Status bar ═════════════════════════════════════════════ -->
<div id="status-bar">
  <span>Modo: <b id="sb-mode">-</b></span>
  <span>IP: <b id="sb-ip">-</b></span>
  <span>WiFi: <b id="sb-wifi">-</b></span>
  <span>MQTT: <b id="sb-mqtt">-</b></span>
</div>
<div class="toast" id="toast"></div>

<script>
let cfg = {};
let testTimer = null;
let stepDone = [false,false,false,false,false];

// ── Roles OEE ─────────────────────────────────────────────────
const IN_ROLES  = ['--','Start','Stop','Saida Boa','Refugo','Estado','BT Livre'];
const OUT_ROLES = ['--','LED Start','LED Stop','LED Saida','LED Refugo','LED Estado','Rele Livre'];

// ── Stepper ───────────────────────────────────────────────────
function goStep(n) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.step').forEach(s => s.classList.remove('active'));
  document.getElementById('page-' + n).classList.add('active');
  document.getElementById('st' + n).classList.add('active');
  if (n === 4) { startTestPolling(); } else { stopTestPolling(); }
  if (n === 2) updateTopicsPreview();
}

function markDone(n) {
  stepDone[n] = true;
  document.getElementById('sn' + n).textContent = '✓';
  document.getElementById('st' + n).classList.add('done');
}

// ── Toast ─────────────────────────────────────────────────────
function toast(msg, ok) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast show ' + (ok === false ? 'terr' : 'tok');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 3500);
}

// ── API ───────────────────────────────────────────────────────
async function api(path, method, body) {
  const opts = { method: method || 'GET', headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  return r.json();
}

// ── Load config ───────────────────────────────────────────────
async function loadConfig() {
  try {
    cfg = await api('/api/config');
    document.getElementById('wifi-ssid').value   = cfg.wifi_ssid       || '';
    document.getElementById('mqtt-host').value   = cfg.mqtt_host       || '';
    document.getElementById('mqtt-port').value   = cfg.mqtt_port       || 1883;
    document.getElementById('mqtt-tls').value    = cfg.mqtt_tls        || 0;
    document.getElementById('mqtt-user').value   = cfg.mqtt_user       || '';
    document.getElementById('mqtt-topic').value  = cfg.mqtt_topic_base || '';
    document.getElementById('mqtt-client').value = cfg.mqtt_client_id  || '';
    const bt0 = cfg.bt_pins?.[0] ?? '?';
    document.getElementById('bt0-pin-info').textContent = bt0;
    onTlsChange();
    buildGpioTables();
    updateTopicsPreview();
  } catch(e) { toast('Erro ao carregar config', false); }
}

// ── Status ────────────────────────────────────────────────────
let _isAP = true;
async function loadStatus() {
  try {
    const s = await api('/api/status');
    _isAP = s.mode === 'ap';
    const isAP = _isAP;
    const wOk  = s.wifi === 'Conectado';
    const mOk  = s.mqtt === 'Conectado';

    document.getElementById('hdr-mode').textContent = isAP ? 'AP Config' : 'STA';
    document.getElementById('hdr-mode').className   = 'badge ' + (isAP ? 'by' : 'bg');
    document.getElementById('hdr-ip').textContent   = s.ip || '-';

    document.getElementById('ov-mode').textContent  = isAP ? 'Access Point' : 'Station';
    document.getElementById('ov-ip').textContent    = 'IP: ' + (s.ip || '-');
    document.getElementById('ov-wifi').textContent  = s.wifi || '-';
    document.getElementById('ov-rssi').textContent  = s.rssi ? s.rssi + ' dBm' : '';
    document.getElementById('ov-mqtt').textContent  = s.mqtt || '-';
    document.getElementById('ov-broker').textContent = cfg.mqtt_host || '';
    document.getElementById('ov-wifi').style.color  = wOk ? '#34d399' : '#f87171';
    document.getElementById('ov-mqtt').style.color  = mOk ? '#34d399' : '#f87171';

    // Atualiza MAC e IDs em todas as ocorrências
    if (s.mac) {
      const macShort = s.mac.split('-').slice(3).join('-');
      const arpCmd = 'arp -a | findstr ' + macShort;
      ['arp-cmd','arp-cmd2','diag-arp'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = arpCmd;
      });
      ['esp-mac-display','ref-mac','ov-mac','diag-mac1'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = s.mac;
      });
    }
    const clientEl = document.getElementById('ref-client');
    if (clientEl && cfg.mqtt_client_id) clientEl.textContent = cfg.mqtt_client_id;
    const ovClientEl = document.getElementById('ov-client');
    if (ovClientEl && cfg.mqtt_client_id) ovClientEl.textContent = cfg.mqtt_client_id;

    // Pino BT0 no diagnóstico
    const diagBt0 = document.getElementById('diag-bt0');
    if (diagBt0 && cfg.bt_pins) diagBt0.textContent = cfg.bt_pins[0] ?? '?';

    // Aviso MQTT em modo AP
    const apWarn = document.getElementById('mqtt-ap-warn');
    const testBtn = document.getElementById('btn-mqtt-test');
    if (apWarn) apWarn.style.display = isAP ? 'block' : 'none';
    if (testBtn) testBtn.disabled = isAP;

    document.getElementById('sb-mode').textContent = isAP ? 'Access Point' : 'Station';
    document.getElementById('sb-ip').textContent   = s.ip   || '-';
    document.getElementById('sb-wifi').textContent = s.wifi || '-';
    document.getElementById('sb-mqtt').textContent = s.mqtt || '-';

    // WiFi detail card
    const wd = document.getElementById('wifi-status-detail');
    wd.innerHTML =
      `Modo: <b>${isAP ? 'Access Point (config)' : 'Station (normal)'}</b><br>` +
      `IP: <b>${s.ip || '-'}</b><br>` +
      `WiFi: <span class="badge ${wOk?'bg':'br'}">${s.wifi}</span>${s.rssi?' &nbsp; Sinal: <b>'+s.rssi+' dBm</b>':''}<br>` +
      `MQTT: <span class="badge ${mOk?'bg':'br'}">${s.mqtt}</span>`;

    // Test status box
    const tb = document.getElementById('test-status-box');
    if (wOk && mOk) {
      tb.className = 'info-box';
      tb.innerHTML = '✅ Sistema operacional - WiFi e MQTT conectados. Sinais sendo publicados.';
    } else {
      tb.className = 'warn';
      tb.innerHTML = (!wOk ? '⚠ WiFi desconectado. ' : '') + (!mOk ? '⚠ MQTT desconectado.' : '');
    }
  } catch(e) {}
}

// ── WiFi ──────────────────────────────────────────────────────
async function saveWifi() {
  const ssid = document.getElementById('wifi-ssid').value.trim();
  const pass = document.getElementById('wifi-pass').value;
  if (!ssid) { toast('SSID não pode ser vazio', false); return; }
  const r = await api('/api/save/wifi', 'POST', { ssid, pass });
  if (r.ok) { toast('✓ WiFi salvo! Clique em Conectar.'); markDone(3); }
  else toast('Erro ao salvar WiFi', false);
}

async function connectWifi() {
  const btn = document.getElementById('btn-connect');
  btn.disabled = true; btn.textContent = '⏳ Conectando (até 15s)...';
  try {
    const r = await api('/api/connect', 'POST');
    if (r.ok) {
      // Mostrar overlay com instrucoes - a pagina vai cair logo
      _showConnectedOverlay(r.ip);
    } else {
      toast('✗ Falha: ' + (r.error || 'timeout - verifique SSID e senha'), false);
      btn.disabled = false; btn.textContent = '🔗 Conectar →';
    }
  } catch(e) {
    // Esperado: conexão caiu quando ESP32 entrou na rede - mostrar overlay
    _showConnectedOverlay(null);
  }
}

let _ovRedirectTimer = null;
let _ovRedirectCancelled = false;

function _showConnectedOverlay(ip) {
  const ov = document.getElementById('wifi-connected-overlay');
  if (!ov) return;
  ov.style.display = 'flex';

  if (ip) {
    const url = 'http://' + ip;
    const linkEl = document.getElementById('ov-ip-link');
    if (linkEl) { linkEl.href = url; linkEl.textContent = url; }
    document.getElementById('ov-ip-block').style.display = 'block';
    document.getElementById('ov-manual-block').style.display = 'none';
    _ovStartCountdown(url, 10);
  } else {
    document.getElementById('ov-ip-block').style.display = 'none';
    document.getElementById('ov-manual-block').style.display = 'block';
  }
}

function _ovStartCountdown(url, secs) {
  _ovRedirectCancelled = false;
  const cdEl = document.getElementById('ov-countdown');
  let remaining = secs;
  _ovRedirectTimer = setInterval(() => {
    if (_ovRedirectCancelled) { clearInterval(_ovRedirectTimer); return; }
    remaining--;
    if (cdEl) cdEl.textContent = remaining;
    if (remaining <= 0) {
      clearInterval(_ovRedirectTimer);
      window.location.href = url;
    }
  }, 1000);
}

function _ovCancelRedirect() {
  _ovRedirectCancelled = true;
  if (_ovRedirectTimer) clearInterval(_ovRedirectTimer);
  const p = document.getElementById('ov-countdown')?.parentElement;
  if (p) p.innerHTML = '<span style="color:#94a3b8;font-size:.78rem">Redirecionamento cancelado. Clique no link acima quando estiver na rede.</span>';
}

// ── MQTT ──────────────────────────────────────────────────────
function onTlsChange() {
  const tls = parseInt(document.getElementById('mqtt-tls')?.value || 0);
  const hints = [
    'Broker na rede local, sem criptografia. Porta padrão: 1883.',
    'TLS sem verificação de certificado. Ideal para HiveMQ Cloud, EMQX Cloud. Porta: 8883.',
    'TLS com CA embutida no firmware. Edite setupMQTT() no .ino antes de compilar.'
  ];
  const el = document.getElementById('tls-hint');
  if (el) el.textContent = hints[tls] || hints[0];

  const cloud = document.getElementById('cloud-hint-card');
  if (cloud) cloud.style.display = tls > 0 ? 'block' : 'none';

  // Sugerir porta
  const portEl = document.getElementById('mqtt-port');
  if (portEl && !portEl.dataset.manual) {
    portEl.value = tls > 0 ? 8883 : 1883;
  }
}

async function saveMqtt() {
  const host     = document.getElementById('mqtt-host').value.trim();
  const port     = parseInt(document.getElementById('mqtt-port').value) || 1883;
  const tls      = parseInt(document.getElementById('mqtt-tls').value)  || 0;
  const user     = document.getElementById('mqtt-user').value.trim();
  const pass     = document.getElementById('mqtt-pass').value;
  const topic    = document.getElementById('mqtt-topic').value.trim();
  const clientId = document.getElementById('mqtt-client').value.trim();
  if (!host) { toast('Host não pode ser vazio', false); return; }
  const r = await api('/api/save/mqtt', 'POST',
    { host, port, tls, user, pass, topic, client_id: clientId });
  if (r.ok) { toast('✓ MQTT salvo!'); cfg.mqtt_topic_base = topic; markDone(2); }
  else toast('Erro ao salvar MQTT', false);
}

async function testMqtt() {
  if (_isAP) {
    toast('⚠ Conecte ao WiFi primeiro (Passo 4), depois teste o MQTT pelo novo IP.', false);
    return;
  }
  toast('Testando conexão MQTT...');
  const r = await api('/api/test/mqtt', 'POST');
  if (r.ok) {
    toast('✓ MQTT conectado com sucesso!');
    markDone(2);
  } else {
    toast('✗ ' + (r.error || 'sem resposta - verifique host, porta e credenciais'), false);
  }
}

function updateTopicsPreview() {
  const base = document.getElementById('mqtt-topic')?.value || cfg.mqtt_topic_base || '<base>';
  const el = document.getElementById('mqtt-topics-preview');
  if (!el) return;
  el.innerHTML =
    `<b style="color:#f1f5f9">Publicados pelo ESP32:</b><br>` +
    `${base}/input/1..8  →  {"label":"Start","state":1,"ts":12345}<br>` +
    `${base}/status      →  {"online":true,"ip":"...","rssi":-65}<br><br>` +
    `<b style="color:#f1f5f9">Assina (comandos para relés):</b><br>` +
    `${base}/relay/1..8  ←  {"state":1}`;
}

// ── GPIO tables ───────────────────────────────────────────────
function roleOpts(roles, sel) {
  return roles.map((r,i) =>
    `<option value="${r}" ${r === sel ? 'selected' : ''}>${r}</option>`).join('');
}

function buildGpioTables() {
  const bt = document.getElementById('bt-table');
  const rl = document.getElementById('rl-table');
  bt.innerHTML = ''; rl.innerHTML = '';
  for (let i = 0; i < 8; i++) {
    const bLbl = cfg.bt_labels?.[i] ?? ('BT'+(i+1));
    const rLbl = cfg.rl_labels?.[i] ?? ('RL'+(i+1));
    bt.innerHTML += `<tr>
      <td>${i+1}</td>
      <td><input type="number" id="bt-pin-${i}" value="${cfg.bt_pins?.[i]??0}" min="0" max="39"></td>
      <td><select id="bt-role-${i}" onchange="applyRole('bt',${i})">${roleOpts(IN_ROLES,bLbl)}</select></td>
      <td><input type="text" id="bt-lbl-${i}" value="${bLbl}"></td></tr>`;
    rl.innerHTML += `<tr>
      <td>${i+1}</td>
      <td><input type="number" id="rl-pin-${i}" value="${cfg.rl_pins?.[i]??0}" min="0" max="39"></td>
      <td><select id="rl-role-${i}" onchange="applyRole('rl',${i})">${roleOpts(OUT_ROLES,rLbl)}</select></td>
      <td><input type="text" id="rl-lbl-${i}" value="${rLbl}"></td></tr>`;
  }
}

function applyRole(kind, i) {
  const role = document.getElementById(kind+'-role-'+i).value;
  if (role !== '--') document.getElementById(kind+'-lbl-'+i).value = role;
}

async function saveGpio() {
  const payload = { bt_pins:[], rl_pins:[], bt_labels:[], rl_labels:[] };
  for (let i = 0; i < 8; i++) {
    payload.bt_pins.push(parseInt(document.getElementById('bt-pin-'+i).value) || 0);
    payload.rl_pins.push(parseInt(document.getElementById('rl-pin-'+i).value) || 0);
    payload.bt_labels.push(document.getElementById('bt-lbl-'+i).value || 'BT'+(i+1));
    payload.rl_labels.push(document.getElementById('rl-lbl-'+i).value || 'RL'+(i+1));
  }
  const r = await api('/api/save/gpio', 'POST', payload);
  if (r.ok) {
    cfg = { ...cfg, ...payload };
    toast('✓ GPIO salvo e pinos reinicializados!');
    markDone(1);
    // atualiza pino da entrada 1 no passo 0
    document.getElementById('bt0-pin-info').textContent = payload.bt_pins[0];
  } else toast('Erro ao salvar GPIO', false);
}

async function reloadGpio() { await loadConfig(); toast('Config recarregada'); }

// ── Test tab ──────────────────────────────────────────────────
function startTestPolling() { updateTest(); testTimer = setInterval(updateTest, 600); }
function stopTestPolling()  { if (testTimer) { clearInterval(testTimer); testTimer = null; } }

async function updateTest() {
  let s;
  try { s = await api('/api/gpio/state'); } catch(e) { return; }
  document.getElementById('test-inputs').innerHTML =
    s.inputs.map((inp,i) => `<tr>
      <td>${i+1}</td><td>${inp.label}</td><td><code>${inp.pin}</code></td>
      <td class="${inp.state?'son':'soff'}">${inp.state?'● ATIVO':'○ inativo'}</td>
    </tr>`).join('');
  document.getElementById('test-outputs').innerHTML =
    s.outputs.map((out,i) => `<tr>
      <td>${i+1}</td><td>${out.label}</td><td><code>${out.pin}</code></td>
      <td class="${out.state?'son':'soff'}">${out.state?'● ON':'○ OFF'}</td>
      <td><button class="btn ${out.state?'r':'g'}" style="padding:.25rem .55rem;font-size:.75rem"
          onclick="toggleOutput(${i},${out.state?0:1})">${out.state?'Desligar':'Ligar'}</button></td>
    </tr>`).join('');
}

async function toggleOutput(idx, state) { await api('/api/gpio/output','POST',{index:idx,state}); }

// ── Factory reset ─────────────────────────────────────────────
async function factoryReset() {
  if (!confirm('Apaga TODA a configuração e reinicia o ESP32. Confirmar?')) return;
  toast('Resetando...');
  await api('/api/reset','POST');
  toast('✓ Reset executado. ESP32 reiniciando...');
}

// ── FAQ accordion ─────────────────────────────────────────────
function toggleFaq(el) { el.classList.toggle('open'); }

// ── Init ──────────────────────────────────────────────────────
loadConfig();
loadStatus();
setInterval(loadStatus, 5000);
</script>
</body>
</html>
)rawliteral";

// =============================================================
// Handlers HTTP
// =============================================================

void _handleRoot()      { _srv->send_P(200, "text/html", WEB_HTML); }
void _handleGetConfig() { _srv->send(200, "application/json", _cfg->toJson()); }

void _handleGetStatus() {
    String mode = *_apMode ? "ap" : "sta";
    String ip   = *_apMode ? WiFi.softAPIP().toString() : WiFi.localIP().toString();
    String wifi = (WiFi.status() == WL_CONNECTED) ? "Conectado" : "Desconectado";
    String mqtt = _mqtt->connected()               ? "Conectado" : "Desconectado";
    uint8_t mac[6]; WiFi.macAddress(mac);
    char macStr[18];
    snprintf(macStr, sizeof(macStr), "%02x-%02x-%02x-%02x-%02x-%02x",
             mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);
    String j = "{\"mode\":\"" + mode + "\",\"ip\":\"" + ip + "\","
               "\"wifi\":\"" + wifi + "\",\"mqtt\":\"" + mqtt + "\","
               "\"rssi\":" + String(WiFi.RSSI()) + ","
               "\"mac\":\"" + String(macStr) + "\"}";
    _srv->send(200, "application/json", j);
}

void _handleSaveWifi() {
    if (!_srv->hasArg("plain")) { _srv->send(400,"application/json","{\"ok\":false}"); return; }
    const String& body = _srv->arg("plain");
    _cfg->saveWiFi(_jsonStr(body,"ssid").c_str(), _jsonStr(body,"pass").c_str());
    _srv->send(200, "application/json", "{\"ok\":true}");
}

void _handleConnect() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(_cfg->config.wifi_ssid, _cfg->config.wifi_pass);
    unsigned long t = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - t < 15000) delay(200);
    if (WiFi.status() == WL_CONNECTED) {
        *_apMode = false;
        _srv->send(200, "application/json",
                   "{\"ok\":true,\"ip\":\"" + WiFi.localIP().toString() + "\"}");
    } else {
        _srv->send(200, "application/json",
                   "{\"ok\":false,\"error\":\"Timeout - verifique SSID e senha\"}");
    }
}

void _handleSaveMqtt() {
    if (!_srv->hasArg("plain")) { _srv->send(400,"application/json","{\"ok\":false}"); return; }
    const String& body = _srv->arg("plain");
    String   host     = _jsonStr(body, "host");
    uint16_t port     = (uint16_t)_jsonInt(body, "port", 1883);
    uint8_t  tls      = (uint8_t) _jsonInt(body, "tls",  0);
    String   user     = _jsonStr(body, "user");
    String   pass     = _jsonStr(body, "pass");
    String   topic    = _jsonStr(body, "topic");
    String   clientId = _jsonStr(body, "client_id");
    _cfg->saveMQTT(host.c_str(), port, tls,
                   user.c_str(), pass.c_str(),
                   topic.c_str(), clientId.c_str());
    _srv->send(200, "application/json", "{\"ok\":true}");
}

void _handleTestMqtt() {
    // Em modo AP o ESP32 não tem rota para a rede local - teste impossível
    if (*_apMode) {
        _srv->send(200, "application/json",
            "{\"ok\":false,\"ap_mode\":true,"
            "\"error\":\"ESP32 em modo AP - sem rota para o broker. Conecte ao WiFi (Passo 4) e teste pelo novo IP.\"}");
        return;
    }
    bool ok = false;
    String errMsg = "Conexao recusada - verifique host, porta e credenciais";

    if (_cfg->config.mqtt_tls > 0) {
        WiFiClientSecure tc;
        tc.setInsecure();
        PubSubClient probe(tc);
        probe.setServer(_cfg->config.mqtt_host, _cfg->config.mqtt_port);
        const char* u = _cfg->config.mqtt_user[0] ? _cfg->config.mqtt_user : nullptr;
        const char* p = _cfg->config.mqtt_pass[0] ? _cfg->config.mqtt_pass : nullptr;
        ok = probe.connect("oee-test-tls", u, p);
        if (ok) probe.disconnect();
    } else {
        WiFiClient tc;
        PubSubClient probe(tc);
        probe.setServer(_cfg->config.mqtt_host, _cfg->config.mqtt_port);
        const char* u = _cfg->config.mqtt_user[0] ? _cfg->config.mqtt_user : nullptr;
        const char* p = _cfg->config.mqtt_pass[0] ? _cfg->config.mqtt_pass : nullptr;
        ok = probe.connect("oee-test-plain", u, p);
        if (ok) probe.disconnect();
    }
    _srv->send(200, "application/json",
               ok ? "{\"ok\":true}"
                  : "{\"ok\":false,\"error\":\"" + errMsg + "\"}");
}

void _handleSaveGpio() {
    if (!_srv->hasArg("plain")) { _srv->send(400,"application/json","{\"ok\":false}"); return; }
    const String& body = _srv->arg("plain");

    uint8_t btPins[NUM_IO], rlPins[NUM_IO];
    char    btLabels[NUM_IO][24], rlLabels[NUM_IO][24];
    for (int i = 0; i < NUM_IO; i++) {
        btPins[i] = _cfg->config.bt_pins[i];
        rlPins[i] = _cfg->config.rl_pins[i];
        strlcpy(btLabels[i], _cfg->config.bt_labels[i], 24);
        strlcpy(rlLabels[i], _cfg->config.rl_labels[i], 24);
    }
    _jsonIntArr(body, "bt_pins",  btPins,  NUM_IO);
    _jsonIntArr(body, "rl_pins",  rlPins,  NUM_IO);
    _jsonStrArr(body, "bt_labels", btLabels, NUM_IO);
    _jsonStrArr(body, "rl_labels", rlLabels, NUM_IO);
    _cfg->saveGPIO(btPins, rlPins, btLabels, rlLabels);

    for (int i = 0; i < NUM_IO; i++) {
        if (_cfg->config.bt_pins[i] > 0) pinMode(_cfg->config.bt_pins[i], INPUT_PULLUP);
        if (_cfg->config.rl_pins[i] > 0) {
            pinMode(_cfg->config.rl_pins[i], OUTPUT);
            digitalWrite(_cfg->config.rl_pins[i], LOW);
        }
    }
    _srv->send(200, "application/json", "{\"ok\":true}");
}

void _handleGpioState() {
    String j = "{\"inputs\":[";
    for (int i = 0; i < NUM_IO; i++) {
        uint8_t pin = _cfg->config.bt_pins[i];
        int state = (pin > 0 && digitalRead(pin) == LOW) ? 1 : 0;
        j += "{\"pin\":" + String(pin) + ",\"label\":\"" +
             String(_cfg->config.bt_labels[i]) + "\",\"state\":" + String(state) + "}";
        if (i < NUM_IO-1) j += ",";
    }
    j += "],\"outputs\":[";
    for (int i = 0; i < NUM_IO; i++) {
        uint8_t pin = _cfg->config.rl_pins[i];
        int state = (pin > 0) ? digitalRead(pin) : 0;
        j += "{\"pin\":" + String(pin) + ",\"label\":\"" +
             String(_cfg->config.rl_labels[i]) + "\",\"state\":" + String(state) + "}";
        if (i < NUM_IO-1) j += ",";
    }
    j += "]}";
    _srv->send(200, "application/json", j);
}

void _handleGpioOutput() {
    if (!_srv->hasArg("plain")) { _srv->send(400,"application/json","{\"ok\":false}"); return; }
    const String& body = _srv->arg("plain");
    int idx   = _jsonInt(body, "index", -1);
    int state = _jsonInt(body, "state",  0);
    if (idx < 0 || idx >= NUM_IO || _cfg->config.rl_pins[idx] == 0) {
        _srv->send(400,"application/json","{\"ok\":false,\"error\":\"index invalido\"}"); return;
    }
    digitalWrite(_cfg->config.rl_pins[idx], state ? HIGH : LOW);
    _srv->send(200, "application/json", "{\"ok\":true}");
}

void _handleReset() {
    _cfg->factoryReset();
    _srv->send(200, "application/json", "{\"ok\":true}");
    delay(500);
    ESP.restart();
}

void _handleNotFound() {
    _srv->sendHeader("Location", "http://192.168.4.1", true);
    _srv->send(302, "text/plain", "");
}

// =============================================================
void setupWebServer(WebServer& srv, ConfigManager& cfg, bool& apMode, PubSubClient& mqttClient) {
    _srv    = &srv;
    _cfg    = &cfg;
    _apMode = &apMode;
    _mqtt   = &mqttClient;

    srv.on("/",                HTTP_GET,  _handleRoot);
    srv.on("/api/config",      HTTP_GET,  _handleGetConfig);
    srv.on("/api/status",      HTTP_GET,  _handleGetStatus);
    srv.on("/api/save/wifi",   HTTP_POST, _handleSaveWifi);
    srv.on("/api/connect",     HTTP_POST, _handleConnect);
    srv.on("/api/save/mqtt",   HTTP_POST, _handleSaveMqtt);
    srv.on("/api/test/mqtt",   HTTP_POST, _handleTestMqtt);
    srv.on("/api/save/gpio",   HTTP_POST, _handleSaveGpio);
    srv.on("/api/gpio/state",  HTTP_GET,  _handleGpioState);
    srv.on("/api/gpio/output", HTTP_POST, _handleGpioOutput);
    srv.on("/api/reset",       HTTP_POST, _handleReset);
    srv.onNotFound(_handleNotFound);
}
