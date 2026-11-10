# CAN — preparação para avaliação de Bus-Off (versão de segurança 1)

## Estado desta entrega

Esta pasta é **nova**. Não substitua `automacao_complementar_CAN_TCC2_v2/`, os códigos originais do Pico nem os binários do Nó A. `ALTO_EXT` não foi implementado, autorizado nem validado.

Revisei o firmware recebido (`firmware.zip`, Pico `main.c` de 15/10/2026): **o comando `x` já existe**. A máquina de estados PIO é reinicializada por `abort_test()`, e o Pico informa `TEST_ABORTED`. Logo, não foi preciso adicionar um comando STOP ao protocolo.

A automação oficial complementar só usa `x` em falhas da execução e não acompanha `STATE_CHANGE` do Nó A. A versão `*_segura.py` acompanha as mensagens de entrada em `BUS_OFF` e solicita a parada via `x`. Ela espera, no máximo por 3 segundos, uma confirmação `TEST_ABORTED`; se essa confirmação não chegar, marca a ocorrência como não confirmada. Um ensaio abortado será classificado como **incompleto**, preservando logs e ZIP. O programa interrompe o lote ao detectar falha e **não tenta repetir o teste automaticamente**.

## Validação no computador (NÃO acessa hardware)

```bash
cd /home/calebe/Documentos/tcc/can-busoff-mitigation/automacao_busoff_segura_v1
python3 teste_simulado_segurança.py
python3 validar_stop_pico_idle.py
```

## Próximo teste na bancada: STOP com Pico ocioso

Execute somente quando **não houver campanha ativa**, o Pico estiver conectado a `/dev/ttyACM1` e nenhuma outra aplicação tiver aberto essa porta:

```bash
cd /home/calebe/Documentos/tcc/can-busoff-mitigation/automacao_busoff_segura_v1
python3 validar_stop_pico_idle.py --port /dev/ttyACM1 --execute
```

O script apenas envia `?`, depois `x`, depois `?`. **Ele nunca envia `s`, nem `CFG`, portanto não começa a injeção.** Exige `STATUS state=IDLE` antes de enviar o `x`; confirma `TEST_ABORTED` e `STATUS state=IDLE`. Se não houver confirmação, não assuma que a saída está fisicamente segura.

## Plano seguro: apenas simulação

Abaixo é exemplo **somente de simulação**; NÃO acrescente `--execute` enquanto não terminarmos a validação e o plano científico.

```bash
python3 orquestrar_campanha_segura.py \
  --plan ../automacao_complementar_CAN_TCC2_v2/plano_exploratorio_CAN_ALTO_runs_191_196.csv \
  --reference-bin ../automacao_complementar_CAN_TCC2_v2/binarios_node_a_complementar/node_a_referencia.bin \
  --adaptive-bin ../automacao_complementar_CAN_TCC2_v2/binarios_node_a_complementar/node_a_adaptativo.bin \
  --node-a /dev/ttyUSB0 --node-b /dev/ttyACM0 --pico /dev/ttyACM1 \
  --output ../data --from-run 191 --to-run 192
```

Esse exemplo usa IDs já executados **somente para simular**. Não os reutilize em um ensaio real. A pasta `data/` continua sendo a da raiz do repositório. O executor rejeita perfis fora dos três originais.

## Pico: correção candidata — NÃO gravar por enquanto

`pico_injector_candidato/` preserva a lógica e os parâmetros originais, mas altera a sequência de desativação no helper `injector_set_high_z()` para desabilitar a máquina de estados PIO **antes** de reconfigurar a direção do GP2. O SDK recomenda configurar direção e valores de pinos com a máquina parada. Consulte `mudanca_revisao_PIO.diff`.

Esta alteração foi apenas inspecionada estaticamente. **Não foi compilada nem validada em um RP2040 real.** O dispositivo está atualmente executando o firmware de 15/10/2026, que já responde a `x`; mantenha-o até avaliarmos a correção em condições controladas. Mesmo após atualização, sem instrumentação não poderemos afirmar que a saída ficou em alta impedância em todos os instantes de comutação.

## Limites e riscos

- O 2N2222 comuta diretamente CAN_H e CAN_L. O SN65HVD230 tem proteções, mas isso **não valida eletricamente** maior duração/frequência de curtos. Faltam aferições reais de forma de onda, pico de corrente, dissipação e saída GP2.
- `x` é uma **parada lógica via USB**: não é parada de emergência independente. Pode atrasar ou falhar se houver perda da comunicação, travamento do host ou Pico, ou falha elétrica. O Pico também tem limite local de duração, mas a injeção pode prosseguir até esse limite caso o computador falhe.
- A detecção depende de eventos seriais `STATE_CHANGE`/`SAMPLE`; uma linha perdida pode atrasar ou impedir a detecção. Uma entrada em Bus-Off pode ser transitória porque o Nó A solicita recuperação.
- Não está autorizado aumentar a frequência, elevar largura de pulso ou implementar `ALTO_EXT` só com essas proteções de software.
- Nenhuma mudança nas duas PCBs nem nas conexões elétricas foi proposta.

## Metodologia

Essas ferramentas auxiliares de segurança não substituem o relato dos procedimentos reais. Se um ensaio atingir Bus-Off e for interrompido, seus dados são apropriados para estudar **ocorrência e tempo até Bus-Off**, mas não são diretamente comparáveis aos ensaios completos de 40 segundos em todas as métricas.

## Verificações já realizadas (fora da bancada)

- Sintaxe de ambos os executores e do teste da porta.
- Cinco testes unitários para entrada em Bus-Off, saída do estado, amostras, espera interrompida e confirmação do Pico.
- Simulação do orquestrador com o plano dos Runs 191–192 e perfis oficiais (nenhuma porta acessada).

**Não realizados:** compilação do Pico candidato, validação física da saída GP2, teste completo de parada automática sob injeção, calibração elétrica de perfil novo.
