#!/usr/bin/env python3
"""Executa planos CAN no Pico parametrizavel; mantem logs/csv da captura v13.

Requer pyserial para execucao na bancada. --dry-run nao abre hardware.
"""
import argparse
import csv
import json
import queue
import sys
import threading
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    import serial
except ImportError:
    serial = None

VERSION = 'pico-param-v1.5'
EXPECTED_FIELDS = ('run_previsto', 'perfil', 'intervalo_min_us',
                   'intervalo_max_us', 'seed_hex', 'duracao_injecao_s')


@dataclass(frozen=True)
class PlannedRun:
    run: int
    profile: str
    minimum: int
    maximum: int
    seed: int
    duration: int
    expected_pulses: int


def ideal_pulses(seed, minimum, maximum, duration):
    x = seed
    deadline = 0
    pulses = 0
    span = maximum - minimum + 1
    while True:
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        x &= 0xFFFFFFFF
        deadline += minimum + (x % span)
        if deadline >= duration * 1000000:
            return pulses
        pulses += 1


def load_plan(path):
    out = []
    with path.open(newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        for name in EXPECTED_FIELDS:
            if name not in (reader.fieldnames or []):
                raise ValueError(f'Coluna ausente no plano: {name}')
        for row in reader:
            run = PlannedRun(
                run=int(row['run_previsto']),
                profile=row['perfil'].strip().upper(),
                minimum=int(row['intervalo_min_us']),
                maximum=int(row['intervalo_max_us']),
                seed=int(row['seed_hex'], 0),
                duration=int(row['duracao_injecao_s']),
                expected_pulses=int(row['pulsos_ideais_previstos'])
                if row.get('pulsos_ideais_previstos') else -1,
            )
            if run.run < 1 or run.profile not in {'BAIXO', 'MEDIO_V2', 'MEDIO_ORIGINAL', 'ALTO'}:
                raise ValueError(f'Run ou perfil invalido: {run}')
            if not (1000 <= run.minimum <= run.maximum <= 100000):
                raise ValueError(f'Intervalo invalido: {run}')
            if not (5 <= run.duration <= 180 and 0 < run.seed <= 0xFFFFFFFF):
                raise ValueError(f'Semente/duracao invalida: {run}')
            ideal = ideal_pulses(run.seed, run.minimum, run.maximum, run.duration)
            if run.expected_pulses != -1 and ideal != run.expected_pulses:
                raise ValueError(f'Previsao de pulsos incorreta no plano, Run {run.run}: '
                                 f'CSV={run.expected_pulses}, calculada={ideal}')
            out.append(run)
    if len({r.run for r in out}) != len(out):
        raise ValueError('O plano contem IDs repetidos.')
    if not out:
        raise ValueError('O plano esta vazio.')
    return out


def metrics(detail):
    return dict(pair.split('=', 1) for pair in detail.split(';') if '=' in pair)


def parse_data_line(line):
    fields = line.split(',', 8)
    if len(fields) != 9 or fields[0] != 'DATA':
        return None
    try:
        timestamp = int(fields[1])
    except ValueError:
        return None
    return {'timestamp_us': timestamp, 'event': fields[2],
            'detail': metrics(fields[8]), 'raw_detail': fields[8]}


class SerialCapture:
    def __init__(self, name, port, baud, folder, stop):
        self.name = name
        self.port = port
        self.stop = stop
        self.events = queue.Queue() if name == 'pico' else None
        self.errors = []
        self.lines = 0
        self.device = serial.Serial()
        self.device.port = port
        self.device.baudrate = baud
        self.device.timeout = 0.1
        self.device.write_timeout = 1
        self.device.dtr = (name == 'pico')
        self.device.rts = False
        self.device.open()
        self.device.dtr = (name == 'pico')
        self.device.rts = False
        self.raw_path = folder / f'{name}.log'
        self.csv_path = folder / f'{name}.csv'
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        try:
            with self.raw_path.open('w', encoding='utf-8', buffering=1) as raw_file, \
                    self.csv_path.open('w', encoding='utf-8', buffering=1) as csv_file:
                csv_file.write('timestamp_us,node,event,sequence,tec,rec,state,mode,detail\n')
                while not self.stop.is_set():
                    try:
                        raw = self.device.readline()
                        if not raw:
                            continue
                        host_timestamp_ns = time.time_ns()
                        line = raw.decode('utf-8', errors='replace').rstrip('\r\n')
                        raw_file.write(f'{host_timestamp_ns}\t{line}\n')
                        self.lines += 1
                        parsed = parse_data_line(line)
                        if parsed:
                            fields = line.split(',', 8)
                            csv_file.write(f'{fields[1]},{self.name},' + ','.join(fields[2:]) + '\n')
                            if self.events is not None:
                                self.events.put(parsed)
                        elif self.name == 'pico' and line:
                            print(f'[pico] {line[:160]}')
                    except Exception as exc:
                        if not self.stop.is_set():
                            self.errors.append(str(exc))
                            self.stop.set()
                        break
        except Exception as exc:
            self.errors.append(str(exc))
            self.stop.set()

    def send(self, text):
        if self.stop.is_set():
            raise RuntimeError('Captura encerrada por erro serial.')
        self.device.write(text.encode('ascii'))
        self.device.flush()

    def close(self):
        self.thread.join(timeout=2.0)
        if self.device.is_open:
            self.device.close()


def wait_event(pico, event, timeout, stop):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if stop.is_set():
            raise RuntimeError('Porta serial ou captura falhou.')
        try:
            item = pico.events.get(timeout=min(0.2, max(0.01, end - time.monotonic())))
        except queue.Empty:
            continue
        if item['event'] in {'CONFIG_ERROR', 'TEST_ABORTED'}:
            raise RuntimeError(f'Pico: {item["event"]}, {item["raw_detail"]}')
        if item['event'] == 'COMMAND' and item['raw_detail'] == 'TEST_ALREADY_RUNNING':
            raise RuntimeError('Pico ja estava executando um ensaio.')
        if item['event'] == event:
            return item
    raise TimeoutError(f'Tempo esgotado aguardando {event} ({timeout}s).')


def control_event(file, event_name, **info):
    file.write(json.dumps({'event': event_name, 'host_timestamp_ns': time.time_ns(), **info},
                          ensure_ascii=False) + '\n')


def check_fields(observed, expected):
    for key, value in expected.items():
        if str(observed['detail'].get(key, '')).lower() != str(value).lower():
            raise RuntimeError(f'Dados inconsistentes em {observed["event"]}: '
                               f'{key} esperado={value}, recebido={observed["detail"].get(key)}')


def count_events(path, event):
    total = 0
    with path.open(encoding='utf-8', errors='replace') as f:
        for line in f:
            if f'\tDATA,' in line and f',{event},' in line:
                total += 1
    return total


def archive_run(folder, destination):
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipfile_:
        for file in sorted(folder.glob('*')):
            if file.is_file():
                zipfile_.write(file, file.name)


def run_one(plan, args):
    raw_root = args.output / 'raw'
    zip_root = args.output / 'zips'
    raw_root.mkdir(parents=True, exist_ok=True)
    zip_root.mkdir(parents=True, exist_ok=True)
    folder = raw_root / f'run_{plan.run:03d}_injection'
    destination = zip_root / f'run_{plan.run}_injection.zip'
    if folder.exists() or destination.exists():
        raise RuntimeError(f'Arquivos do Run {plan.run} ja existem; nao vou sobrescrever: {folder}')
    folder.mkdir()
    metadata = {
        'run': plan.run,
        'type': 'injection',
        'started_at': datetime.now(timezone.utc).isoformat(),
        'baud': args.baud,
        'devices': {'node_a': args.node_a, 'node_b': args.node_b, 'pico': args.pico},
        'planned': {'profile': plan.profile, 'seed_hex': f'0x{plan.seed:08X}',
                    'interval_min_us': plan.minimum, 'interval_max_us': plan.maximum,
                    'injection_duration_s': plan.duration, 'pulse_width_us_nominal': 8,
                    'ideal_pulses': ideal_pulses(plan.seed, plan.minimum, plan.maximum, plan.duration)},
        'firmware_expected': VERSION,
    }
    (folder / 'metadata.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding='utf-8')
    stop = threading.Event()
    devices = {}
    phase = {}
    outcome = {'run': plan.run, 'valid': False, 'reason': None}
    in_progress = False
    try:
        with (folder / 'control_events.jsonl').open('w', encoding='utf-8', buffering=1) as controller:
            for name, port in [('node_a', args.node_a), ('node_b', args.node_b), ('pico', args.pico)]:
                devices[name] = SerialCapture(name, port, args.baud, folder, stop)
                control_event(controller, 'DEVICE_CONNECTED', name=name, port=port)
            pico = devices['pico']
            time.sleep(2.0)  # deixa os ESP32 completarem o boot apos abertura das portas
            pico.send('?')
            control_event(controller, 'STATUS_SENT')
            status = wait_event(pico, 'STATUS', timeout=6, stop=stop)
            check_fields(status, {'firmware': VERSION, 'state': 'IDLE'})
            command = (f'CFG,{plan.run},{plan.profile},{plan.minimum},{plan.maximum},'
                       f'{plan.seed:08X},{plan.duration}\n')
            pico.send(command)
            control_event(controller, 'CONFIG_SENT', command=command.rstrip())
            ack = wait_event(pico, 'CONFIG_OK', timeout=5, stop=stop)
            check_fields(ack, {
                'run_id': plan.run, 'profile': plan.profile,
                'interval_min_us': plan.minimum, 'interval_max_us': plan.maximum,
                'seed': f'0x{plan.seed:08x}', 'injection_us': plan.duration * 1000000,
            })
            phase['CONFIG_OK'] = ack
            # Evita iniciar se algum no nao completou o boot
            for node in ('node_a', 'node_b'):
                if devices[node].lines < 5:
                    raise RuntimeError(f'{node} nao produziu dados apos abertura serial.')
            pico.send('s')
            in_progress = True
            control_event(controller, 'START_SENT')
            for event, limit in [
                ('TEST_START', 5), ('NOISE_START', 9),
                ('NOISE_END', plan.duration + 9), ('TEST_END', 9),
            ]:
                phase[event] = wait_event(pico, event, timeout=limit, stop=stop)
                print(f'  {event}: {phase[event]["raw_detail"]}')
            in_progress = False
            time.sleep(0.8)  # escoamento dos ultimos bytes seriais
            control_event(controller, 'CAPTURE_END_REQUESTED')
            check_fields(phase['TEST_START'], {
                'run_id': plan.run, 'profile': plan.profile,
                'injection_us': plan.duration * 1000000,
                'baseline_us': 5000000, 'recovery_us': 5000000,
            })
            check_fields(phase['NOISE_START'], {
                'run_id': plan.run, 'profile': plan.profile,
                'interval_min_us': plan.minimum, 'interval_max_us': plan.maximum,
                'seed': f'0x{plan.seed:08x}', 'pulse_us': 8,
            })
            for e in ('NOISE_END', 'TEST_END'):
                check_fields(phase[e], {'run_id': plan.run})
            start_us = phase['NOISE_START']['timestamp_us']
            end_us = phase['NOISE_END']['timestamp_us']
            actual_duration = (end_us - start_us) / 1e6
            if abs(actual_duration - plan.duration) > 0.01:
                raise RuntimeError(f'Duracao incorreta: {actual_duration:.6f}s')
            end_detail = phase['TEST_END']['detail']
            recorded = int(end_detail['pulses'])
            missed = int(end_detail['missed_deadlines'])
            ideal = ideal_pulses(plan.seed, plan.minimum, plan.maximum, plan.duration)
            if missed != 0:
                raise RuntimeError(f'O Pico perdeu {missed} prazos de agendamento.')
            if recorded != ideal:
                raise RuntimeError(f'Pulsos divergentes: obtidos {recorded}, previstos {ideal}.')
            outcome.update({'pulses': recorded, 'missed_deadlines': missed,
                            'max_late_us': int(end_detail['max_late_us']),
                            'injection_actual_s': actual_duration})
    except (Exception, KeyboardInterrupt) as exc:
        outcome['reason'] = str(exc) or type(exc).__name__
        print(f'  FALHA Run {plan.run}: {outcome["reason"]}')
        if in_progress and 'pico' in devices:
            try:
                devices['pico'].send('x')
            except Exception:
                pass
    finally:
        stop.set()
        for device in devices.values():
            device.close()
        for device in devices.values():
            if device.errors and outcome['reason'] is None:
                outcome['reason'] = '; '.join(device.errors)
        if not outcome['reason']:
            try:
                a_log = (folder / 'node_a.log').read_text(encoding='utf-8', errors='replace')
                if 'throttling=0' not in a_log:
                    raise RuntimeError('Nao foi comprovado throttling=0 no boot do Node A.')
                for node, event in [('node_a', 'TX_SUCCESS'), ('node_b', 'RECEIVED')]:
                    count = count_events(folder / f'{node}.log', event)
                    outcome[f'{node}_{event}'] = count
                    if count < plan.duration * 40:
                        raise RuntimeError(f'{node}: numero anormalmente baixo de eventos {event}: {count}')
                outcome['valid'] = True
            except Exception as exc:
                outcome['reason'] = str(exc)
        (folder / 'qc.json').write_text(json.dumps(outcome, indent=2, ensure_ascii=False), encoding='utf-8')
        archive_run(folder, destination)
        print(f'  ZIP: {destination}')
    return outcome


def main():
    parser = argparse.ArgumentParser(description='Captura automatica CAN com firmware Pico parametrizavel v1.5')
    parser.add_argument('--plan', type=Path, default=Path(__file__).with_name('plano_runs_145_150.csv'))
    parser.add_argument('--node-a', default='/dev/ttyUSB0')
    parser.add_argument('--node-b', default='/dev/ttyACM0')
    parser.add_argument('--pico', default='/dev/ttyACM1')
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[2] / 'data')
    parser.add_argument('--from-run', type=int)
    parser.add_argument('--to-run', type=int)
    parser.add_argument('--between', type=float, default=3.0,
                        help='Pausa em segundos entre ensaios (padrao: 3).')
    parser.add_argument('--dry-run', action='store_true', help='Confere plano sem abrir hardware.')
    args = parser.parse_args()
    try:
        plans = load_plan(args.plan)
        selected = [p for p in plans if (args.from_run is None or p.run >= args.from_run)
                    and (args.to_run is None or p.run <= args.to_run)]
        if not selected:
            parser.error('Nenhum run selecionado.')
        print(f'Plano: {args.plan}; {len(selected)} ensaio(s)')
        for p in selected:
            print(f'  Run {p.run}: {p.profile}, {p.duration}s, seed=0x{p.seed:08X}, '
                  f'{p.minimum}-{p.maximum} us, {ideal_pulses(p.seed,p.minimum,p.maximum,p.duration)} pulsos ideais')
        if args.dry_run:
            print('Plano valido; nenhum dispositivo foi acessado.')
            return 0
        if serial is None:
            parser.error('pyserial nao instalado: python3 -m pip install pyserial')
        for i, p in enumerate(selected):
            print(f'\nExecutando Run {p.run} ({i+1}/{len(selected)})...')
            result = run_one(p, args)
            if not result['valid']:
                print('Lote interrompido. Repeticoes devem receber novo ID no plano.')
                return 1
            print(f'  VALIDADO: {result["pulses"]} pulsos, maior atraso '
                  f'{result["max_late_us"]} us')
            if i < len(selected) - 1:
                time.sleep(args.between)
        print(f'\nTodos os ensaios selecionados terminaram. Consulte {args.output / "zips"}/.')
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print(f'Erro: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())