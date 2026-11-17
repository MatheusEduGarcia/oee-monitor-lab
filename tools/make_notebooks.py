"""
Builds and executes the study notebooks (Portuguese).

    python tools/make_notebooks.py        # needs an MQTT broker on 127.0.0.1:1883 for notebook 01

The notebooks are generated from this file so that text and code stay in one
place and every committed notebook is known to run from top to bottom.
"""
from pathlib import Path

import nbformat as nbf
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parent.parent
SETUP = """import sys, json, pathlib
ROOT = pathlib.Path.cwd().parent if pathlib.Path.cwd().name == "notebooks" else pathlib.Path.cwd()
sys.path.insert(0, str(ROOT))
%matplotlib inline"""


def build(name: str, cells: list[tuple[str, str]]):
    nb = nbf.v4.new_notebook()
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    for kind, src in cells:
        nb.cells.append(nbf.v4.new_markdown_cell(src.strip()) if kind == "md" else nbf.v4.new_code_cell(src.strip()))
    NotebookClient(nb, timeout=300, kernel_name="python3", resources={"metadata": {"path": str(ROOT / "notebooks")}}).execute()
    out = ROOT / "notebooks" / name
    nbf.write(nb, out)
    print("ok", out.name, len(nb.cells), "células")


def quiz(items: list[tuple[str, str]]) -> str:
    return "## Confira o que ficou\n\n" + "\n\n".join(
        f"**{i}. {q}**\n\n<details><summary>Ver resposta</summary>\n\n{a}\n\n</details>" for i, (q, a) in enumerate(items, 1))


