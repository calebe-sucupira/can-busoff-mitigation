# Campanha PHASE20 integral — referência × adaptativo

## Escopo

**Um único comando inicia todos os 40 ensaios da campanha principal**, desde que a condição elétrica da bancada esteja aprovada e a execução seja **supervisionada presencialmente**. Os dois pilotos já realizados permanecem intactos:

- Run 300: REFERENCIA, Bus-Off, ~21,71 s (piloto exploratorio, fora dos 40).
- Run 303: ADAPTATIVO, Bus-Off, ~8,47 s (piloto exploratorio, fora dos 40).
- Novos Runs **304–343**: **20 REFERENCIA + 20 ADAPTATIVO**.
- Ao concluir: **40 resultados para comparacao** + **2 pilotos documentados separadamente** = 42 ZIPs no estudo.
- Runs 301 e 302 eram entradas não executadas de um plano piloto antigo e **não serão inventados nem reutilizados**.

Em uma única invocação, o orquestrador percorre 8 blocos: ADAPTATIVO 5, REFERENCIA 5, ADAPTATIVO 5, REFERENCIA 5, ADAPTATIVO 5, REFERENCIA 5, ADAPTATIVO 5, REFERENCIA 5. O firmware de Nó A é gravado automaticamente quando o bloco muda. No primeiro bloco presume que o Nó A ainda está no modo ADAPTATIVO (último firmware gravado pelo usuário); **o executor verifica `throttling=1` no boot antes de gerar o primeiro pulso**. Use `--flash-first` caso queira que o programa também grave o primeiro bloco.

A semente PHASE20 é preservada, mas **não muda a sequência de temporização neste perfil**. Portanto, as repetições não são amostras com sementes temporais distintas e não têm sincronização física de fase entre Pico e CAN.

## Instalação

Na raiz do repositório:

```bash
cd ~/Documentos/tcc/can-busoff-mitigation
unzip ~/Downloads/campanha_integral_phase20_TCC_CAN_2026-10-20.zip -d testes_busoff/pico_fase
```

O pacote contém somente arquivos **novos**, sem substituir `executar_campanha_CAN_phase20.py`.

## Verificações sem hardware

```bash
python3 testes_busoff/pico_fase/testar_campanha_integral_offline.py
python3 testes_busoff/pico_fase/executar_campanha_integral_phase20.py --dry-run
```

Ambas dispensam Pico/ESP32, sem injeção. O código recusa executar se o executor PHASE20 tiver sido modificado desde o auditado (`sha256` conferido).

## Executar toda a coleta em um comando

**Condição prévia indispensável:** a adequação elétrica do circuito para injeções sucessivas foi avaliada por pessoa competente. Não há medição elétrica/termal nesta automação; um teste bem-sucedido de Bus-Off com desligamento lógico **não demonstra** que 40 ensaios sucessivos sejam seguros. Não execute sem supervisão. Mantenha acesso à desenergização da bancada e interrompa ao primeiro sinal físico anormal. Pausa de 60 s é apenas operacional; **não certifica resfriamento**.

Se ESP-IDF não estiver no PATH, inicialize o ambiente como já faz normalmente antes de usar `idf.py`:

```bash
. "$HOME/esp/esp-idf/export.sh"
```

Execute **uma vez**, após a verificação de segurança:

```bash
python3 testes_busoff/pico_fase/executar_campanha_integral_phase20.py --execute
```

O programa usa por padrão `/dev/ttyUSB0` (Nó A), `/dev/ttyACM0` (Nó B), `/dev/ttyACM1` (Pico) e dados em `data/busoff_estudo_2026/`.

Em cada Bus-Off, o executor salva ZIP com `qc.json` indicando `BUS_OFF_OBSERVED_ABORTED` e retorna. O orquestrador **não considera o evento como falha operacional** se conseguir verificar:

- `TEST_ABORTED` do run correto e `STATUS IDLE` no log do Pico.
- Entrada em BUS_OFF documentada no Nó A, seguida de `BUS_OFF->ACTIVE`.
- Amostras `ACTIVE` e transmissões bem-sucedidas depois da recuperação.
- ZIP íntegro, run e política corretos, nenhum erro de captura séria.

Sem Bus-Off, só aceita `FULL_DURATION_VERIFIED` e `TEST_END` do run correto, registros em ACTIVE ao término e TX_SUCCESS. Se qualquer condição não for atendida, **interrompe o lote sem repetir automaticamente ou pular o run**, preservando tudo que foi salvo. O STOP serial **não é um intertravamento elétrico independente**.

O programa impõe uma espera padrão de 60 s entre ensaios, sem prometer segurança térmica. Tempo real depende de quando o Bus-Off ocorre, das gravações e das pausas.

## Registro, falhas e retomada

- ZIPs: `data/busoff_estudo_2026/zips/run_NNN_injection.zip`.
- Logs brutos: `data/busoff_estudo_2026/raw/run_NNN_injection/`.
- Journal append-only: `data/busoff_estudo_2026/campanha_integral_phase20_journal.jsonl`.
- Os arquivos existentes de 300 e 303 são **verificados e nunca sobrescritos**.
- Se interrompido por falha, examine a bancada e os dados. `--resume` pula apenas ZIPs concluídos que tenham comprovação dos critérios acima; não sobrescreve um run parcialmente coletado. Se aparecer arquivo de run parcial, investigue antes de atribuir um **novo ID**.
- Se `idf.py` falhar, **nenhum pulso será enviado** ao passar para o modo correspondente.

## Interpretação científica

O objetivo **não é provar prevenção completa de Bus-Off**. O trabalho investiga **mitigação de risco/comportamento** sob perturbação: ocorrência de Bus-Off, tempo até ele ou censura aos 40 s, curvas TEC, intervalos Error Warning e Error Passive, taxa de envio/recepção e supressão de submissões pelo throttling. Ao comparar, normalizar contagens pela duração efetiva da injeção (runs abortados duram menos), não interpretar diferença de totais como efeito de política sem ajuste temporal e reconhecer que o perfil não sincroniza pulsos diretamente aos quadros CAN.

### Garantias e limites da validação do pacote

Foram feitos **9 testes offline** do orquestrador: plano de 40 novos/20×20, Bus-Off aceito com parada e recuperação, STOP sem ACK, recuperação ausente, múltiplos Bus-Off inesperados, duração completa, troca de firmware num único processo, fail-stop e retomada. O verificador também aceitou o **ZIP real do Run 303**. **A sequência integral não foi executada na bancada aqui.**
