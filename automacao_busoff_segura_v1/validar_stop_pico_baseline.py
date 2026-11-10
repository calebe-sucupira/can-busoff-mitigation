#!/usr/bin/env python3
"""Teste controlado: inicia ensaio Pico e solicita STOP durante baseline de 5 s.

Nao e certificacao eletrica do GP2; se host/USB falhar, perfil BAIXO
configurado pode iniciar e operar por ate 5 s apos a baseline.
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

RUN_ID = 900001  # Diagnostico; nao pertence a campanha cientifica.
PROFILE = 'BAIXO'
SEED = 'EA125C50'
CFG = f'CFG,{RUN_ID},{PROFILE},40000,60000,{SEED},5\n'


def event_from(raw):
    line = raw.decode('utf-8', errors='replace').strip()
    if not line.startswith('DATA,'):
        return None
    parts = line.split(',', 8)
    if len(parts) != 9:
        return None
    return {'timestamp_us': parts[1], 'event': parts[2], 'detail': parts[8]}


def next_event(port, wanted, timeout, seen):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = port.readline()
        if not raw:
            continue
        event = event_from(raw)
        if event is None:
            continue
        seen.append(event)
        if event['event'] == 'NOISE_START':
            raise RuntimeError('ATENCAO: Pico anunciou NOISE_START; STOP sera solicitado.')
        if event['event'] == 'CONFIG_ERROR':
            raise RuntimeError('Pico rejeitou configuracao: ' + event['detail'])
        if event['event'] == wanted:
            return event
    raise TimeoutError('Sem resposta do Pico para ' + wanted)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', default='/dev/ttyACM1')
    p.add_argument('--execute', action='store_true')
    args = p.parse_args()
    print('PORTA:', args.port)
    print('Config: BAIXO, intervalo 40000-60000 us, injecao programada 5 s, run diagnostico 900001')
    print('Sequencia: STATUS -> CFG -> s -> TEST_START -> x -> TEST_ABORTED -> STATUS')
    if not args.execute:
        print('SIMULACAO: nenhuma porta aberta e nenhum comando enviado.')
        return 0
    import serial
    seen = []
    started = False
    stopped = False
    report_dir = Path(__file__).resolve().parent / 'validacao_stop_baseline'
    report_dir.mkdir(exist_ok=True)
    with serial.Serial(args.port, 115200, timeout=0.05, write_timeout=0.5,
                       dsrdtr=False, rtscts=False) as port:
        port.dtr = True
        port.rts = False
        time.sleep(2)
        port.reset_input_buffer()
        try:
            port.write(b'?'); port.flush()
            initial = next_event(port, 'STATUS', 2.0, seen)
            print('STATUS inicial:', initial['detail'])
            if 'state=IDLE' not in initial['detail'] or 'firmware=pico-param-v1.5' not in initial['detail']:
                raise RuntimeError('Pico nao esta em IDLE com firmware esperado; nao iniciar.')
            port.write(CFG.encode('ascii')); port.flush()
            config = next_event(port, 'CONFIG_OK', 1.5, seen)
            print('CONFIG_OK:', config['detail'])
            if f'run_id={RUN_ID}' not in config['detail'] or 'profile=BAIXO' not in config['detail']:
                raise RuntimeError('Confirmacao de CFG nao coincide. Nao iniciar.')
            start_sent = time.monotonic()
            started = True
            port.write(b's'); port.flush()
            started_event = next_event(port, 'TEST_START', 1.0, seen)
            elapsed = time.monotonic() - start_sent
            print('TEST_START:', started_event['detail'])
            if elapsed >= 2.0:
                raise RuntimeError('Tempo ate TEST_START excessivo; enviar STOP.')
            port.write(b'x'); port.flush()
            stopped = True
            ack = next_event(port, 'TEST_ABORTED', 1.5, seen)
            print('TEST_ABORTED:', ack['detail'])
            port.write(b'?'); port.flush()
            status = next_event(port, 'STATUS', 1.5, seen)
            print('STATUS final:', status['detail'])
            if 'state=IDLE' not in status['detail']:
                raise RuntimeError('Pico nao retornou a IDLE.')
            if f'run_id={RUN_ID}' not in ack['detail'] or 'pulses=0' not in ack['detail']:
                raise RuntimeError('Interrupcao nao confirmou run diagnostico com zero pulsos.')
            print('PASSOU: STOP durante BASELINE, confirmado run=900001/pulses=0/IDLE.')
            print('IMPORTANTE: saida fisica GP2 nao foi medida. Nao e STOP de emergencia.')
        except BaseException:
            if started:
                try:
                    port.write(b'x'); port.flush()
                    print('STOP adicional enviado por precaucao. CONFIRA A BANCADA.')
                    # Evita deixar a porta ocupada em caso de falha.
                except Exception as e:
                    print('ATENCAO: nao consegui enviar STOP:', e)
            raise
        finally:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            report = {'test': 'stop_baseline', 'diagnostic_run': RUN_ID,
                      'port': args.port, 'events': seen,
                      'sent_start': started, 'sent_stop': stopped,
                      'time_utc': datetime.now(timezone.utc).isoformat()}
            target = report_dir / f'teste_{stamp}.json'
            target.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
            print('RELATORIO:', target)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
