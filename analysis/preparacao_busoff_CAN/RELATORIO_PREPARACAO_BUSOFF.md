# Auditoria documental de preparacao do estudo Bus-Off

> Gerado automaticamente em 2026-10-19 20:43 UTC. Nenhum dispositivo acessado e nenhum ensaio executado.

## Escopo e limites

Foram lidos **25 arquivos-fonte/copies em arquivos ZIP** e encontradas **528 ocorrencias textuais**.
Esta verificacao usa expressoes regulares: **nao executa o firmware nem comprova** que o Pico realmente interrompe um curto em Bus-Off.
A ausencia de uma marca pode ser falso negativo, especialmente quando um arquivo esta fora do repositorio.

## Indicadores no codigo

| Item pesquisado | Resultado textual |
|---|---|
| no_a_marcas_busoff | LOCALIZADO |
| no_a_marcas_recuperacao | LOCALIZADO |
| pico_marcas_stop | LOCALIZADO |
| pico_marcas_saida | LOCALIZADO |
| host_marcas_busoff | LOCALIZADO |
| host_marcas_stop | LOCALIZADO |
| host_marcas_confirmacao | LOCALIZADO |
| host_marcas_timeout | LOCALIZADO |
| host_marcas_captura | LOCALIZADO |

Arquivos Python com marcas textuais de **BUS_OFF + STOP + confirmacao** no mesmo arquivo (ainda sem prova de fluxo):

- `automacao_busoff_segura_v1/executar_campanha_CAN_seguro.py`
- `automacao_busoff_segura_v1/validar_alerta_busoff_integrado.py`

## Exemplos para revisao manual

| Categoria | Local | Trecho |
|---|---|---|
| A_EVENTO_BUSOFF | `analysis/avaliar_campanha_60_runs_TCC2.py:165` | `busoff = sum('BUS_OFF' in r['event'] or 'BUS_OFF' in r['detail'] for r in a_csv)` |
| A_EVENTO_BUSOFF | `analysis/avaliar_campanha_60_runs_TCC2.py:166` | `check(busoff == 0, f'Run {run}: BUS_OFF detectado (reavaliar metricas)')` |
| A_EVENTO_BUSOFF | `automacao_busoff_segura_v1/executar_campanha_CAN_seguro.py:2` | `"""Executa planos CAN no Pico; monitora estado BUS_OFF no Node A e interrompe via x.` |
| A_EVENTO_BUSOFF | `automacao_busoff_segura_v1/executar_campanha_CAN_seguro.py:194` | `"""Detecta somente a ENTRADA em BUS_OFF, nao a recuperacao."""` |
| B_ESTADO_E_RECUPERACAO | `automacao_busoff_segura_v1/validar_alerta_busoff_integrado.py:39` | `recovery = parse_data_line(SYNTHETIC_RECOVERY)` |
| B_ESTADO_E_RECUPERACAO | `automacao_busoff_segura_v1/validar_alerta_busoff_integrado.py:41` | `if not all((entry, recovery, sample)):` |
| B_ESTADO_E_RECUPERACAO | `automacao_busoff_segura_v1/validar_alerta_busoff_integrado.py:43` | `if not bus_off_detected(entry) or bus_off_detected(recovery) or not bus_off_detected(sample):` |
| B_ESTADO_E_RECUPERACAO | `firmware/node-a/main/main.c:82` | `} recovery;` |
| C_DETECTOR_HOST | `analysis/avaliar_campanha_60_runs_TCC2.py:149` | `states = [r for r in a_csv if r['event']=='STATE_CHANGE']` |
| C_DETECTOR_HOST | `analysis/avaliar_campanha_60_runs_TCC2.py:165` | `busoff = sum('BUS_OFF' in r['event'] or 'BUS_OFF' in r['detail'] for r in a_csv)` |
| C_DETECTOR_HOST | `analysis/avaliar_campanha_60_runs_TCC2.py:166` | `check(busoff == 0, f'Run {run}: BUS_OFF detectado (reavaliar metricas)')` |
| C_DETECTOR_HOST | `analysis/capture.py:74` | `"ERROR", "STATE_CHANGE", "TX_FAILED",` |
| D_COMANDO_STOP_PICO | `analysis/CAN_automacao_v1_5/executar_campanha_CAN.py:127` | `def __init__(self, name, port, baud, folder, stop):` |
| D_COMANDO_STOP_PICO | `analysis/CAN_automacao_v1_5/executar_campanha_CAN.py:130` | `self.stop = stop` |
| D_COMANDO_STOP_PICO | `analysis/CAN_automacao_v1_5/executar_campanha_CAN.py:154` | `while not self.stop.is_set():` |
| D_COMANDO_STOP_PICO | `analysis/CAN_automacao_v1_5/executar_campanha_CAN.py:172` | `if not self.stop.is_set():` |
| E_COMPROVACAO_PARADA | `analysis/CAN_automacao_v1_5/executar_campanha_CAN.py:201` | `if item['event'] in {'CONFIG_ERROR', 'TEST_ABORTED'}:` |
| E_COMPROVACAO_PARADA | `analysis/CAN_automacao_v1_5/executar_campanha_CAN.py:284` | `status = wait_event(pico, 'STATUS', timeout=6, stop=stop)` |
| E_COMPROVACAO_PARADA | `analysis/CAN_automacao_v1_5/executar_campanha_CAN.py:285` | `check_fields(status, {'firmware': VERSION, 'state': 'IDLE'})` |
| E_COMPROVACAO_PARADA | `analysis/CAN_automacao_v1_5/executar_campanha_CAN.py:320` | `('NOISE_END', plan.duration + 9), ('TEST_END', 9),` |
| F_FALHAS_SERIAL_TIMEOUT | `analysis/CAN_automacao_v1_5/executar_campanha_CAN.py:137` | `self.device.timeout = 0.1` |
| F_FALHAS_SERIAL_TIMEOUT | `analysis/CAN_automacao_v1_5/executar_campanha_CAN.py:138` | `self.device.write_timeout = 1` |
| F_FALHAS_SERIAL_TIMEOUT | `analysis/CAN_automacao_v1_5/executar_campanha_CAN.py:187` | `self.thread.join(timeout=2.0)` |
| F_FALHAS_SERIAL_TIMEOUT | `analysis/CAN_automacao_v1_5/executar_campanha_CAN.py:192` | `def wait_event(pico, event, timeout, stop):` |
| G_CAPTURA_AUDITAVEL | `analysis/CAN_automacao_v1_5/executar_campanha_CAN.py:268` | `(folder / 'metadata.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encod` |
| G_CAPTURA_AUDITAVEL | `analysis/CAN_automacao_v1_5/executar_campanha_CAN.py:276` | `with (folder / 'control_events.jsonl').open('w', encoding='utf-8', buffering=1) as controller:` |
| G_CAPTURA_AUDITAVEL | `analysis/CAN_automacao_v1_5/executar_campanha_CAN.py:302` | `a_log = (folder / 'node_a.log').read_text(encoding='utf-8', errors='replace')` |
| G_CAPTURA_AUDITAVEL | `analysis/CAN_automacao_v1_5/executar_campanha_CAN.py:372` | `a_log = (folder / 'node_a.log').read_text(encoding='utf-8', errors='replace')` |
| H_MONITOR_PROG_TEC | `analysis/CAN_automacao_v1_5/executar_campanha_CAN.py:153` | `csv_file.write('timestamp_us,node,event,sequence,tec,rec,state,mode,detail\n')` |
| H_MONITOR_PROG_TEC | `analysis/CAN_automacao_v1_5/executar_campanha_CAN.py:377` | `samples = count_events(folder / f'{node}.log', 'SAMPLE')` |
| H_MONITOR_PROG_TEC | `analysis/CAN_automacao_v1_5/executar_campanha_CAN.py:380` | `raise RuntimeError(f'{node}: captura sem SAMPLE suficiente ({samples}).')` |
| H_MONITOR_PROG_TEC | `analysis/CAN_automacao_v1_5/executar_lote.py:134` | `csv_file.write('timestamp_us,node,event,sequence,tec,rec,state,mode,detail\n')` |

