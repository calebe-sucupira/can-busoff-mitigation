# Auditoria inicial do material recebido — 16/10/2026

**Material analisado:** `firmware.zip` e `analysis.zip`. Foram inspecionados os arquivos-fonte `firmware/pico-injector/main.c`, `injector.pio`, `firmware/node-a/main/main.c`, `throttle_policy.h`, `firmware/node-b/main/main.c`, `analysis/CAN_automacao_v1_5/executar_campanha_CAN.py`, os planos CSV e a documentação da campanha. Os arquivos brutos dos 36 ensaios **não fazem parte destes dois ZIPs**; este diagnóstico é do firmware e da automação, não uma reanálise das séries históricas.

## Constatações diretamente do código

1. **Pico parametrizável já existe.** Protocolo `CFG,<run>,<perfil>,<min>,<max>,<seed>,<duração>`, comandos `s`, `x` e `?`; gera `CONFIG_OK`, `NOISE_START`, `NOISE_END`, `TEST_END`. O GP2 comuta via PIO; o GP4 indica a fase de ruído. `injector.pio` usa `set pindirs, 1 [7]` seguido de `set pindirs, 0`, produzindo acionamento nominal de 8 ciclos a 1 MHz, sem aferição elétrica externa.
2. **Restrição atual do Pico é permissiva demais para novas intensidades não avaliadas:** `apply_command_line` aceita intervalo mínimo `1000 µs`, embora os três perfis oficiais usem mínimos de `40000`, `17500` e `9375 µs`, respectivamente. O script oficial, diferentemente do firmware do Pico, já obriga os limites de cada perfil; a automação complementar mantém esse bloqueio.
3. **Nó A:** CAN de 125 kbit/s, produtor de 10 ms, monitor de 1 ms, fila `xQueueCreate(1,...)` e `xQueueOverwrite`. A política do cabeçalho usa TEC `<96` (100 Hz), `96–127` (50 Hz), `>=128` (25 Hz). A condição de comparação é compilada por `ENABLE_THROTTLING`, cujo padrão no fonte recebido é **0**, não selecionável por serial na versão enviada.
4. **Detecção de Bus-Off está prevista:** `on_state_change` registra `STATE_CHANGE` e marca `controller_bus_off`; a tarefa de monitoramento tenta `twai_node_recover()` quando o estado é `TWAI_ERROR_BUS_OFF`. Portanto, uma nova campanha precisa registrar o evento e a recuperação caso ocorram, em vez de olhar apenas para o TEC amostrado.
5. **Nó B:** armazena recepções com sequência e instante local; registra estado/TEC/REC e eventos de erro. `xQueueSendFromISR(rx_queue,...)` não confere retorno; por isso, sem auditoria não é válido supor entrega total somente pela ausência de eventos de erro.
6. **Executor existente:** lê CSV, valida os perfis fixos, calcula pulsos ideais, confere versão do Pico, `CONFIG_OK`, boot do Nó A e `125000 bit/s`, aguarda fases, valida duração/pulsos e salva `.zip`, `.csv`, `.log`, `metadata.json` e `qc.json`. A verificação é de consistência básica, **não** de eficácia científica ou segurança elétrica.
7. **Firmware duplicado:** `analysis/CAN_automacao_v1_5/main.c` e `firmware/pico-injector/main.c` têm o mesmo código relevante; diferença observada apenas no caractere de fim de arquivo. Não precisamos trocar o firmware do Pico para parametrizar novos ensaios.
8. **Build atual:** há um único `firmware/node-a/build/node_a.bin` no ZIP, além do `flasher_args.json` indicando ESP32 e endereço de app `0x10000`. Não foi possível verificar o conteúdo dos dois binários correspondentes às políticas só com esta remessa.

## Verificações executadas localmente

- Compilação sintática via `ast.parse` dos scripts Python extraídos: **aprovada**.
- `executar_lote.py --dry-run`: **aprovado** (seis pilotos, sem hardware).
- `executar_campanha_CAN.py --dry-run`: **aprovado** (36 ensaios, sem hardware).
- Orquestrador complementar `--dry-run` com exemplo de dois grupos: **aprovado** (sem hardware).

Não executei compilação de C com ESP-IDF ou Pico SDK nesta sessão, não gravei nenhum dispositivo e não realizei testes físicos.

## Decisão recomendada

A automação já resolve a parametrização do Pico. O complemento útil é **automatizar a escolha e gravação de binários previamente compilados para o Nó A**, mantendo intacto o firmware usado na campanha oficial. Como não há osciloscópio para validar a condição elétrica, **não planejar nem iniciar automaticamente uma busca por Bus-Off aumentando a densidade de pulsos**. Primeiro confirmar os dois binários e os parâmetros admissíveis com orientação do projeto; depois validar o orquestrador com condições já conhecidas. Os ensaios oficiais (153–188) não devem ser repetidos nem substituídos só para testar o novo script.
