# TCC II — Revisão do fluxo de interrupção por Bus-Off

**Data:** 19/10/2026  
**Entrada:** `fontes_busoff_TCC2.tar.gz`, com dois programas de host, fonte do Nó A, política e fonte/PIO do Pico.  
**Escopo:** revisão estática de seis fontes, correção **somente do executor Python** e testes de integração offline com portas seriais falsas. Nenhum microcontrolador foi acessado, nenhum firmware foi compilado ou gravado e nenhum pulso físico foi gerado.

## 1. Achados com evidência no código original

1. **P0 — parada bloqueada por arquivo fechado.** `executar_campanha_CAN_seguro.py` abre `control_events.jsonl` com `with` nas linhas 319–320. O tratamento `except` está **fora** desse `with` (linha 400). A primeira ação ao receber `BusOffDetected` com `in_progress=True` é `control_event(controller, 'STOP_REQUESTED', ...)` na linha 406. Nesse instante, `controller` já está fechado; o erro impede alcançar `pico.send('x')` da linha 407. Não é um risco hipotético: é consequência da estrutura do programa.
2. **P0 — falha serial impede confirmação e pode impedir STOP.** `SerialCapture._read()` marca o evento global `stop` ao encontrar exceção de leitura (linhas 172–179). `SerialCapture.send()` rejeita a escrita quando `stop.is_set()` (linhas 181–185), e `wait_abort_ack()` também interrompe a espera nessa condição (linhas 218–228). Uma falha de captura do Nó A ou B pode bloquear a tentativa lógica de interromper o Pico mesmo que sua própria porta ainda esteja acessível.
3. **P1 — confirmação insuficiente.** O código aguardava apenas qualquer `TEST_ABORTED`, sem verificar `run_id` nem obter `STATUS IDLE` do Pico. Uma mensagem atrasada de outro ensaio poderia ser confundida com a confirmação desejada.
4. **P1 — dados de ocorrência classificados apenas como falha.** O `qc.json` original registra `bus_off_detected=True`, mas `valid=False` e um motivo textual. Isso é adequado para impedir que o lote execute automaticamente outras runs, porém insuficiente para distinguir uma **observação de Bus-Off** de uma falha de instrumentação. O arquivo principal `analysis/avaliar_campanha_60_runs_TCC2.py` rejeita Bus-Off porque foi escrito para a campanha anterior, que não foi desenhada para esse evento.
5. **P1 — evento de borda após `TEST_END`.** O código original não fazia uma última drenagem de eventos Bus-Off nem verificava uma falha de leitura após a espera final de 0,8 s.
6. **Firmware Nó A:** `state_change_callback()` sinaliza Bus-Off (linhas 190–205) e a tarefa de monitoramento pode solicitar recuperação (linhas 348–361). Não há comprovação em hardware novo. A fila de eventos pode perder registros, acompanhados por `lost` nas amostras; o host utiliza `STATE_CHANGE` ou `SAMPLE` como gatilhos possíveis.
7. **Firmware Pico:** `x` chama `abort_test()`, que reconfigura a PIO para ocioso e emite `TEST_ABORTED` (linhas 217–249 e 453–462). Essa confirmação é **lógica**, não uma medição independente do nível de GP2 ou de corrente no CAN. O Pico não tem, nesse material, watchdog elétrico independente para falha do USB/host. A validação de `CFG` no próprio Pico permite mínimos inferiores aos três perfis permitidos pelo host (linhas 418–425), o que exige continuar bloqueando regimes não avaliados.

## 2. Alterações preparadas

**Arquivo alterado:** apenas `automacao_busoff_segura_v1/executar_campanha_CAN_seguro.py`.