## Pontos que exigem comprovacao antes de qualquer novo ensaio fisico

1. Distinguir **entrada** em Bus-Off de um estado historico ou transicao de recuperacao. Os eventos devem ser datados usando o relogio de captura do host e o relogio local do dispositivo, sem presumir sincronismo em microssegundos.
2. Demonstrar no **fluxo real da automacao** que a entrada em Bus-Off do No A dispara parada do Pico e confirmacao (`TEST_ABORTED` e/ou `STATUS IDLE`). A presenca de palavras nos arquivos nao constitui prova.
3. Confirmar que **falha serial, timeout, Ctrl+C e perda do No A** nao mantem o gerador ativo. `x` via USB e parada logica; so nao constituem protecao eletrica independente.
4. Verificar saida desligada no inicio e no final, falha segura apos reset, e tratamento de comando desconhecido no firmware Pico. Exige revisao de circuito/firmware; nao pode ser verificado somente por logs.
5. Preservar brutos dos tres dispositivos, marcadores de estado, `TEC`, eventos de recepcao, motivo da parada e configuracao. **Nao descartar eventos apos o primeiro Bus-Off**; preservar janela de recuperacao, se eletricamente admissivel.
6. **Nenhum novo perfil de pulso esta autorizado por esta auditoria**. A corrente diferencial nao foi medida; sem isso nao se infere seguranca de uma intensidade intermediaria.

## Proximos artefatos a conferir

- `diagnostico.json`: resultados de verificacao textual e possiveis erros de leitura;
- `evidencias_codigo.csv`: arquivo, linha e fragmento de cada referencia no fonte;
- `inventario_fontes.csv`: lista de fontes e hashes.