# ----------------------------------------------------------------------------- 01
nb01 = [
("md", """
# 01 · O nó de coleta: o que um ESP32 diz sobre uma máquina

**Objetivo:** entender o que o nó lê da máquina, o que ele publica no MQTT e por que três firmwares escritos em momentos diferentes acabaram falando três dialetos.

## Antes de começar

- **Você precisa saber:** o básico de MQTT (tópico, publicar, assinar). Se não souber, a lição 05 do [iiot-protocols-examples](https://github.com/MatheusEduGarcia/iiot-protocols-examples) cobre isso.
- **Você não precisa de:** hardware. O `oeelab.node.Node` é o ESP32 sem a placa: mesmas entradas, mesmas mensagens.
- **Tempo:** 20 minutos.
- **Broker:** só a seção 4 usa um broker em `127.0.0.1:1883`. O resto roda sem rede.

![Arquitetura](../docs/img/architecture.png)
"""),
("code", SETUP),
("md", """
## 1. O que o nó lê

Um nó, uma máquina, até cinco sinais:

| Entrada | De onde vem | Tipo | Vira |
|---|---|---|---|
| start | botão ou sinal de ciclo | borda | evento `start` |
| stop | botão ou sinal de parada | borda | evento `stop` |
| peça boa | sensor ótico ou indutivo na saída | pulso | contador `output-good` |
| refugo | botão do operador | pulso | contador `output-defect` |
| rodando | contato auxiliar do contator | nível | `state` |

![Ligação](../docs/img/wiring.png)

O firmware usa `INPUT_PULLUP` com nível baixo ativo. Na bancada basta um botão entre o pino e o GND. Na máquina, sinais de 24 V **nunca** vão direto no pino: passam por um estágio optoisolado. Os detalhes estão em [docs/hardware.md](../docs/hardware.md).
"""),
("md", """
## 2. O que o firmware de hoje publica (v0)

Vamos ligar um nó virtual no dialeto `v0`, o do firmware `esp32_oee_full_signals`, e capturar o que sai. O parâmetro `wire` entrega as mensagens a uma função em vez de a um broker.
"""),
("code", """
from datetime import datetime, timedelta, timezone
from oeelab.contract import Machine
from oeelab.node import Node

maquina = Machine("packaging", "line-1", "cell-a", "filler-01")
t0 = datetime(2026, 11, 10, 9, 0, 0, tzinfo=timezone.utc)

capturado = []
no = Node(maquina, "v0", wire=lambda topico, payload, retido: capturado.append((topico, payload.decode(), retido)))
no.connect(t0)
no.press_start(t0 + timedelta(seconds=1))
no.piece(t0 + timedelta(seconds=3))
no.piece(t0 + timedelta(seconds=5), good=False)
no.press_stop(t0 + timedelta(seconds=9))

for topico, payload, retido in capturado:
    print(f"{topico.split('/')[-1]:14s} {'R' if retido else ' '}  {payload}")
"""),
("md", """
Leia o payload de `output-good` com calma. Ele tem um horário com resolução de **um segundo**, o valor `1` e o nome da máquina. Mais nada.

### Pare e preveja

A máquina faz **duas peças dentro do mesmo segundo**. O nó publica uma mensagem por peça. O que diferencia a primeira mensagem da segunda?

Decida antes de rodar a próxima célula.
"""),
("code", """
capturado.clear()
no.piece(t0 + timedelta(seconds=20, milliseconds=100))
no.piece(t0 + timedelta(seconds=20, milliseconds=600))
a, b = [p for _, p, _ in capturado]
print(a); print(b)
print("\\nAs duas mensagens são idênticas byte a byte?", a == b)
"""),
("md", """
Nada diferencia. Para quem recebe, isso é indistinguível de **uma** mensagem entregue duas vezes, coisa que o MQTT faz de verdade (QoS 1, bridges, reconexão). Um receptor cuidadoso descarta repetições, e aqui o cuidado vira perda de peça. O notebook 02 mede o tamanho do estrago.

## 3. Três firmwares, três dialetos

O repositório tem três sketches em `firmware/`, e cada um nasceu para resolver um caso:
"""),
("code", """
dialetos = {
  "esp32_oee_full_signals":  ("oee/uns/packaging/line-1/cell-a/filler-01/output",   '{"ts":"2026-11-10T06:00:00","value":1,"machine_id":"FILLER-01"}'),
  "esp32_oee_webconfig":     ("fabrica/linha1/m1/input/3",                            '{"label":"Peca boa","state":1,"ts":123456}'),
  "esp32_cnc_lathe_1button": ("lab/line1/cnc_lathe/button/start",                     '{"ts":"2026-11-10T06:00:00","value":1.0,"machine_id":"CNC-001"}'),
}
for nome, (topico, payload) in dialetos.items():
    print(f"{nome}\\n   tópico  {topico}\\n   payload {payload}\\n")
"""),
("md", """
Compare os três e anote as diferenças. As que importam:

| Ponto | full_signals | webconfig | cnc_lathe |
|---|---|---|---|
| Onde fica o nome do sinal | no tópico (`output`) | num rótulo livre dentro do payload | no tópico (`button/start`) |
| `ts` | hora **local** sem fuso, em segundos | **milissegundos desde o boot** | hora local sem fuso |
| Sem NTP | publica `1970-01-01T00:00:00` | não se aplica | publica 1970 |
| Hierarquia do tópico | `uns/area/linha/célula/máquina` | livre | `lab/line1/...` |

Nenhum está "errado" isolado. O problema aparece quando um único backend precisa entender os três, e é para isso que serve um contrato.

## 4. O nó morreu ou a máquina parou?

Sem dados chegando, o painel não sabe distinguir "máquina parada" de "nó sem energia". O MQTT resolve com o **last will**: ao conectar, o nó deixa com o broker uma mensagem para ser publicada se ele sumir.

Esta seção usa o broker de verdade.
"""),
("code", """
import time, paho.mqtt.client as mqtt
from oeelab.node import now_utc

m = Machine("lab", "line-9", "cell-z", "demo-01", prefix="oeenb")
visto = []
ouvinte = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
ouvinte.on_message = lambda c, u, msg: msg.payload and visto.append((msg.topic.split("/")[-1], json.loads(msg.payload)))
ouvinte.connect("127.0.0.1", 1883); ouvinte.subscribe(m.base + "/status"); ouvinte.loop_start()

no_real = Node(m, "v1")
no_real.connect(now_utc()); time.sleep(0.8)
print("depois de conectar :", visto[-1][1])

no_real.disconnect(graceful=False)        # queda de energia: o socket fecha sem aviso
time.sleep(1.5)
print("depois da queda    :", visto[-1][1])

ouvinte.publish(m.base + "/status", b"", retain=True); time.sleep(0.2); ouvinte.loop_stop()
"""),
("md", """
A segunda mensagem **não foi enviada pelo nó**, que já estava morto. Foi o broker que a publicou em nome dele. Por isso ela não tem `seq`, `boot` nem `ts`: foi escrita no momento da conexão.

![Ciclo de vida](../docs/img/lifecycle.png)

## Erros comuns

- **Ligar 24 V direto no pino.** O ESP32 é 3,3 V e não tolera nem 5 V. Use optoacoplador.
- **Confiar no relógio do nó.** Sem NTP o ESP32 acorda em 1970. O firmware precisa saber que o relógio não é confiável e dizer isso.
- **Usar hora local no payload.** Quem recebe não sabe o fuso. O payload leva UTC e quem exibe converte.
- **Achar que "sem mensagem" significa "parada".** Sem last will, um nó desligado parece uma máquina muito bem comportada.
- **Deixar o nome do sinal num rótulo livre.** "Peca boa", "peça boa" e "OK" viram três sinais diferentes.
"""),
("md", quiz([
 ("Por que duas peças no mesmo segundo geram mensagens idênticas no v0?", "Porque o único campo que muda entre mensagens é o `ts`, e ele tem resolução de um segundo. Valor (`1`) e máquina são sempre iguais."),
 ("Quem publica a mensagem `online: false` quando o nó perde energia?", "O broker. O nó registrou essa mensagem como last will ao conectar."),
 ("O que há de errado em publicar `millis()` como `ts`?", "É o tempo desde o boot, não um instante. Não dá para colocar o evento no calendário, e o valor volta a zero a cada reinício."),
 ("Uma máquina só tem um contato de 'rodando'. Que parte do OEE dá para calcular?", "A disponibilidade. Sem contagem de peças não há performance nem qualidade."),
])),
("md", """
## Exercícios

1. Crie um nó `v0` com `clock_synced=False`, publique três peças e observe o `ts`. O que o receptor consegue concluir sobre a ordem delas?
2. Rode a seção 4 com `graceful=True`. O last will é publicado? Por quê?
3. Abra `firmware/esp32_oee_webconfig/esp32_oee_webconfig.ino`, ache `handleInputs()` e descubra o que acontece quando um contato "quica" três vezes em 10 ms.

## Glossário

- **Nó de coleta:** o ESP32 ligado aos sinais de uma máquina.
- **Borda, pulso, nível:** mudança de estado, mudança curta que vai e volta, e estado que permanece.
- **Last will:** mensagem que o broker publica em nome de um cliente que desapareceu.
- **Retido (retain):** o broker guarda a última mensagem do tópico e a entrega a quem assinar depois.
- **Optoacoplador:** componente que passa o sinal por luz, sem ligação elétrica entre os dois lados.

## Próximo passo

No notebook **02** os três problemas viram números, e o contrato v1 resolve cada um com um campo.
"""),
]

