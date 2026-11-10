#!/usr/bin/env python3
"""Analisa ZIPs CAN/TWAI existentes, inclusive abortados por Bus-Off.

Nao abre portas seriais, nao modifica firmwares nem executa injetor.
Python 3.10+, somente biblioteca padrao.
"""
import argparse
import csv
import io
import json
import re
import zipfile
from collections import Counter, defaultdict, deque
from pathlib import Path

FIELDS = ['run', 'condition', 'observation_status', 'qc_valid',
          'bus_off_raw', 'bus_off_qc', 'first_busoff_event', 'first_busoff_node_a_us',
          'first_busoff_approx_since_noise_s', 'first_busoff_host_capture_ns',
          'pico_noise_start_host_ns', 'pico_end_event', 'boot_throttling', 'control_stop_result', 'stop_sent',
          'stop_ack', 'pico_idle', 'max_sampled_tec_in_injection',
          'max_tec_peak_in_injection', 'observed_tec_ge_96',
          'observed_tec_ge_128', 'node_a_tx_success_captured',
          'node_b_received_captured', 'node_a_lost_max',
          'node_a_samples_in_injection', 'warnings']
CRITICAL = {'STATE_CHANGE', 'RECOVERY_REQUEST', 'TX_FAILED', 'TX_REJECTED',
            'PENDING_WARNING'}


def details(text):
    return dict(part.split('=', 1) for part in str(text).split(';') if '=' in part)


def get_member(zf, name):
    matches = [s for s in zf.namelist() if Path(s).name == name]
    if len(matches) != 1:
        raise ValueError(f'{name}: esperado 1 membro, encontrados {len(matches)}')
    return zf.read(matches[0]).decode('utf-8-sig', errors='replace')


