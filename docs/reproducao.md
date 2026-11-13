# Compilacao e reproducibilidade (sem acesso a hardware)

Este roteiro parte de uma copia limpa do repositorio. Ele **compila fontes**, mas nao reexecuta os ensaios fisicos, nao garante equivalencia binaria bit a bit com as compilacoes de outubro de 2026 e nao altera os registros originais.

## Ambiente

- ESP-IDF **v6.0.2** para ambos ESP32-WROOM-32, com `idf.py` disponivel apos ativar `export.sh`.
- Raspberry Pi Pico C/C++ SDK **2.2.0** e compilador `arm-none-eabi-gcc` para RP2040.
- CMake, Ninja, Python 3. Todos os comandos partem da raiz do repositorio.

```bash
git clone https://github.com/calebe-sucupira/can-busoff-mitigation.git
cd can-busoff-mitigation
```

## ESP32: No A e No B

Ative previamente o ambiente do ESP-IDF v6.0.2:

```bash
idf.py -C firmware/node-a set-target esp32
idf.py -C firmware/node-a build

idf.py -C firmware/node-b set-target esp32
idf.py -C firmware/node-b build
```

Os dois projetos possuem `sdkconfig.defaults` com `CONFIG_FREERTOS_HZ=1000`, necessario para as tarefas periodicas de monitoramento de 1 ms. O arquivo `sdkconfig` completo e local, ignorado pelo Git e gerado na configuracao. Antes de usar esses comandos sobre um projeto previamente compilado, lembre-se de que `set-target` recria as configuracoes locais.

O firmware do No A tem `ENABLE_THROTTLING=0` por padrao. **Compilar dessa forma nao testa a variante adaptativa.** Para compilar as duas variantes em diretorios isolados, depois de gerar o `sdkconfig` de No A, use:

```bash
python3 experiments/characterization/complementary/preparar_binarios_node_a.py \
  --project firmware/node-a --output /tmp/binarios_node_a_reproducao --build
```

Esse procedimento cria novas imagens e um manifesto novo; nao substitua as imagens nem o manifesto da campanha de outubro. Um clone limpo nao contem o `sdkconfig` historico integral, logo os hashes dos aplicativos antigos nao devem ser exigidos das novas compilacoes.

## RP2040: injetor parametrizavel e variante PHASE20

Depois de instalar o SDK da Raspberry Pi na versao indicada e definir `PICO_SDK_PATH`:

```bash
cmake -S firmware/pico-injector -B /tmp/build-pico-param -DPICO_BOARD=pico
cmake --build /tmp/build-pico-param

python3 experiments/busoff/preparar_workspace_phase20.py \
  --repo . --output /tmp/pico-phase20-reproducao
cmake -S /tmp/pico-phase20-reproducao -B /tmp/build-pico-phase20 -DPICO_BOARD=pico
cmake --build /tmp/build-pico-phase20
```

`preparar_workspace_phase20.py` compara os hashes do codigo-base e do PIO antes de preparar a copia. Essa variante foi usada na campanha de progressao ate Bus-Off e e distinta do injetor parametrizavel.

## Checagens sem hardware

```bash
python3 -m compileall -q experiments
python3 experiments/characterization/initial/executar_campanha_CAN.py --dry-run
python3 experiments/characterization/complementary/executar_campanha_CAN_complementar.py --dry-run
python3 experiments/busoff/executar_campanha_integral_phase20.py --dry-run
python3 experiments/busoff/executar_campanha_CAN_phase20.py \
  --plan experiments/busoff/plano_campanha_phase20_40_runs.csv --dry-run
```

O executor individual PHASE20 preserva seu hash original porque o orquestrador confere esse arquivo antes da execucao. Por isso seu argumento `--plan` deve ser explicitado; seu valor padrao historico aponta para um plano de outra campanha.

## Conjunto de dados publicado

Os 100 ensaios definitivos são disponibilizados como ZIPs individuais: 153–188 e 197–220 em `data/zips/`, e 304–343 em `data/busoff_estudo_2026/zips/`. Cada ZIP contém os arquivos brutos da execução. As cópias descompactadas e os pacotes consolidados redundantes não integram o repositório atual.

Os ZIPs dos pilotos 300 e 303 são conservados separadamente dos 100 ensaios porque a função `verify_pilots()` do orquestrador de Bus-Off os exige antes de uma nova execução física usando o diretório padrão. Esses pilotos não integram as estatísticas finais.

## Rastreabilidade dos binarios historicos

A versao historica de `experiments/characterization/complementary/binarios_node_a_complementar/manifesto_binarios.json` conserva caminhos absolutos existentes na maquina durante a coleta. Esses caminhos **nao sao referencias validas para o novo layout** e foram mantidos intocados para preservar o registro historico. Localizacoes atuais:

| Condicao | Caminho atual relativo ao repositorio | SHA-256 historico |
| --- | --- | --- |
| REFERENCIA | `experiments/characterization/complementary/binarios_node_a_complementar/node_a_referencia.bin` | `559b0773e025a2639186503acd75b3ccc30ea7caebbe966ae457a0d65ce0dd6e` |
| ADAPTATIVO | `experiments/characterization/complementary/binarios_node_a_complementar/node_a_adaptativo.bin` | `e65d74af829c0307988542a2483300d2f8435a9674dafce1c9b1495da56cf3db` |

A variante de telemetria do No A usada nas execucoes 304–343 esta preservada como `experiments/busoff/node_a_busoff_trace.c`. O workspace historico externo `_compilacao_telemetria_busoff_2026-10-20` nao integra o clone; recompilar essa variante requer preparar novamente um workspace independente e nao reproduz automaticamente os hashes registrados nos ensaios.

## Limites da validacao

O GitHub Actions verifica a compilacao dos firmwares ESP32 e RP2040. Os comandos `--dry-run` mostrados acima conferem os planos sem acessar dispositivos. A compilacao automatica nao mede pulsos no osciloscopio, nao verifica a instrumentacao eletrica nem demonstra que novos binarios reproduzem o mesmo comportamento dos experimentos. Nao grave dispositivos ou acione o injetor durante a verificacao de software.
