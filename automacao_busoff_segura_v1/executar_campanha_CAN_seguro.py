#!/usr/bin/env python3
"""Executa planos CAN no Pico; monitora estado BUS_OFF no Node A e interrompe via x.

Requer pyserial para execucao na bancada. --dry-run nao abre hardware.
"""
import argparse
import csv
import json
import re
import hashlib
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
POST_BUSOFF_OBSERVATION_S = 2.0
# Mantido exatamente o protocolo do Pico ja utilizado nos ensaios oficiais.
EXPECTED_FIELDS = ('run_previsto', 'perfil', 'intervalo_min_us',
                   'intervalo_max_us', 'seed_hex', 'duracao_injecao_s',
                   'condicao', 'throttling_esperado', 'bloco')
PROFILES = {'BAIXO': (40000, 60000),
            'MEDIO_V2': (17500, 22500),
            'ALTO': (9375, 14375)}
CONDITIONS = {'REFERENCIA': 0, 'ADAPTATIVO': 1}


@dataclass(frozen=True)
class PlannedRun:
    run: int
    profile: str
    minimum: int
    maximum: int
    seed: int
    duration: int
    expected_pulses: int
    condition: str
    throttling: int
    block: int


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
                condition=row['condicao'].strip().upper(),
                throttling=int(row['throttling_esperado']),
                block=int(row['bloco']),
            )
            if run.run < 1 or run.profile not in PROFILES:
                raise ValueError(f'Run ou perfil invalido: {run}')
            if (run.minimum, run.maximum) != PROFILES[run.profile]:
                raise ValueError(f'Intervalos divergentes do perfil predefinido: {run}')
            if run.condition not in CONDITIONS or CONDITIONS[run.condition] != run.throttling:
                raise ValueError(f'Politica esperada inconsistente: {run}')
            if run.block < 0:
                raise ValueError(f'Bloco invalido: {run}')
            if not (5 <= run.duration <= 180 and 0 < run.seed <= 0xFFFFFFFF):
                raise ValueError(f'Semente/duracao invalida: {run}')
            ideal = ideal_pulses(run.seed, run.minimum, run.maximum, run.duration)
            if run.expected_pulses != -1 and ideal != run.expected_pulses:
                raise ValueError(f'Previsao de pulsos incorreta no plano, Run {run.run}: '
                                 f'CSV={run.expected_pulses}, calculada={ideal}')
            out.append(run)
    if [r.run for r in out] != sorted(r.run for r in out):
        raise ValueError('Os IDs devem estar ordenados de forma crescente.')
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
            'state': fields[6], 'detail': metrics(fields[8]), 'raw_detail': fields[8]}


class SerialCapture:
    def __init__(self, name, port, baud, folder, stop, fault):
        self.name = name
        self.port = port
        self.stop = stop
        self.fault = fault
        self.events = queue.Queue() if name in ('pico', 'node_a') else None
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
                            parsed['host_timestamp_ns'] = host_timestamp_ns
                            fields = line.split(',', 8)
                            csv_file.write(f'{fields[1]},{self.name},' + ','.join(fields[2:]) + '\n')
                            if self.events is not None and (self.name == 'pico' or parsed['event'] in ('STATE_CHANGE', 'SAMPLE')):
                                self.events.put(parsed)
                        elif self.name == 'pico' and line:
                            print(f'[pico] {line[:160]}')
                    except Exception as exc:
                        if not self.stop.is_set():
                            self.errors.append(str(exc))
                            self.fault.set()
                        break
        except Exception as exc:
            self.errors.append(str(exc))
            self.fault.set()

    def send(self, text, emergency=False):
        if self.stop.is_set() and not emergency:
            raise RuntimeError('Captura encerrada por erro serial.')
        self.device.write(text.encode('ascii'))
        self.device.flush()

    def close(self):
        self.thread.join(timeout=2.0)
        if self.device.is_open:
            self.device.close()


def bus_off_detected(item):
    """Detecta somente a ENTRADA em BUS_OFF, nao a recuperacao."""
    if item['event'] == 'STATE_CHANGE':
        old, separator, new = item['raw_detail'].strip().partition('->')
        return bool(separator) and old != 'BUS_OFF' and new == 'BUS_OFF'
    if item['event'] == 'SAMPLE':
        return item.get('state') == 'BUS_OFF'
    return False


