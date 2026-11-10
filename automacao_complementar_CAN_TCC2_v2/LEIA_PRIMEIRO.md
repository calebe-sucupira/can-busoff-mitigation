# Automação complementar CAN — v2

Esta versão adiciona **geração automática dos dois binários do Nó A** ao executor complementar v1. Ela **não altera o repositório original** e não mexe na lógica do firmware. Não foram incluídos novos perfis de injeção nem houve experimentos físicos.

## 1. Preparação (uma vez)

Abra o terminal do Linux e ative o ESP-IDF instalado:

```bash
source ~/esp/esp-idf/export.sh
```

Na pasta que contém `preparar_binarios_node_a.py`, primeiro confira os caminhos, sem compilar:

```bash
python3 preparar_binarios_node_a.py --project /CAMINHO/DO/REPOSITORIO/firmware/node-a
```

Depois inicie as compilações automáticas:

```bash
python3 preparar_binarios_node_a.py --project /CAMINHO/DO/REPOSITORIO/firmware/node-a --build
```

O programa cria duas cópias temporárias de compilação e adiciona a definição `ENABLE_THROTTLING=0` ou `=1` **somente ao CMake dessas cópias**, mantendo intacto o `main.c` e o CMake original. Cada imagem é salva em arquivo distinto:

- `binarios_node_a_complementar/node_a_referencia.bin`
- `binarios_node_a_complementar/node_a_adaptativo.bin`

O manifesto registra SHA-256 do código e dos arquivos e confere que as duas versões usam as mesmas imagens auxiliares de bootloader/partições e aplicação em `0x10000`. Se os binários já estiverem prontos e o código não tiver mudado, uma nova chamada **não recompila**. Se o código mudar, escolha uma pasta de saída nova para preservar o histórico.

**Requer o ESP-IDF e a compilação real no computador do usuário.** Nesta entrega, houve validação estática e dry-run, não compilação efetiva com o ESP-IDF nem gravação física no ESP32.

## 2. Uso posterior no executor complementar

**Primeiro:** validar individualmente no Nó A o boot de cada imagem e confirmar `throttling=0` e `throttling=1`. Só depois, com o plano experimental revisado, usar:

```bash
python3 orquestrar_campanha_complementar.py \
  --plan PLANO_COMPLEMENTAR_APROVADO.csv \
  --reference-bin binarios_node_a_complementar/node_a_referencia.bin \
  --adaptive-bin binarios_node_a_complementar/node_a_adaptativo.bin
```

O exemplo acima **não acessa hardware**. `--execute` é reservado a um ensaio piloto aprovado e à campanha posterior, pois aciona gravação de firmware e injeção de pulsos.

O executor anterior continua responsável pelos grupos, seleção dos binários já produzidos, gravação do aplicativo no endereço `0x10000`, confirmação de boot/mode, coleta das três portas e validação das saídas. Não gravar firmware na bancada antes de conferir porta USB, compatibilidade da versão do ESP-IDF e binário.

## 3. Sobre testes de Bus-Off

Este pacote não intensifica a injeção. O circuito atual comuta CAN_H e CAN_L temporariamente; **sem caracterização elétrica do circuito final, não é adequado aumentar automaticamente duração ou frequência dos pulsos**. Isso deverá ser tratado em um plano experimental separado. Os 36 runs oficiais permanecem intocados.