# ----------------------------------------------------------------------------- 02
nb02 = [
("md", """
# 02 · O contrato v1: dois campos que salvam a contagem

**Objetivo:** medir quanto o payload v0 perde em três situações de chão de fábrica e ver, campo a campo, como o contrato v1 resolve cada uma.

## Antes de começar

- **Você precisa de:** o notebook 01.
- **Tempo:** 30 minutos.
- **Broker:** nenhum. Tudo roda com o nó ligado direto ao receptor, com relógio controlado, então os números são sempre os mesmos.

O texto completo do contrato está em [docs/protocol.md](../docs/protocol.md). Aqui vamos chegar nele pelos experimentos.
"""),
("code", SETUP),
("md", """
## 1. A regra do receptor

Do lado de quem recebe existe uma regra comum e razoável: **mensagem idêntica à outra aceita nos últimos 5 segundos é repetição, descarte**. Ela protege contra o broker ou uma bridge entregando a mesma mensagem duas vezes.

`LegacyPipeline` é essa regra em 15 linhas. O modelo foi conferido contra um backend de produção que aplica a mesma regra, com os mesmos números que você vai ver abaixo.

## 2. Experimento 1: máquina rápida

### Pare e preveja

Uma rotuladora faz **3 peças por segundo**. O nó v0 publica 30 peças em 10 segundos. Quantas o receptor conta: 30, 20, 10 ou 3?
"""),
("code", """
from oeelab.lab import bench, counted, pulses

no, rx, relogio = bench("v0")
pulses(no, relogio, n=30, period_s=1/3)
print("peças feitas  :", 30)
print("peças contadas:", counted(rx))
print("descartadas como repetição:", rx.dropped)
"""),
("md", """
Uma por segundo sobrevive. As outras duas de cada segundo têm exatamente os mesmos bytes da primeira.

Agora o mesmo teste com o contrato v1:
"""),
("code", """
no, rx, relogio = bench("v1")
pulses(no, relogio, n=30, period_s=1/3)
print("peças contadas:", counted(rx))
for _, p in no.sent[1:4]:
    print(json.dumps(p))
"""),
("md", """
Dois campos novos fazem o trabalho:

- **`seq`** sobe 1 a cada mensagem. Duas peças no mesmo milissegundo ainda são mensagens diferentes, e uma repetição de verdade tem o mesmo `seq`.
- **`total`** é a contagem desde o boot. Guarde esse campo, ele volta no experimento 3.

O gráfico abaixo repete o teste em várias velocidades.
"""),
("code", """
from oeelab import figures
figures.fast_pieces();
"""),
("md", """
## 3. Experimento 2: nó sem relógio

O ESP32 não tem bateria de relógio. Se o servidor NTP não responder no boot (rede industrial sem saída para a internet é o caso típico), o relógio começa em 1970.

### Pare e preveja

Máquina lenta, uma peça a cada 2 segundos, 8 peças. Com o relógio em 1970, quantas o receptor conta?
"""),
("code", """
no, rx, relogio = bench("v0", clock_synced=False)
pulses(no, relogio, n=8, period_s=2.0)
print("payload de toda peça:", json.dumps(no.sent[1][1]))
print("peças contadas      :", counted(rx), "de 8")
"""),
("md", """
Agora **toda** peça é idêntica, não só as do mesmo segundo. Passa uma a cada janela de 5 segundos.

A regra do v1 para tempo é curta: **`ts` é UTC correto ou não vai**. Sem relógio, o nó omite o campo e o receptor carimba com a própria hora.
"""),
("code", """
no, rx, relogio = bench("v1", clock_synced=False)
pulses(no, relogio, n=8, period_s=2.0)
print("payload:", json.dumps(no.sent[1][1]))
print("peças contadas:", counted(rx), "de 8")
"""),
("md", """
## 4. Experimento 3: o Wi-Fi cai

Este é o caso que nenhuma regra no receptor resolve. Se a rede cai por alguns minutos, a máquina continua produzindo.

### Pare e preveja

No v0, cada peça é uma mensagem `value: 1`. A rede fica fora por 4 minutos e meio numa máquina de uma peça a cada 2,3 s. Quando a rede volta, o que o receptor sabe sobre as peças desse intervalo?
"""),
("code", """
figures.outage();
"""),
("md", """
No v0, nada. A peça que não foi enviada deixou de existir.

No v1 o nó continua contando com a rede fora. Quando volta, a primeira mensagem leva `value` com tudo o que ficou pendente e o `total` atualizado. O receptor soma a **diferença de `total`**, então não importa quantas mensagens se perderam no caminho.

Vamos ver isso por dentro, mensagem a mensagem:
"""),
("code", """
from datetime import timedelta
from oeelab.lab import LABELER
from oeelab.scenario import SHIFT_START as t0

no, rx, relogio = bench("v1")
no.connect(t0)
def peca(s):
    relogio.now = t0 + timedelta(seconds=s); no.piece(relogio.now)

peca(1); peca(2)
no.link(False, t0 + timedelta(seconds=3))          # rede cai
for s in range(3, 13): peca(s)                      # 10 peças sem rede
relogio.now = t0 + timedelta(seconds=13)
no.link(True, relogio.now)                          # rede volta

for topico, p in no.sent:
    if "total" in p: print(f"seq {p['seq']:2d}  value {p['value']:2d}  total {p['total']:2d}")
print("\\ncontadas:", counted(rx), "de 12")
"""),
("md", """
## 5. Experimento 4: mensagens perdidas no caminho

O cliente MQTT usado no ESP32 só publica com QoS 0: enviou, esqueceu. Em Wi-Fi ruim, uma fração das mensagens some sem o nó saber. Vamos derrubar 20 % delas.
"""),
("code", """
no, rx, relogio = bench("v1", loss=0.20, seed=3)
pulses(no, relogio, n=200, period_s=0.5)
print("mensagens publicadas:", len(no.sent))
print("buracos no seq      :", rx.rows("SELECT COALESCE(SUM(missing),0) n FROM gaps")[0]["n"], "mensagens faltando")
print("peças recuperadas pelo total:", rx.rows("SELECT COALESCE(SUM(recovered),0) n FROM pieces")[0]["n"])
print("peças contadas      :", counted(rx), "de 200")
"""),
("md", """
O receptor **sabe** quantas mensagens perdeu (buracos no `seq`) e **recupera** as peças delas (diferença de `total`). Se a contagem ficar uma ou duas abaixo de 200, é porque a última mensagem também se perdeu: a recuperação só acontece quando chega a próxima. Como o contador é retido no broker, a próxima peça corrige.

## 6. O contrato inteiro em uma tabela

![Tópicos](../docs/img/topics.png)

| Campo | Para que serve | Problema que resolve |
|---|---|---|
| `v` | versão do contrato | receptor recusa o que não conhece |
| `seq` | número da mensagem | repetição de verdade tem o mesmo `seq`; buraco mostra perda |
| `boot` | identidade do boot | reinício do nó não parece contador andando para trás |
| `ts` | UTC com milissegundos, ou ausente | fim de 1970, de hora local e de `millis()` |
| `total` | contagem desde o boot | peça de mensagem perdida ou de rede fora é recuperada |

O contrato também é código. `validate` devolve a lista de problemas de um payload:
"""),
("code", """
from oeelab.contract import validate

exemplos = {
  "v1 correto":            {"v":1,"seq":42,"boot":"a1b2c3","ts":"2026-11-10T09:00:02.480Z","value":1,"total":1532},
  "v0 full_signals":       {"ts":"2026-11-10T06:00:00","value":1,"machine_id":"FILLER-01"},
  "v0 webconfig":          {"label":"Peca boa","state":1,"ts":123456},
  "hora local sem Z":      {"v":1,"seq":42,"boot":"a1b2c3","ts":"2026-11-10T06:00:02","value":1,"total":1532},
  "total menor que value": {"v":1,"seq":42,"boot":"a1b2c3","value":5,"total":3},
}
for nome, p in exemplos.items():
    erros = validate("output-good", p)
    print(f"{nome:22s} {'OK' if not erros else 'RECUSADO: ' + erros[0]}")
"""),
("md", """
## Erros comuns

- **Resolver no receptor o que é defeito do payload.** Afrouxar a regra de repetição faz o v0 contar certo e volta a contar em dobro quando o broker repetir.
- **Aumentar a resolução do `ts` e parar aí.** Milissegundos reduzem a colisão e não resolvem rede fora nem mensagem perdida. `seq` e `total` resolvem.
- **Zerar o `total` a cada mensagem.** Ele só serve se for acumulado desde o boot.
- **Reusar o `boot` entre reinícios.** O receptor acharia que o contador andou para trás.
- **Confiar em QoS 1 para não perder peça.** QoS trata do trecho cliente e broker. Não ajuda se o nó nem estava conectado.
"""),
("md", quiz([
 ("Qual campo permite recuperar peças de mensagens que nunca chegaram?", "`total`. O receptor soma a diferença entre o `total` recebido e o último que conhecia."),
 ("Para que serve `seq` se o `total` já recupera as peças?", "Para descartar repetições com certeza (mesmo `boot` e `seq`) e para saber que houve perda, o que é um indicador de saúde da rede. Vale também para sinais sem total, como `state`."),
 ("O nó reinicia e o `total` volta a 2. Como o receptor sabe que não é erro?", "O `boot` mudou. Boot novo zera a referência, e o receptor conta 2 em vez de uma diferença negativa."),
 ("Por que o v1 manda omitir `ts` em vez de enviar o melhor palpite?", "Porque um horário errado parece dado bom e contamina cálculos de duração. A ausência é honesta, e o receptor usa a própria hora."),
 ("Qual perda o v1 ainda não resolve?", "Peças contadas entre a última mensagem entregue e uma queda de energia, porque o `total` vive em RAM."),
])),
("md", """
## Exercícios

1. Em `bench("v0")`, descubra a maior velocidade (peças por segundo) em que o v0 ainda conta 100 %. Explique o número.
2. Rode o experimento 4 com `loss=0.5`. A contagem continua certa? E o número de buracos?
3. Escreva um payload de `state` válido e um inválido e passe os dois por `validate("state", ...)`.
4. Leia a seção 9 de `docs/protocol.md` e proponha como seria o campo que falta para o `total` sobreviver a uma queda de energia.

## Glossário

- **Contrato:** acordo escrito e testável sobre tópicos e payloads.
- **Idempotente:** processar a mesma mensagem duas vezes dá o mesmo resultado que uma.
- **Contador acumulado:** valor que só cresce, do qual se tira a diferença.
- **QoS 0:** entrega no máximo uma vez, sem confirmação.
- **Dead letter:** lugar onde ficam as mensagens recusadas, com o motivo.

## Próximo passo

No notebook **03** um turno inteiro de três máquinas passa pelo coletor e vira OEE, e os firmwares antigos entram no contrato sem regravar nenhuma placa.
"""),
]