def check_node_a_bus_off(node_a):
    if node_a is None:
        return
    while True:
        try:
            item = node_a.events.get_nowait()
        except queue.Empty:
            return
        if bus_off_detected(item):
            raise BusOffDetected(item)


class BusOffDetected(RuntimeError):
    def __init__(self, item):
        self.item = item
        super().__init__(f'Node A: {item["event"]} {item["raw_detail"]}')


def wait_abort_ack(pico, stop, run_id, timeout=3.0):
    """Retorna se o Pico confirmou a parada; sem confirmacao nao supor seguro."""
    limit = time.monotonic() + timeout
    while time.monotonic() < limit and not stop.is_set():
        try:
            item = pico.events.get(timeout=min(0.1, max(0.01, limit - time.monotonic())))
        except queue.Empty:
            continue
        if (item['event'] == 'TEST_ABORTED' and
                item['detail'].get('run_id') == str(run_id)):
            return item
    return None


def wait_idle_status(pico, stop, run_id, timeout=3.0):
    limit = time.monotonic() + timeout
    while time.monotonic() < limit and not stop.is_set():
        try:
            item = pico.events.get(timeout=min(0.1, max(0.01, limit - time.monotonic())))
        except queue.Empty:
            continue
        if (item['event'] == 'STATUS' and
                item['detail'].get('run_id') == str(run_id) and
                item['detail'].get('state') == 'IDLE'):
            return item
    return None


