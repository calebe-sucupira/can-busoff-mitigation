#!/usr/bin/env python3
"""Diagnostico do comando x durante injecao BAIXO conhecida (nao e STOP de emergencia).

Inicia um ensaio com baseline de 5 s e injecao de 5 s. Apos receber
NOISE_START, aguarda 0,25 s e envia x. Falhas de host/USB podem permitir
que a injecao continue por toda a duracao programada (5 s).
Nenhuma saida eletrica e medida por este programa.
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

RUN_ID = 900002  # Apenas diagnostico; nao entra em data/raw ou data/zips.
PROFILE = 'BAIXO'
SEED = 'EA125C50'
CFG = f'CFG,{RUN_ID},{PROFILE},40000,60000,{SEED},5\n'
EXPECTED_PULSES_FULL_RUN = 100
POST_NOISE_START_DELAY_S = 0.25


def parse_event(raw):
    line = raw.decode('utf-8', errors='replace').strip()
    if not line.startswith('DATA,'):
        return None
    parts = line.split(',', 8)
    if len(parts) != 9:
        return None
    return {'timestamp_us': parts[1], 'event': parts[2], 'detail': parts[8]}


def read_for(port, wanted, seconds, events):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        raw = port.readline()
        if not raw:
            continue
        event = parse_event(raw)
        if event is None:
            continue
        events.append(event)
        kind = event['event']
        if kind == 'CONFIG_ERROR':
            raise RuntimeError(f'Pico rejeitou configuracao: {event["detail"]}')
        if kind == 'NOISE_END' and wanted != 'NOISE_END':
            raise RuntimeError('Injecao terminou antes da confirmacao de STOP.')
        if kind == 'TEST_END' and wanted != 'TEST_END':
            raise RuntimeError('Ensaio concluiu normalmente antes de STOP.')
        if kind == wanted:
            return event
    raise TimeoutError(f'Nao recebi {wanted} em {seconds:g} s.')


def parse_details(detail):
    result = {}
    for part in detail.split(';'):
        if '=' in part:
            k, v = part.split('=', 1)
            result[k] = v
    return result


def check(event, **expected):
    got = parse_details(event['detail'])
    for field, value in expected.items():
        if got.get(field) != str(value):
            raise RuntimeError(
                f'{event["event"]}: {field}={got.get(field)!r}, esperado {value!r}'
            )
    return got


def send(port, command):
    port.write(command)
    port.flush()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--port', default='/dev/ttyACM1')
    ap.add_argument('--execute', action='store_true')
    args = ap.parse_args()

    print(f'PORTA: {args.port}')
    print('Diagnostico: run=900002 | BAIXO 40000-60000 us | injecao programada=5 s')
    print('Sequencia: STATUS -> CFG -> s -> TEST_START -> NOISE_START -> x -> TEST_ABORTED -> STATUS')
    print('STOP solicitado ~0,25 s apos NOISE_START, esperando 1 a 99 pulsos.')
    if not args.execute:
        print('SIMULACAO CONCLUIDA. Nenhuma porta foi aberta e nenhum comando enviado.')
        return 0

    import serial
    events = []
    started = False
    confirmed_stop = False
    succeeded = False
    problem = None
    started_monotonic = None
    stop_requested_monotonic = None
    dest_dir = Path(__file__).resolve().parent / 'validacao_stop_injecao'
    dest_dir.mkdir(exist_ok=True)

    try:
        with serial.Serial(args.port, 115200, timeout=0.05, write_timeout=0.5,
                           dsrdtr=False, rtscts=False) as port:
            port.dtr = True
            port.rts = False
            time.sleep(2)
            port.reset_input_buffer()
            try:
                send(port, b'?')
                initial = read_for(port, 'STATUS', 2.0, events)
                print('STATUS inicial:', initial['detail'])
                check(initial, firmware='pico-param-v1.5', state='IDLE')

                send(port, CFG.encode('ascii'))
                configured = read_for(port, 'CONFIG_OK', 1.5, events)
                check(configured, run_id=RUN_ID, profile=PROFILE,
                      interval_min_us=40000, interval_max_us=60000,
                      seed='0xea125c50', injection_us=5000000)
                print('CONFIG_OK:', configured['detail'])

                started = True
                started_monotonic = time.monotonic()
                send(port, b's')
                start_ev = read_for(port, 'TEST_START', 1.5, events)
                check(start_ev, run_id=RUN_ID, profile=PROFILE,
                      baseline_us=5000000, injection_us=5000000)
                print('TEST_START:', start_ev['detail'])

                noise = read_for(port, 'NOISE_START', 6.5, events)
                check(noise, run_id=RUN_ID, profile=PROFILE,
                      pulse_us=8, interval_min_us=40000, interval_max_us=60000)
                print('NOISE_START:', noise['detail'])
                time.sleep(POST_NOISE_START_DELAY_S)
                stop_requested_monotonic = time.monotonic()
                send(port, b'x')
                ack = read_for(port, 'TEST_ABORTED', 2.0, events)
                info = check(ack, run_id=RUN_ID)
                print('TEST_ABORTED:', ack['detail'])
                confirmed_stop = True

                pulses = int(info.get('pulses', '-1'))
                if not 1 <= pulses < EXPECTED_PULSES_FULL_RUN:
                    raise RuntimeError(
                        f'Pulsos={pulses}. Esperado >=1 e <{EXPECTED_PULSES_FULL_RUN}.'
                    )
                send(port, b'?')
                status = read_for(port, 'STATUS', 1.5, events)
                check(status, firmware='pico-param-v1.5', state='IDLE', run_id=RUN_ID)
                print('STATUS final:', status['detail'])
                succeeded = True
                print(f'PASSOU: STOP durante INJECAO, pulsos={pulses}, IDLE confirmado.')
                print('Nao comprova a condicao eletrica de GP2 e nao e STOP de emergencia.')
            finally:
                if started and not confirmed_stop:
                    try:
                        send(port, b'x')
                        print('STOP adicional solicitado por precaucao. CONFIRA A BANCADA.')
                    except Exception as exc:
                        print(f'ATENCAO: falha ao solicitar STOP: {exc}')
    except BaseException as exc:
        problem = f'{type(exc).__name__}: {exc}'
        print('FALHOU:', problem)
    finally:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        report = {
            'test': 'stop_during_injection', 'diagnostic_run': RUN_ID,
            'port': args.port, 'profile': PROFILE,
            'parameter_interval_min_us': 40000, 'parameter_interval_max_us': 60000,
            'injection_duration_s': 5, 'stop_delay_after_noise_start_s': POST_NOISE_START_DELAY_S,
            'events': events, 'started': started, 'confirmed_stop': confirmed_stop,
            'succeeded': succeeded, 'error': problem,
            'start_host_monotonic': started_monotonic,
            'stop_host_monotonic': stop_requested_monotonic,
            'time_utc': datetime.now(timezone.utc).isoformat()
        }
        target = dest_dir / f'teste_{stamp}.json'
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('RELATORIO:', target)
    return 0 if succeeded else 1


if __name__ == '__main__':
    raise SystemExit(main())