# ----------------------------------------------------------------------------- 03
nb03 = [
("md", """
# 03 · Do evento ao OEE, e como migrar sem regravar as placas

**Objetivo:** passar um turno de três máquinas pelo coletor de referência, calcular o OEE e conferir contra o que realmente aconteceu. Depois, trazer os firmwares v0 para o contrato com um adaptador.

## Antes de começar

- **Você precisa de:** os notebooks 01 e 02.
- **Tempo:** 25 minutos.
- **Broker:** nenhum.
"""),
("code", SETUP),
("md", """
## 1. O turno e a verdade

`oeelab.scenario` gera um turno de 8 horas para três máquinas, sempre igual (a semente é fixa). Cada máquina roda, para algumas vezes, faz cerca de 3 % de refugo e **perde a rede uma vez**.

O roteiro também devolve a **verdade**: quantas peças foram realmente feitas e quanto tempo a máquina realmente rodou. É contra isso que o coletor será conferido.
"""),
("code", """
from oeelab.scenario import MACHINES, script

for nome in MACHINES:
    passos, verdade = script(nome)
    print(f"{nome:10s} {len(passos):6d} passos | boas {verdade.good:6d} | refugo {verdade.defect:4d} | "
          f"rodando {verdade.run_s/3600:4.2f} h | rede fora {verdade.offline_s/60:3.1f} min | paradas {len(verdade.stops)}")
"""),
("md", """
## 2. O coletor

`Collector.handle()` recebe tópico, bytes e hora de recebimento, e grava em SQLite. A ordem das decisões é a da seção 5 do contrato:

1. tópico ou payload fora do contrato vai para a tabela de recusados, com o motivo;
2. `status` atualiza a saúde do nó;
3. mesmo `boot` com `seq` já visto é repetição;
4. salto no `seq` é registrado como perda;
5. contador soma a diferença de `total`.

### Pare e preveja

O turno vai passar pelo coletor duas vezes: uma com nós v1 e outra com nós v0 (contados pela regra do notebook 02). As máquinas fazem menos de uma peça por segundo e o relógio está certo. O v0 erra a contagem? Onde?
"""),
("code", """
from oeelab.lab import run_shift, counted

v1, v0 = run_shift("v1"), run_shift("v0")
print(f"{'máquina':10s} {'verdade':>8s} {'v1':>8s} {'v0':>8s} {'v0 perdeu':>10s}")
for nome, (maquina, _) in MACHINES.items():
    verdade = v1[nome][1].good
    c1, c0 = counted(v1[nome][0], maquina), counted(v0[nome][0], maquina)
    print(f"{nome:10s} {verdade:8d} {c1:8d} {c0:8d} {verdade - c0:10d}")
"""),
("md", """
O v0 perde exatamente as peças feitas enquanto a rede estava fora. É pouco mais de 1 % da produção em cada máquina, com uma única queda de poucos minutos no turno. Uma planta com Wi-Fi instável perde isso várias vezes por dia, sempre para o mesmo lado: **contando menos**.

## 3. Do que foi gravado ao OEE

Com estados e contagens gravados, o OEE é aritmética:

- **Disponibilidade** = tempo rodando ÷ tempo planejado
- **Performance** = (peças × ciclo ideal) ÷ tempo rodando
- **Qualidade** = peças boas ÷ peças totais
"""),
("code", """
from datetime import timedelta
from oeelab.oee import compute
from oeelab.scenario import SHIFT_START, SHIFT_HOURS

fim = SHIFT_START + timedelta(hours=SHIFT_HOURS)
print(f"{'máquina':10s} {'disp.':>7s} {'perf.':>7s} {'qual.':>7s} {'OEE':>7s}   tempo rodando (coletor / verdade)")
for nome, (maquina, ciclo) in MACHINES.items():
    rx, verdade = v1[nome]
    o = compute(rx, maquina.base, SHIFT_START, fim, ciclo)
    print(f"{nome:10s} {o.availability:7.1%} {o.performance:7.1%} {o.quality:7.1%} {o.oee:7.1%}   {o.run_s:7.0f} s / {verdade.run_s:7.0f} s")
figures = __import__("oeelab.figures", fromlist=["oee"]); figures.oee();
"""),
("md", """
O tempo rodando sai do sinal `state`, que é retido e republicado a cada reconexão. Os eventos `start` e `stop` registram a intenção do operador e podem se perder sem estragar a conta.

O mesmo turno, enviado no contrato v1 para um painel de OEE de verdade:

![Painel](../docs/img/dashboard_multi.png)

## 4. O que o coletor recusa

Um contrato só vale se alguém o faz cumprir. Vamos mandar ao coletor o que os firmwares v0 publicam hoje:
"""),
("code", """
from oeelab.collector import Collector
from oeelab.contract import Machine

c = Collector()
m = Machine("packaging", "line-1", "cell-a", "filler-01")
agora = SHIFT_START
print(c.handle(m.topic("output-good"), b'{"ts":"2026-11-10T06:00:00","value":1,"machine_id":"FILLER-01"}', agora))
print(c.handle("fabrica/linha1/m1/input/3", b'{"label":"Peca boa","state":1,"ts":123456}', agora))
print(c.handle(m.topic("output-good"), b'isto nao e json', agora))
print()
for linha in c.rows("SELECT topic, reason FROM dlq"):
    print(f"{linha['topic'][-32:]:32s} -> {linha['reason'][:90]}")
"""),
("md", """
Nada é jogado fora em silêncio: cada recusa fica guardada com o motivo. Em produção, essa tabela é o primeiro lugar onde olhar quando "a máquina não aparece".

## 5. Migrar sem regravar: o adaptador

Regravar firmware em dezenas de placas instaladas leva tempo. O adaptador é um processo pequeno ao lado do broker: assina os tópicos antigos e republica cada mensagem no contrato v1.

### Pare e preveja

O adaptador vê duas mensagens v0 **idênticas** no mesmo segundo. Ele deve tratar como uma peça repetida ou como duas peças?
"""),
("code", """
from oeelab.adapter import Adapter, Route

torno = Machine("machining", "line-1", "cell-a", "lathe-01")
adaptador = Adapter({
    "oee/uns/packaging/line-1/cell-a/filler-01/output": Route(m, "output-good"),
    "fabrica/linha1/m1/input/1":                         Route(m, "start"),
    "lab/line1/cnc_lathe/status":                        Route(torno, "state"),
}, boot="c0ffee")

entradas = [
  ("oee/uns/packaging/line-1/cell-a/filler-01/output", b'{"ts":"2026-11-10T06:00:00","value":1,"machine_id":"FILLER-01"}'),
  ("oee/uns/packaging/line-1/cell-a/filler-01/output", b'{"ts":"2026-11-10T06:00:00","value":1,"machine_id":"FILLER-01"}'),
  ("fabrica/linha1/m1/input/1",                         b'{"label":"Start","state":1,"ts":123456}'),
  ("lab/line1/cnc_lathe/status",                        b'{"ts":"2026-11-10T06:00:05","running":true,"value":1}'),
]
destino = Collector()
for topico, bruto in entradas:
    novo_topico, novo = adaptador.translate(topico, bruto, agora)
    print(f"{novo_topico.split('uns/')[1]:45s} {json.dumps(novo)}")
    destino.handle(novo_topico, json.dumps(novo).encode(), agora)
print("\\npeças no coletor:", destino.pieces(m.base), "| recusadas:", len(destino.rows("SELECT 1 FROM dlq")))
"""),
("md", """
O adaptador trata como **duas peças**. Ele está logo depois do broker, onde repetição é rara, e dá a cada mensagem um `seq` próprio. A partir dali, todo consumidor recebe mensagens distinguíveis.

O que o adaptador resolve e o que não resolve:

| Problema do v0 | Adaptador | Firmware v1 |
|---|---|---|
| peças no mesmo segundo | resolve | resolve |
| relógio em 1970, hora local, `millis()` | resolve (usa a hora de recebimento) | resolve |
| três dialetos e três hierarquias de tópico | resolve | resolve |
| peças feitas com a rede fora | **não resolve** | resolve |
| mensagem perdida entre a placa e o broker | **não resolve** | resolve |

O adaptador compra tempo. As duas últimas linhas só mudam com o firmware, e a lista de alterações está em [docs/firmware_v1_changes.md](../docs/firmware_v1_changes.md).

## Erros comuns

- **Calcular tempo rodando por `start` e `stop`.** Um evento perdido deixa a máquina "rodando" a noite toda. Use `state`.
- **Descartar mensagem inválida sem registrar.** Sem a tabela de recusados, um nó mal configurado é invisível.
- **Colocar o adaptador longe do broker.** Quanto mais saltos antes dele, mais repetições legítimas ele confunde com peças.
- **Tratar o adaptador como solução final.** Ele não recupera o que nunca chegou.
- **Conferir o sistema só contra ele mesmo.** O teste que vale compara com uma verdade externa, aqui o roteiro do turno.
"""),
("md", quiz([
 ("De qual sinal sai o tempo rodando, e por quê?", "De `state`. É um nível, retido e republicado na reconexão, então o receptor converge para a verdade mesmo perdendo mensagens."),
 ("O v0 perdeu cerca de 1 % das peças no turno simulado. Qual foi a causa?", "A queda de rede. Cada peça era uma mensagem isolada, e as feitas sem conexão nunca foram enviadas."),
 ("Por que o adaptador conta duas mensagens idênticas como duas peças?", "Porque no v0 peças reais no mesmo segundo são idênticas, e ao lado do broker a repetição é rara. O erro de contar a menos é o mais provável."),
 ("O que o adaptador não consegue fazer?", "Recuperar pulsos que nunca chegaram ao broker: rede fora ou mensagem perdida entre a placa e o broker."),
])),
("md", """
## Exercícios

1. Rode `run_shift("v1", loss=0.1)` e compare contagem e OEE com o turno sem perda. O que muda e o que não muda?
2. Envie ao coletor um contador com `boot` novo no meio do turno e veja a coluna `reboots` da tabela `node`.
3. Acrescente ao adaptador uma rota para o refugo do `esp32_oee_full_signals` (tópico terminado em `/defect`).
4. Com um broker local, rode `python -m oeelab.demo` e depois `python -m oeelab.check_node oee/uns/packaging/line-1/cell-a/filler-01 --seconds 5`.

## Glossário

- **OEE:** disponibilidade × performance × qualidade.
- **Verdade de referência:** o que realmente aconteceu, conhecido por fora do sistema que está sendo testado.
- **Adaptador:** processo que traduz um protocolo antigo para o novo sem mexer na origem.
- **Baseline:** valor de partida de um contador acumulado, a partir do qual se contam diferenças.

## Próximo passo

- O mesmo raciocínio de contrato, aplicado a um namespace inteiro: lição 06 (UNS) do [iiot-protocols-examples](https://github.com/MatheusEduGarcia/iiot-protocols-examples).
- Dar significado aos dados coletados: [industrial-ontology-lab](https://github.com/MatheusEduGarcia/industrial-ontology-lab).
- Proteger o broker e os nós: [ot-security-lab](https://github.com/MatheusEduGarcia/ot-security-lab).
"""),
]