def as_number(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def parse_log(raw):
    out = []
    for line in raw.splitlines():
        m = re.match(r'^(\d+)\t(DATA,.*)$', line)
        if not m:
            continue
        fields = m.group(2).split(',', 8)
        if len(fields) != 9:
            continue
        out.append({'host_ns': int(m.group(1)), 'device_us': as_number(fields[1]),
                    'event': fields[2], 'detail': fields[8]})
    return out


def match_host(records, log_items, warnings, label):
    """Mapeia por (timestamp,event), sem inventar sincronizacao entre MCUs."""
    index = defaultdict(deque)
    for item in log_items:
        index[(item['device_us'], item['event'])].append(item['host_ns'])
    absent = 0
    for row in records:
        row['device_us'] = as_number(row.get('timestamp_us'))
        q = index[(row['device_us'], row.get('event'))]
        row['host_ns'] = q.popleft() if q else None
        if row['host_ns'] is None:
            absent += 1
    if absent:
        warnings.append(f'{label}: {absent}/{len(records)} eventos sem timestamp host associavel')
    return records


def busoff_entry(row):
    ev = row.get('event')
    if ev == 'STATE_CHANGE':
        before, sep, after = row.get('detail', '').strip().partition('->')
        return bool(sep) and before != 'BUS_OFF' and after == 'BUS_OFF'
    return ev == 'SAMPLE' and row.get('state') == 'BUS_OFF'


def qc_status(qc):
    return 'true' if qc.get('valid') is True else 'false'


def analyze(path, output):
    warnings = []
    with zipfile.ZipFile(path) as zf:
        if zf.testzip() is not None:
            raise ValueError(f'ZIP corrompido: {path}')
        meta = json.loads(get_member(zf, 'metadata.json'))
        qc = json.loads(get_member(zf, 'qc.json'))
        rows = {}
        raw_logs = {}
        for name in ('node_a', 'node_b', 'pico'):
            data = list(csv.DictReader(io.StringIO(get_member(zf, f'{name}.csv'))))
            raw_logs[name] = get_member(zf, f'{name}.log')
            rows[name] = match_host(data, parse_log(raw_logs[name]), warnings, name)
        control = []
        try:
            control = [json.loads(line) for line in get_member(zf, 'control_events.jsonl').splitlines()
                       if line.strip()]
        except ValueError:
            warnings.append('control_events.jsonl ausente ou nao unico')
        except json.JSONDecodeError:
            warnings.append('control_events.jsonl contem JSON invalido')

    run_id = meta.get('run', qc.get('run', path.stem))
    folder = output / f'run_{run_id}'
    if folder.exists():
        raise FileExistsError(f'Saida ja existe: {folder}; use outra pasta --out')
    folder.mkdir(parents=True)
    pico = rows['pico']
    a = rows['node_a']
    b = rows['node_b']

    def first_event(data, kind):
        return next((row for row in data if row.get('event') == kind), None)

    noise = first_event(pico, 'NOISE_START')
    ended = first_event(pico, 'NOISE_END')
    aborted = first_event(pico, 'TEST_ABORTED')
    end = ended or aborted
    busoff_candidates = [row for row in a if busoff_entry(row)]
    first_bo = min(busoff_candidates,
                   key=lambda row: row.get('device_us') if row.get('device_us') is not None else float('inf'),
                   default=None)

    boot_modes = re.findall(r'NODE_A:[^\n]*?throttling=([01])', raw_logs['node_a'])
    boot_mode = int(boot_modes[-1]) if boot_modes and len(set(boot_modes)) == 1 else None
    if meta.get('expected_throttling') is not None and boot_mode is not None and (
            boot_mode != meta['expected_throttling']):
        warnings.append('Modo do No A no boot diverge da metadata')
    if boot_mode is None:
        warnings.append('Nao foi possivel conferir throttling=0/1 no boot do No A')
    stop_results = [item for item in control if item.get('event') == 'STOP_RESULT']
    last_stop = stop_results[-1] if stop_results else None
    if qc.get('bus_off_detected') and not last_stop:
        warnings.append('Bus-Off no QC, mas STOP_RESULT nao foi encontrado em control_events.jsonl')
    if last_stop:
        for key, qc_key in [('sent', 'stop_command_sent'),
                            ('acknowledged', 'stop_acknowledged'),
                            ('idle', 'pico_idle_confirmed')]:
            if bool(last_stop.get(key)) != bool(qc.get(qc_key)):
                warnings.append(f'STOP_RESULT.{key} diverge do QC.{qc_key}')
    if noise is None:
        warnings.append('NOISE_START ausente; janela de injeção não identificável')
    if end is None:
        warnings.append('NOISE_END/TEST_ABORTED ausente; fim da janela de injeção desconhecido')
    if qc.get('bus_off_detected') and first_bo is None:
        warnings.append('QC marca Bus-Off, mas nenhum STATE_CHANGE/SAMPLE correspondente no CSV do Nó A')
    if first_bo is not None and not qc.get('bus_off_detected'):
        warnings.append('Log mostra Bus-Off, mas QC nao marcou bus_off_detected')
    if aborted is not None and qc.get('bus_off_detected') and not (
            qc.get('stop_acknowledged') and qc.get('pico_idle_confirmed')):
        warnings.append('Bus-Off: parada nao confirmada por ACK e STATUS IDLE no QC')

    start_ns = noise.get('host_ns') if noise else None
    end_ns = end.get('host_ns') if end else None

    def inside(row):
        t = row.get('host_ns')
        return t is not None and start_ns is not None and t >= start_ns and (
            end_ns is None or t <= end_ns)

    samples = [r for r in a if r.get('event') == 'SAMPLE' and inside(r)]
    observed_tec = [as_number(r.get('tec')) for r in samples]
    observed_tec = [x for x in observed_tec if x is not None]
    peaks = [as_number(details(r.get('detail', '')).get('tec_peak')) for r in samples]
    peaks = [x for x in peaks if x is not None]
    lost = [as_number(details(r.get('detail', '')).get('lost')) for r in a if r.get('event') == 'SAMPLE']
    lost = [x for x in lost if x is not None]

    progression = []
    for r in samples:
        d = details(r.get('detail', ''))
        progression.append({
            'node_a_timestamp_us': r.get('device_us'),
            'host_capture_timestamp_ns': r.get('host_ns'),
            'approx_s_since_pico_NOISE_START': round((r['host_ns']-start_ns)/1e9, 6),
            'tec': r.get('tec'), 'tec_peak_since_last_sample': d.get('tec_peak'),
            'rec': r.get('rec'), 'state': r.get('state'), 'mode': r.get('mode'),
            'produced': d.get('produced'), 'submitted': d.get('submitted'),
            'tx_ok': d.get('tx_ok'), 'gap': d.get('gap'),
            'pending': d.get('pending'), 'lost': d.get('lost'),
        })

    critical = []
    for r in a:
        if r.get('event') in CRITICAL or busoff_entry(r):
            t = r.get('host_ns')
            critical.append({
                'node_a_timestamp_us': r.get('device_us'),
                'host_capture_timestamp_ns': t,
                'approx_s_since_pico_NOISE_START': (round((t-start_ns)/1e9, 6)
                                                     if t is not None and start_ns is not None else ''),
                'event': r.get('event'), 'state': r.get('state'),
                'detail': r.get('detail'), 'bus_off_entry': busoff_entry(r),
            })

    bo_host_ns = first_bo.get('host_ns') if first_bo else None
    bo_dt = ((bo_host_ns - start_ns)/1e9 if bo_host_ns is not None and start_ns is not None
             else None)
    if bo_dt is not None and bo_dt < 0:
        warnings.append('Bus-Off observado antes de NOISE_START: nao atribuir a este periodo de injeção')

    summary = {
        'run': run_id, 'condition': meta.get('condition', qc.get('condition')),
        'observation_status': qc.get('observation_status', 'NAO_INFORMADO'),
        'qc_valid': qc_status(qc),
        'bus_off_raw': first_bo is not None,
        'bus_off_qc': bool(qc.get('bus_off_detected')),
        'first_busoff_event': first_bo.get('event') if first_bo else None,
        'first_busoff_node_a_us': first_bo.get('device_us') if first_bo else None,
        'first_busoff_approx_since_noise_s': (round(bo_dt, 6) if bo_dt is not None else None),
        'first_busoff_host_capture_ns': bo_host_ns,
        'pico_noise_start_host_ns': start_ns,
        'pico_end_event': end.get('event') if end else None,
        'boot_throttling': boot_mode,
        'control_stop_result': bool(last_stop),
        'stop_sent': bool(qc.get('stop_command_sent')),
        'stop_ack': bool(qc.get('stop_acknowledged')),
        'pico_idle': bool(qc.get('pico_idle_confirmed')),
        'max_sampled_tec_in_injection': max(observed_tec, default=None),
        'max_tec_peak_in_injection': max(peaks, default=None),
        'observed_tec_ge_96': any(x >= 96 for x in observed_tec),
        'observed_tec_ge_128': any(x >= 128 for x in observed_tec),
        'node_a_tx_success_captured': sum(r.get('event') == 'TX_SUCCESS' and inside(r) for r in a),
        'node_b_received_captured': sum(r.get('event') == 'RECEIVED' and inside(r) for r in b),
        'node_a_lost_max': max(lost, default=None),
        'node_a_samples_in_injection': len(samples),
        'warnings': warnings,
        'metadados': {'profile': meta.get('planned', {}).get('profile'),
                      'seed': meta.get('planned', {}).get('seed_hex'),
                      'expected_throttling': meta.get('expected_throttling'),
                      'run_reason': qc.get('reason'), 'first_busoff_qc': qc.get('first_bus_off_event'),
                      'interval_min_us': meta.get('planned', {}).get('interval_min_us'),
                      'interval_max_us': meta.get('planned', {}).get('interval_max_us')},
    }

    def save_csv(name, data, headers):
        with (folder / name).open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=headers)
            writer.writeheader()
            writer.writerows(data)

    save_csv('progressao_tec.csv', progression,
             ['node_a_timestamp_us', 'host_capture_timestamp_ns',
              'approx_s_since_pico_NOISE_START', 'tec', 'tec_peak_since_last_sample',
              'rec', 'state', 'mode', 'produced', 'submitted', 'tx_ok', 'gap', 'pending', 'lost'])
    save_csv('eventos_criticos.csv', critical,
             ['node_a_timestamp_us', 'host_capture_timestamp_ns',
              'approx_s_since_pico_NOISE_START', 'event', 'state', 'detail', 'bus_off_entry'])
    (folder / 'resumo.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n',
                                       encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zips', type=Path, nargs='+', help='Um ou mais run_XXX_injection.zip')
    parser.add_argument('--out', type=Path, default=Path('analysis/analise_busoff_offline'))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    all_rows = []
    errors = []
    for path in args.zips:
        try:
            summary = analyze(path, args.out)
            all_rows.append(summary)
            print(f"Run {summary['run']}: BUS_OFF_RAW={summary['bus_off_raw']}, "
                  f"QC={summary['observation_status']}, TEC_MAX={summary['max_tec_peak_in_injection']}")
        except Exception as exc:
            errors.append(f'{path}: {type(exc).__name__}: {exc}')
            print(f'ERRO: {errors[-1]}')
    with (args.out / 'indice.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore')
        writer.writeheader()
        for row in all_rows:
            writer.writerow({k: '; '.join(row[k]) if k == 'warnings' else row.get(k)
                             for k in FIELDS})
    if errors:
        (args.out / 'erros.txt').write_text('\n'.join(errors) + '\n', encoding='utf-8')
    print(f'Resumos: {args.out}; analisados={len(all_rows)}, erros={len(errors)}')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