def wait_event(pico, event, timeout, stop, node_a=None, fault=None):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        check_node_a_bus_off(node_a)
        if fault is not None and fault.is_set():
            raise RuntimeError('Falha na captura serial; interrupcao requerida.')
        if stop.is_set():
            raise RuntimeError('Porta serial ou captura falhou.')
        try:
            item = pico.events.get(timeout=min(0.1, max(0.01, end - time.monotonic())))
        except queue.Empty:
            continue
        if item['event'] in {'CONFIG_ERROR', 'TEST_ABORTED'}:
            raise RuntimeError(f'Pico: {item["event"]}, {item["raw_detail"]}')
        if item['event'] == 'COMMAND' and item['raw_detail'] == 'TEST_ALREADY_RUNNING':
            raise RuntimeError('Pico ja estava executando um ensaio.')
        if item['event'] == event:
            check_node_a_bus_off(node_a)
            if fault is not None and fault.is_set():
                raise RuntimeError('Falha na captura serial; interrupcao requerida.')
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
    node_a_bin = (args.node_a_binary if args.node_a_binary is not None
                  else args.output.parent / 'firmware' / 'node-a' / 'build' / 'node_a.bin')
    binary_hash = (hashlib.sha256(node_a_bin.read_bytes()).hexdigest()
                   if node_a_bin.is_file() else None)
    metadata = {
        'run': plan.run,
        'condition': plan.condition,
        'expected_throttling': plan.throttling,
        'block': plan.block,
        'node_a_binary_sha256': binary_hash,
        'node_a_binary_sha256_note': 'Hash do arquivo local; nao prova sozinho qual binario esta gravado',
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
    fault = threading.Event()
    devices = {}
    phase = {}
    outcome = {'run': plan.run, 'condition': plan.condition, 'expected_throttling': plan.throttling,
               'valid': False, 'reason': None, 'warnings': [],
               'bus_off_detected': False, 'stop_command_sent': False,
               'stop_acknowledged': False, 'pico_idle_confirmed': False,
               'observation_status': 'FULL_DURATION_UNCONFIRMED',
        'first_bus_off_event': None}
    in_progress = False
    controller = (folder / 'control_events.jsonl').open('w', encoding='utf-8', buffering=1)
    try:
        for name, port in [('node_a', args.node_a), ('node_b', args.node_b), ('pico', args.pico)]:
            devices[name] = SerialCapture(name, port, args.baud, folder, stop, fault)
            control_event(controller, 'DEVICE_CONNECTED', name=name, port=port)
        pico = devices['pico']
        time.sleep(2.0)  # deixa os ESP32 completarem o boot apos abertura das portas
        pico.send('?')
        control_event(controller, 'STATUS_SENT')
        status = wait_event(pico, 'STATUS', timeout=6, stop=stop, fault=fault)
        check_fields(status, {'firmware': VERSION, 'state': 'IDLE'})
        command = (f'CFG,{plan.run},{plan.profile},{plan.minimum},{plan.maximum},'
                   f'{plan.seed:08X},{plan.duration}\n')
        pico.send(command)
        control_event(controller, 'CONFIG_SENT', command=command.rstrip())
        ack = wait_event(pico, 'CONFIG_OK', timeout=5, stop=stop, fault=fault)
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
        # Valida o modo de verdade pelo boot do ESP32, antes de gerar pulsos.
        a_log = (folder / 'node_a.log').read_text(encoding='utf-8', errors='replace')
        found = re.findall(r'NODE_A:[^\n]*?throttling=([01])', a_log)
        if not found:
            raise RuntimeError('Nao encontrei throttling=0/1 na linha NODE_A do boot; '
                               'ensaio nao iniciado.')
        if len(set(found)) != 1 or int(found[-1]) != plan.throttling:
            raise RuntimeError(f'Modo incorreto no Node A: esperado '
                               f'throttling={plan.throttling}, observado {found}; '
                               'nenhum pulso iniciado.')
        if 'TWAI 125000 bit/s' not in a_log:
            raise RuntimeError('Taxa CAN de 125000 bit/s nao comprovada no boot do Node A.')
        control_event(controller, 'NODE_A_MODE_VERIFIED', throttling=plan.throttling,
                      condition=plan.condition)
        in_progress = True
        pico.send('s')
        control_event(controller, 'START_SENT')
        for event, limit in [
            ('TEST_START', 5), ('NOISE_START', 9),
            ('NOISE_END', plan.duration + 9), ('TEST_END', 9),
        ]:
            phase[event] = wait_event(pico, event, timeout=limit, stop=stop,
                                      node_a=devices['node_a'], fault=fault)
            print(f'  {event}: {phase[event]["raw_detail"]}')
        in_progress = False
        time.sleep(0.8)  # escoamento dos ultimos bytes seriais
        check_node_a_bus_off(devices['node_a'])
        if fault.is_set():
            raise RuntimeError('Falha na captura serial ao encerrar ensaio.')
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
        outcome['bus_off_detected'] = isinstance(exc, BusOffDetected)
        if outcome['bus_off_detected']:
            outcome['first_bus_off_event'] = {
                'event': exc.item['event'],
                'node_a_timestamp_us': exc.item['timestamp_us'],
                'host_capture_timestamp_ns': exc.item.get('host_timestamp_ns'),
                'details': exc.item['raw_detail'],
            }
            outcome['host_detection_timestamp_ns'] = time.time_ns()
        outcome['observation_status'] = ('BUS_OFF_OBSERVED_ABORTED'
                                         if outcome['bus_off_detected'] else 'ABORTED_OTHER')
        print(f'  FALHA Run {plan.run}: {outcome["reason"]}')
        if in_progress and 'pico' in devices:
            pico = devices['pico']
            try:
                pico.send('x', emergency=True)
                outcome['stop_command_sent'] = True
            except Exception as stop_exc:
                outcome['warnings'].append(f'Falha ao enviar comando x: {stop_exc}')
            if outcome['stop_command_sent']:
                ack = wait_abort_ack(pico, stop, plan.run)
                outcome['stop_acknowledged'] = ack is not None
                if ack is not None:
                    try:
                        pico.send('?', emergency=True)
                        idle = wait_idle_status(pico, stop, plan.run)
                        outcome['pico_idle_confirmed'] = idle is not None
                    except Exception as status_exc:
                        outcome['warnings'].append(f'Falha ao confirmar IDLE: {status_exc}')
                if not outcome['stop_acknowledged'] or not outcome['pico_idle_confirmed']:
                    outcome['warnings'].append('Parada logica nao confirmada; verificar bancada imediatamente.')
                elif outcome['bus_off_detected'] and not fault.is_set():
                    time.sleep(POST_BUSOFF_OBSERVATION_S)
                    outcome['post_bus_off_observation_s'] = POST_BUSOFF_OBSERVATION_S
            try:
                control_event(controller, 'STOP_RESULT',
                              reason=outcome['reason'], sent=outcome['stop_command_sent'],
                              acknowledged=outcome['stop_acknowledged'],
                              idle=outcome['pico_idle_confirmed'])
            except Exception as log_exc:
                outcome['warnings'].append(f'Falha no log de controle apos tentativa de parada: {log_exc}')
        elif in_progress:
            outcome['warnings'].append('Pico indisponivel: interrupcao por software nao confirmada.')
    finally:
        stop.set()
        for device in devices.values():
            try:
                device.close()
            except Exception as close_exc:
                outcome['warnings'].append(f'Falha ao fechar {device.name}: {close_exc}')
                if outcome['reason'] is None:
                    outcome['reason'] = f'Falha ao fechar {device.name}: {close_exc}'
        for device in devices.values():
            if device.errors:
                outcome['warnings'].extend(f'Erro serial {device.name}: {e}' for e in device.errors)
                if outcome['reason'] is None:
                    outcome['reason'] = '; '.join(device.errors)
        if not outcome['reason']:
            try:
                a_log = (folder / 'node_a.log').read_text(encoding='utf-8', errors='replace')
                boot_modes = re.findall(r'NODE_A:[^\n]*?throttling=([01])', a_log)
                if not boot_modes or int(boot_modes[-1]) != plan.throttling:
                    raise RuntimeError(f'Politica incorreta no boot: esperado {plan.throttling}')
                for node in ('node_a', 'node_b'):
                    samples = count_events(folder / f'{node}.log', 'SAMPLE')
                    outcome[f'{node}_SAMPLE'] = samples
                    if samples < 2:
                        raise RuntimeError(f'{node}: captura sem SAMPLE suficiente ({samples}).')
                for node, event in [('node_a', 'TX_SUCCESS'), ('node_b', 'RECEIVED')]:
                    count = count_events(folder / f'{node}.log', event)
                    outcome[f'{node}_{event}'] = count
                    if count < plan.duration * 40:
                        outcome['warnings'].append(
                            f'{node}: {event}={count} abaixo do esperado; '
                            'avaliar impacto de throttling, erros e eventual Bus-Off')
                if binary_hash is None:
                    outcome['warnings'].append('Binario node_a.bin nao encontrado para hash SHA-256')
                outcome['valid'] = True
                outcome['observation_status'] = 'FULL_DURATION_VERIFIED'
            except Exception as exc:
                outcome['reason'] = str(exc)
        controller.close()
        (folder / 'qc.json').write_text(json.dumps(outcome, indent=2, ensure_ascii=False), encoding='utf-8')
        archive_run(folder, destination)
        print(f'  ZIP: {destination}')
    return outcome


def main():
    parser = argparse.ArgumentParser(description='Campanha CAN, parametros Pico v1.5 e politica do Node A verificada')
    parser.add_argument('--plan', type=Path, default=Path(__file__).with_name('plano_oficial_CAN_runs_153_188.csv'))
    parser.add_argument('--node-a', default='/dev/ttyUSB0')
    parser.add_argument('--node-b', default='/dev/ttyACM0')
    parser.add_argument('--pico', default='/dev/ttyACM1')
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[2] / 'data')
    parser.add_argument('--node-a-binary', type=Path, default=None,
                        help='Binario de aplicacao do Node A usado para calcular o hash correto.')
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
                  f'{p.minimum}-{p.maximum} us, {ideal_pulses(p.seed,p.minimum,p.maximum,p.duration)} pulsos ideais, '
                  f'{p.condition}, bloco {p.block}')
        if args.dry_run:
            print('Plano valido; nenhum dispositivo foi acessado.')
            return 0
        policies = {p.condition for p in selected}
        if len(policies) != 1:
            parser.error('Selecao contem REFERENCIA e ADAPTATIVO. Execute separadamente '
                         'cada grupo de ate 3 runs da mesma politica; nao existe troca '
                         'automatica de firmware do ESP32.')
        required = selected[0]
        print(f'CONFIRA NODE A: {required.condition}, throttling={required.throttling}. '
              'O script validara o boot antes de enviar o comando de inicio.')
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