# ----------------------------------------------------------------------------- 04
nb04 = [
("md", """
# 04 · Além do OEE: MTBF, MTTR e a família TEEP, OAE, OOE, OPE e OFE

**Objetivo:** calcular, a partir dos mesmos dados coletados, os indicadores de confiabilidade e os parentes do OEE, entender o que cada um mede e conferir tudo contra a verdade de uma semana simulada.

## Antes de começar

- **Você precisa de:** o notebook 03 (OEE a partir de estados e contadores).
- **Tempo:** 30 minutos.
- **Broker:** nenhum.
- **Referência:** [docs/indicators.md](../docs/indicators.md) tem as fórmulas exatas e as fontes.
"""),
("code", SETUP),
("md", """
## 1. O dado que faltava: por que a máquina parou

Até o notebook 03 o nó só dizia "rodando" ou "parada". Para separar quebra de almoço, o `state` ganhou dois campos opcionais:

| Campo | Valores |
|---|---|
| `category` | `closed`, `unscheduled`, `planned`, `failure`, `unplanned` |
| `reason` | `meal`, `changeover`, `preventive`, `jam`, `seal-wear`, `no-material`... |

Na prática, o motivo vem do operador no painel ou de um código de falha do CLP. O contrato continua v1: quem ignora os campos novos segue funcionando.
"""),
("code", """
from oeelab.contract import validate
base = {"v":1, "seq":88, "boot":"a1b2c3", "value":0, "running":False}
for nome, p in {"falha com modo": {**base, "category":"failure", "reason":"seal-wear"},
                "categoria inventada": {**base, "category":"quebrou"},
                "motivo fora do padrão": {**base, "reason":"Seal Wear"}}.items():
    e = validate("state", p)
    print(f"{nome:22s} {'OK' if not e else 'RECUSADO: ' + e[0][:70]}")
"""),
("md", """
## 2. A semana

`oeelab.week` simula uma semana de três máquinas em duas linhas:

| | Linha 1 (enchedora e tampadora) | Linha 2 (prensa) |
|---|---|---|
| Segunda a sexta | 3 turnos | 2 turnos |
| Sábado | 1 turno | sem turno |
| Domingo | fábrica fechada | fábrica fechada |
| Em todo turno | almoço de 30 min | almoço de 30 min |
| Turno A | troca de formato de 25 min | troca de formato de 25 min |
| Quarta, turno A | preventiva de 2 h | preventiva de 2 h |

As falhas são sorteadas com um MTBF próprio de cada máquina, e cada modo de falha tem seu tempo médio de reparo. Toda parada é publicada com categoria e motivo, passa pelo coletor e vira linha no banco.
"""),
("code", """
from oeelab.weeklab import run_week, lines
medido, verdade, coletor = run_week()

h = 3600
print(f"{'máquina':10s} {'rodando':>8s} {'planej.':>8s} {'falha':>7s} {'outras':>7s} {'sem turno':>10s} {'fechada':>8s} {'total':>7s}")
for nome, t in medido.items():
    s = t.seconds
    print(f"{nome:10s} {s['run']/h:8.1f} {s['planned']/h:8.1f} {s['failure']/h:7.1f} {s['unplanned']/h:7.1f} "
          f"{s['unscheduled']/h:10.1f} {s['closed']/h:8.1f} {sum(s.values())/h:7.1f}")
print("\\nmensagens recusadas:", coletor.rows("SELECT COUNT(*) n FROM dlq")[0]["n"])
"""),
("md", """
Cada segundo das 168 horas cai em exatamente um balde. É essa contabilidade completa que permite comparar os indicadores.

## 3. MTBF e MTTR

### Pare e preveja

Sem a categoria, tudo o que se sabe é "parou". Se você calcular o tempo médio entre paradas e a duração média de parada misturando almoço, troca de formato e quebra, o resultado fica **maior ou menor** que o MTBF e o MTTR de verdade?
"""),
("code", """
from oeelab.week import FLEET
for nome, t in medido.items():
    paradas = coletor.rows("SELECT COUNT(*) n FROM states WHERE machine=? AND running=0 AND category IN ('planned','failure','unplanned')",
                           FLEET[nome][0].base)[0]["n"]
    tempo_parado = t.seconds["planned"] + t.seconds["failure"] + t.seconds["unplanned"]
    print(f"{nome:10s} sem categoria: entre paradas {t.seconds['run']/paradas/h:5.2f} h, parada média {tempo_parado/paradas/60:5.1f} min "
          f"| com categoria: MTBF {t.mtbf_h:5.2f} h, MTTR {t.mttr_min:5.1f} min, falhas {len(t.failures)}")
"""),
("md", """
Sem a categoria, a máquina parece quebrar **de duas a sete vezes mais** do que quebra de fato, porque cada almoço e cada troca de formato contam como "falha". O MTTR aparente também fica distorcido. Um plano de manutenção feito em cima desses números atacaria o problema errado.

Por modo de falha, o mesmo cálculo aponta o que corrigir primeiro:
"""),
("code", """
for nome, t in medido.items():
    print(nome)
    for modo, d in sorted(t.by_mode().items(), key=lambda kv: -kv[1]["downtime_min"]):
        print(f"   {modo:18s} {d['failures']:3d} falhas  {d['downtime_min']:6.0f} min parada  MTTR {d['mttr_min']:5.1f} min")
"""),
("md", """
Repare que o modo mais frequente nem sempre é o que mais tira tempo. Uma falha rara e demorada pode custar mais que dez travamentos rápidos. Por isso o ranking por **tempo parado** vem antes do ranking por contagem.

## 4. A família do OEE: o mesmo numerador, quatro denominadores

Todos são `peças boas × ciclo ideal ÷ tempo de referência`. Só o tempo de referência muda:

| Indicador | Tempo de referência |
|---|---|
| TEEP | calendário inteiro |
| OAE | calendário menos fábrica fechada |
| OOE | menos o tempo sem turno programado |
| OEE | menos as paradas planejadas |

### Pare e preveja

A prensa trabalha só dois turnos e a linha 1 trabalha três. Qual máquina tem o maior OEE? E o maior TEEP?
"""),
("code", """
print(f"{'máquina':10s} {'TEEP':>6s} {'OAE':>6s} {'OOE':>6s} {'OEE':>6s}   (medido = verdade?)")
for nome, t in medido.items():
    v = verdade[nome]
    iguais = all(abs(t.indicator(k) - v.indicator(k)) < 1e-9 for k in ("TEEP","OAE","OOE","OEE"))
    print(f"{nome:10s} " + " ".join(f"{t.indicator(k):6.1%}" for k in ("TEEP","OAE","OOE","OEE")) + f"   {iguais}")
from oeelab import figures
figures.family();
"""),
("md", """
A prensa tem o **maior OEE** e o **menor TEEP**. As duas coisas são verdade ao mesmo tempo:

- **OEE** diz que, nas horas em que foi planejado produzir, a prensa foi bem usada.
- **TEEP** diz que a prensa fica parada a maior parte da semana porque não há turno para ela.

São perguntas diferentes. O OEE serve para o supervisor do turno melhorar a operação. O TEEP serve para decidir investimento: antes de comprar uma prensa nova, existe capacidade sobrando na que já está lá, bastaria um terceiro turno.

A cascata mostra onde cada hora da semana da prensa foi parar, com cada indicador marcado no degrau em que ele mede:
"""),
("code", """
figures.waterfall();
"""),
("md", """
Lendo da esquerda para a direita:

- **OAE para TEEP:** o custo de fechar no domingo.
- **OOE para OAE:** o custo de não ter turno.
- **OEE para OOE:** o custo das paradas planejadas. Almoço e troca de formato não são "perda" para o OEE, mas o OOE mostra quanto eles custam.
- **Abaixo do OEE:** falhas, velocidade e refugo, as perdas clássicas.

## 5. Linha e fábrica: OPE e OFE

O cliente não recebe peças da enchedora, recebe da **saída da linha**. O OPE mede a linha: peças boas que saíram da última máquina, no ritmo da máquina mais lenta, contra o tempo planejado da linha.
"""),
("code", """
r_med, r_ver = lines(medido), lines(verdade)
for k in ("line-1", "line-2", "plant"):
    nome = "OFE (fábrica)" if k == "plant" else f"OPE {k}"
    print(f"{nome:14s} {r_med[k]:6.1%}   verdade {r_ver[k]:6.1%}")
print()
for n in ("filler-01", "capper-01"):
    print(f"OEE {n}: {medido[n].indicator('OEE'):6.1%}")
"""),
("md", """
**Limite honesto:** nesta simulação as máquinas de uma linha rodam de forma independente. Na vida real, quando a tampadora para, a enchedora enche o pulmão e para também. Modelar esse acoplamento é o próximo passo, e nele o OPE costuma ficar bem abaixo do OEE de cada máquina.

**Outro limite:** OAE, OPE e OFE não têm definição única. Aqui estão escritas as usadas neste repositório. Antes de comparar com outro número, confira a fórmula.

## Erros comuns

- **Chamar toda parada de falha.** O MTBF despenca e o MTTR fica enganoso. Sem categoria, chame de "tempo entre paradas" e não de MTBF.
- **Comparar OEE entre plantas com calendários diferentes.** Uma planta pode ter OEE alto e TEEP baixo só por trabalhar menos turnos.
- **Tirar a preventiva do OEE e esquecer dela.** Ela some do OEE e aparece no OOE. Quem só olha o OEE não vê a preventiva crescendo.
- **Ranquear falhas por contagem.** O que importa é o tempo parado.
- **Somar OEE de máquinas para ter o da linha.** A linha entrega o que sai da última máquina. Use o OPE.
"""),
("md", quiz([
 ("Por que TEEP ≤ OAE ≤ OOE ≤ OEE sempre?", "O numerador é o mesmo e o tempo de referência só diminui de um para o outro, porque cada um tira mais um balde do calendário."),
 ("O que o MTBF calculado sem a categoria da parada mede de verdade?", "O tempo médio entre paradas de qualquer tipo. Almoço e troca de formato entram como se fossem quebras."),
 ("A prensa tem OEE de 81 % e TEEP de 34 %. Qual número usar para decidir comprar outra prensa?", "O TEEP. Ele mostra que a prensa já existente fica a maior parte da semana sem turno, então há capacidade antes de investir."),
 ("Uma preventiva de 2 h aparece em qual indicador?", "Ela fica fora do OEE (é parada planejada) e reduz o OOE, o OAE e o TEEP."),
 ("Por que medir a linha na última máquina?", "Porque é o que a linha entrega. Uma máquina boa no meio de uma linha travada não produz nada para o cliente."),
])),
("md", """
## Exercícios

1. Em `oeelab/week.py`, mude a linha 2 para três turnos (`"ABC"`). O OEE da prensa muda? E o TEEP?
2. Dobre o MTBF da enchedora e veja quanto sobe o OEE da máquina e o OPE da linha 1.
3. Calcule a disponibilidade intrínseca, MTBF ÷ (MTBF + MTTR), de cada máquina e compare com a disponibilidade do OEE. Por que são diferentes?
4. Proponha uma regra para quando o operador não apontar o motivo: a parada vira `unplanned` com `reason` vazio? Que efeito isso tem no MTBF?

## Glossário

- **MTBF:** tempo médio rodando entre duas falhas.
- **MTTR:** tempo médio parado por falha, do início da falha até voltar a rodar.
- **TEEP:** OEE medido contra o calendário inteiro.
- **OOE:** OEE medido contra o tempo com turno, contando as paradas planejadas como perda.
- **OAE:** aqui, medido contra o calendário menos o tempo em que a fábrica estava fechada.
- **OPE:** eficácia da linha medida na saída dela.
- **OFE:** eficácia da fábrica, linhas ponderadas pelo tempo planejado.

## Próximo passo

Dar contexto a esses números: em qual equipamento, com qual ordem e qual lote. Veja o [industrial-ontology-lab](https://github.com/MatheusEduGarcia/industrial-ontology-lab).
"""),
]

if __name__ == "__main__":
    import sys
    only = sys.argv[1:]
    for name, cells in (("01_o_no_de_coleta.ipynb", nb01), ("02_contrato_v1.ipynb", nb02),
                        ("03_do_evento_ao_oee.ipynb", nb03), ("04_alem_do_oee.ipynb", nb04)):
        if not only or any(name.startswith(o) for o in only):
            build(name, cells)
