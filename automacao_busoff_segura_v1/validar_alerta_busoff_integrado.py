#!/usr/bin/env python3
"""Testa no computador a deteccao BUS_OFF e, opcionalmente, envia x ao Pico IDLE.

O BUS_OFF e sintetico: nao consulta o No A, nao inicia ensaio, nao gera pulsos.
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from executar_campanha_CAN_seguro import bus_off_detected, parse_data_line

SYNTHETIC_ENTRY = 'DATA,100,STATE_CHANGE,-1,-1,-1,-,-,PASSIVE->BUS_OFF'
SYNTHETIC_RECOVERY = 'DATA,101,STATE_CHANGE,-1,-1,-1,-,-,BUS_OFF->ACTIVE'
SYNTHETIC_SAMPLE = 'DATA,102,SAMPLE,-1,256,0,BUS_OFF,CRITICAL,tec_peak=256'


def get_event(port, desired, timeout=5):
    limit = time.monotonic() + timeout
    while time.monotonic() < limit:
        payload = port.readline()
        if not payload:
            continue
        line = payload.decode('utf-8', errors='replace').strip()
        item = parse_data_line(line)
        if item and item['event'] == desired:
            return item
    raise TimeoutError(f'Nao houve confirmacao {desired} dentro de {timeout} s.')


def send(port, command):
    port.write(command)
    port.flush()


def run(port_name, execute):
    entry = parse_data_line(SYNTHETIC_ENTRY)
    recovery = parse_data_line(SYNTHETIC_RECOVERY)
    sample = parse_data_line(SYNTHETIC_SAMPLE)
    if not all((entry, recovery, sample)):
        raise RuntimeError('Falha ao interpretar eventos de teste.')
    if not bus_off_detected(entry) or bus_off_detected(recovery) or not bus_off_detected(sample):
        raise RuntimeError('Deteccao de BUS_OFF falhou; nenhum comando enviado.')
    print('DETECTOR: entrada em BUS_OFF reconhecida; recuperacao ignorada; SAMPLE BUS_OFF reconhecido.')
    print('EVENTO DE TESTE SINTETICO: NAO ocorreu Bus-Off real no No A.')
    print('Sequencia fisica permitida: ? -> STATUS(IDLE) -> x -> TEST_ABORTED -> ? -> STATUS(IDLE).')
    print('Nao envia CFG nem s. Nao grava firmwares. Nao acessa No A ou No B.')
    if not execute:
        print('SIMULACAO CONCLUIDA: nenhuma porta serial foi aberta.')
        return 0

    import serial
    with serial.Serial(port_name, 115200, timeout=0.1, write_timeout=1,
                       dsrdtr=False, rtscts=False) as pico:
        pico.dtr = True
        pico.rts = False
        time.sleep(2)
        pico.reset_input_buffer()
        send(pico, b'?')
        initial = get_event(pico, 'STATUS')
        print('STATUS inicial:', initial['raw_detail'])
        fields = initial['detail']
        if fields.get('state') != 'IDLE' or fields.get('firmware') != 'pico-param-v1.5':
            raise RuntimeError('Pico nao confirmou firmware esperado e IDLE; nenhum x enviado.')
        last_run = fields.get('run_id')
        if not last_run:
            raise RuntimeError('STATUS sem run_id; nenhum x enviado.')
        # O evento sintetico passa pelo detector real antes do envio do STOP.
        if not bus_off_detected(entry):
            raise RuntimeError('Evento sintetico nao disparou o detector.')
        send(pico, b'x')
        stopped = get_event(pico, 'TEST_ABORTED')
        print('TEST_ABORTED:', stopped['raw_detail'])
        if stopped['detail'].get('run_id') != last_run:
            raise RuntimeError('Confirmacao TEST_ABORTED nao corresponde ao ultimo run.')
        send(pico, b'?')
        final = get_event(pico, 'STATUS')
        print('STATUS final:', final['raw_detail'])
        if final['detail'].get('state') != 'IDLE':
            raise RuntimeError('Pico nao confirmou IDLE apos o comando x.')
        report = {
            'test': 'synthetic_busoff_event_to_idle_pico_stop',
            'time_utc': datetime.now(timezone.utc).isoformat(),
            'port': port_name,
            'trigger': 'synthetic_STATE_CHANGE_PASSIVE_to_BUS_OFF',
            'bus_off_real': False,
            'pulse_start_command_sent': False,
            'pico_stop_sent': True,
            'pico_ack': stopped['raw_detail'],
            'final_state': final['detail'].get('state'),
            'electrical_output_verified': False,
        }
        folder = Path(__file__).resolve().parent / 'validacao_busoff_sintetico'
        folder.mkdir(exist_ok=True)
        path = folder / ('teste_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.json')
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('INTEGRACAO LOGICA APROVADA: evento sintetico -> detector -> comando x -> confirmacao do Pico.')
        print('Limite: nao valida parada automatica sob Bus-Off real nem condicao eletrica do GP2.')
        print('RELATORIO:', path)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--port', default='/dev/ttyACM1')
    ap.add_argument('--execute', action='store_true')
    args = ap.parse_args()
    try:
        return run(args.port, args.execute)
    except Exception as exc:
        print(f'FALHOU: {type(exc).__name__}: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