- Mantém `control_events.jsonl` aberto durante o tratamento da exceção, inclusive STOP, e o fecha antes de criar o ZIP.
- Separa falha de leitura (`fault`) do evento de encerramento definitivo das capturas (`stop`) para manter a porta do Pico ouvindo enquanto o host tenta interromper a injeção.
- Envia `x` **antes** de tentar gravar o resultado da parada, evitando que uma falha do log impeça a tentativa.
- Valida `run_id` em `TEST_ABORTED`, consulta `STATUS` e procura `state=IDLE` com o mesmo `run_id`.
- Registra em `qc.json` `observation_status=BUS_OFF_OBSERVED_ABORTED`, `first_bus_off_event` (tempo local do Nó A, carimbo de captura host quando disponível) e timestamp de detecção no host. A run abortada continua com `valid=false` para **bloquear continuação automática do lote**, mas não deve ser descartada da análise específica de Bus-Off.
- Mantém a leitura de Node A e B por **2 segundos adicionais somente quando o Pico confirma `TEST_ABORTED` e `STATUS IDLE`**, para tentar capturar eventos de recuperação. Essa janela é tempo de captura, não garantia de recuperação.
- Verifica eventos pendentes após a janela final de aquisição e registra erros ao fechar os dispositivos.
- Não altera taxas do throttling, intensidade, largura nem intervalos dos pulsos; não altera os seis códigos-fonte originais na máquina do usuário.

## 3. Testes offline executados

**7 testes passaram** utilizando uma implementação falsa de `SerialCapture`, sem pyserial/USB. Foram verificados:

1. Entrada sintética `PASSIVE->BUS_OFF` leva a `x`, confirmação por run ID, `STATUS IDLE`, `qc.json` e ZIP.
2. Um erro sintético de captura leva à tentativa de STOP sem encerrar antecipadamente a captura do Pico.
3. Caminho normal de `TEST_END`, sem Bus-Off, permanece válido.
4. `SAMPLE state=BUS_OFF` é detectado; `BUS_OFF->ACTIVE` não é interpretado como nova entrada.
5. Erro intencional de escrita do registro de parada não impede `x`.
6. `KeyboardInterrupt` sintético tenta interromper o Pico.
7. Ausência sintética da confirmação `TEST_ABORTED` é explicitamente sinalizada, **sem presumir que o Pico parou**.

Os testes comprovam a lógica do executor **com portas falsas**, não a latência real do USB, a parada elétrica do GP2, a estabilidade da conexão ou a indução física de Bus-Off.

## 4. Limites e condições pendentes

- **Não executar um perfil destinado a induzir Bus-Off antes de validar eletricamente o estágio de injeção.** Não há osciloscópio nem multímetro disponíveis; a corrente e a forma de onda nos terminais CAN não foram medidas.
- Mesmo com o executor corrigido, `x` via USB **não é proteção autônoma**: queda do host, perda do USB, término abrupto do processo e defeitos de hardware podem impedir o STOP.
- Os timestamps locais do ESP32 e do Pico não são relógios diretamente sincronizados; para comparações temporais, preservar os timestamps do host junto aos locais.
- A telemetria de TEC após Bus-Off não deve ser tratada como prova de que o registrador necessariamente mostra 256; a confirmação de estado vem de `STATE_CHANGE`/`SAMPLE`.
- Ainda é necessário testar na bancada, sob condição elétrica caracterizada, o comportamento real de parada, atraso e recuperação. A aprovação dos 7 testes offline **não** autoriza por si só executar curtos mais intensos.
- Se o estudo físico for possível, o protocolo comparativo deverá ser pré-especificado, separando pilotos de repetição, mantendo os IDs e arquivos dos 60 ensaios intactos e tratando `BUS_OFF_OBSERVED_ABORTED` como desfecho experimental específico.

## 5. Aplicação e verificação sem hardware

Na raiz do repositório, após extrair o pacote em uma pasta separada:

```bash
patch -p1 --dry-run < /caminho/para/correcao_host_busoff.patch
```

Se o resultado não apontar conflito, **faça backup do arquivo atual** antes de aplicar o patch. Para verificar sem usar equipamentos:

```bash
python3 /caminho/para/testar_parada_busoff_offline.py
```

A operação `patch -p1` sem `--dry-run` altera o executor Python; não grava nenhum dispositivo. Antes de qualquer uso real, revisar o diff, obter confirmação da avaliação elétrica e ensaiar a lógica de STOP com o Pico sem conectar o estágio injetor ao barramento.
