#!/usr/bin/env python3
"""Auditoria observacional dos logs CAN existentes (nenhum acesso ao hardware).

Uso: python3 auditar_temporal_CAN_60.py --zips-dir data/zips
Foco: eventos ERROR, conclusão TX, amostras de TEC, alertas de TX pendente.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import io
import json
import math
import re
import statistics
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

RUNS = (*range(153, 189), *range(197, 221))
PROFILE_ORDER = ('BAIXO', 'MEDIO_V2', 'ALTO')
POLICIES = ('REFERENCIA', 'ADAPTATIVO')
FIELDS = [
    'run', 'block', 'profile', 'policy', 'qc_valid', 'injection_s',
    'a_error_inj', 'a_tx_success_inj', 'a_tx_failed_inj',
    'a_tx_rejected_inj', 'a_pending_warning_inj', 'a_state_change_inj',
    'a_busoff_detected_inj', 'a_samples_inj', 'tec_max_sample_inj',
    'tec_max_peak_recorded_inj', 'tec_rise_intervals',
    'tec_fall_intervals', 'tec_unchanged_intervals',
    'tec_rise_with_error_intervals', 'tec_fall_with_tx_intervals',
    'service_samples', 'service_mean_us', 'service_p95_us',
    'service_p99_us', 'service_max_us',
    'tx_with_error_during_service', 'tx_with_error_pct',
    'max_error_alerts_during_one_service',
    'errors_during_completed_services', 'max_error_alerts_between_tx_success',
    'bad_data_rows_a',
]


def detail_map(value: str) -> dict[str, str]:
    return dict(part.split('=', 1) for part in value.split(';') if '=' in part)


def parse_log(text: str):
    events = []
    bad = 0
    for line in text.splitlines():
        m = re.match(r'^(\d+)\t(DATA,.*)$', line)
        if not m:
            continue
        try:
            fields = next(csv.reader([m.group(2)]))
            if len(fields) < 9 or fields[0] != 'DATA':
                bad += 1
                continue
            events.append({
                'host_ns': int(m.group(1)),
                'device_us': int(fields[1]),
                'event': fields[2],
                'sequence': fields[3],
                'tec': fields[4],
                'rec': fields[5],
                'state': fields[6],
                'mode': fields[7],
                'detail': ','.join(fields[8:]),
            })
        except (ValueError, csv.Error, IndexError):
            bad += 1
    return events, bad


def percentile(values, pct):
    if not values:
        return None
    a = sorted(values)
    position = (len(a) - 1) * pct / 100
    i = math.floor(position)
    j = math.ceil(position)
    return a[i] + (position - i) * (a[j] - a[i])


def mean_or_none(values):
    return statistics.mean(values) if values else None


def stringify(value):
    if value is None:
        return ''
    if isinstance(value, float):
        return f'{value:.5f}'
    return value


def inspect(path: Path):
    expected_run = int(re.search(r'run_(\d+)_injection\.zip$', path.name).group(1))
    with zipfile.ZipFile(path) as z:
        required = {'metadata.json', 'qc.json', 'pico.log', 'node_a.log'}
        missing = required.difference(z.namelist())
        if missing:
            raise ValueError(f'ZIP sem arquivos essenciais: {sorted(missing)}')
        if z.testzip() is not None:
            raise ValueError('ZIP com CRC inválido')
        metadata = json.loads(z.read('metadata.json'))
        qc = json.loads(z.read('qc.json'))
        if metadata.get('run') != expected_run or qc.get('run') != expected_run:
            raise ValueError('Número de run não corresponde a metadata/QC')
        if qc.get('valid') is not True:
            raise ValueError('QC não aprovado')
        pico, bad_p = parse_log(z.read('pico.log').decode('utf-8', 'replace'))
        a, bad_a = parse_log(z.read('node_a.log').decode('utf-8', 'replace'))
    phase = {}
    for e in pico:
        if e['event'] in ('NOISE_START', 'NOISE_END'):
            if e['event'] in phase:
                raise ValueError(f'Evento {e["event"]} duplicado')
            phase[e['event']] = e['host_ns']
    if 'NOISE_START' not in phase or 'NOISE_END' not in phase:
        raise ValueError('Fases NOISE_START/NOISE_END ausentes no log do Pico')
    start, end = phase['NOISE_START'], phase['NOISE_END']
    if end <= start:
        raise ValueError('Ordem das fases inválida')
    events = [e for e in a if start <= e['host_ns'] < end]
    event_counts = Counter(e['event'] for e in events)

    samples = sorted((e for e in events if e['event'] == 'SAMPLE'), key=lambda e: e['device_us'])
    errors = sorted(e['device_us'] for e in events if e['event'] == 'ERROR')
    success = sorted((e for e in events if e['event'] == 'TX_SUCCESS'), key=lambda e: e['device_us'])
    success_times = [e['device_us'] for e in success]

    services = []
    overlaps = []
    for e in success:
        data = detail_map(e['detail'])
        if 'latency_us' not in data or 'wait_us' not in data:
            continue
        try:
            service_us = int(data['latency_us']) - int(data['wait_us'])
        except ValueError:
            continue
        if service_us < 0:
            continue
        services.append(service_us)
        left = e['device_us'] - service_us
        count = bisect.bisect_right(errors, e['device_us']) - bisect.bisect_left(errors, left)
        overlaps.append(count)

    max_errors_between_tx = 0
    pending_count = 0
    # Eventos ordenados pelo timestamp do microcontrolador, não pela chegada USB.
    for e in sorted(events, key=lambda e: (e['device_us'], e['host_ns'])):
        if e['event'] == 'ERROR':
            pending_count += 1
            max_errors_between_tx = max(max_errors_between_tx, pending_count)
        elif e['event'] in ('TX_SUCCESS', 'TX_FAILED'):
            pending_count = 0

    rise = fall = flat = rise_w_error = fall_w_tx = 0
    for previous, current in zip(samples, samples[1:]):
        delta = int(current['tec']) - int(previous['tec'])
        s, t = previous['device_us'], current['device_us']
        errors_between = bisect.bisect_right(errors, t) - bisect.bisect_right(errors, s)
        tx_between = bisect.bisect_right(success_times, t) - bisect.bisect_right(success_times, s)
        if delta > 0:
            rise += 1
            rise_w_error += bool(errors_between)
        elif delta < 0:
            fall += 1
            fall_w_tx += bool(tx_between)
        else:
            flat += 1

    state_events = [e for e in events if e['event'] == 'STATE_CHANGE']
    busoff = any(e['detail'].endswith('->BUS_OFF') for e in state_events) or any(
        e['state'] == 'BUS_OFF' for e in samples)
    peak_values = []
    for e in samples:
        d = detail_map(e['detail'])
        try:
            peak_values.append(int(d.get('tec_peak', e['tec'])))
        except ValueError:
            pass

    return {
        'run': expected_run,
        'block': metadata.get('block', ''),
        'profile': metadata.get('planned', {}).get('profile', ''),
        'policy': metadata.get('condition', ''),
        'qc_valid': qc.get('valid'),
        'injection_s': qc.get('injection_actual_s', ''),
        'a_error_inj': event_counts['ERROR'],
        'a_tx_success_inj': event_counts['TX_SUCCESS'],
        'a_tx_failed_inj': event_counts['TX_FAILED'],
        'a_tx_rejected_inj': event_counts['TX_REJECTED'],
        'a_pending_warning_inj': event_counts['PENDING_WARNING'],
        'a_state_change_inj': event_counts['STATE_CHANGE'],
        'a_busoff_detected_inj': int(busoff),
        'a_samples_inj': len(samples),
        'tec_max_sample_inj': max((int(e['tec']) for e in samples), default=None),
        'tec_max_peak_recorded_inj': max(peak_values, default=None),
        'tec_rise_intervals': rise,
        'tec_fall_intervals': fall,
        'tec_unchanged_intervals': flat,
        'tec_rise_with_error_intervals': rise_w_error,
        'tec_fall_with_tx_intervals': fall_w_tx,
        'service_samples': len(services),
        'service_mean_us': mean_or_none(services),
        'service_p95_us': percentile(services, 95),
        'service_p99_us': percentile(services, 99),
        'service_max_us': max(services, default=None),
        'tx_with_error_during_service': sum(n > 0 for n in overlaps),
        'tx_with_error_pct': (100 * sum(n > 0 for n in overlaps) / len(overlaps)) if overlaps else None,
        'max_error_alerts_during_one_service': max(overlaps, default=None),
        'errors_during_completed_services': sum(overlaps),
        'max_error_alerts_between_tx_success': max_errors_between_tx,
        'bad_data_rows_a': bad_a,
    }


def write_csv(path: Path, rows, fields):
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(({key: stringify(row.get(key)) for key in fields} for row in rows))


def aggregate(rows):
    aggregated = []
    by_group = defaultdict(list)
    for r in rows:
        by_group[(r['profile'], r['policy'])].append(r)
    for profile in PROFILE_ORDER:
        for policy in POLICIES:
            batch = by_group.get((profile, policy), [])
            if not batch:
                continue
            metrics = (
                'a_error_inj', 'a_tx_success_inj', 'a_pending_warning_inj',
                'tec_max_peak_recorded_inj', 'service_mean_us',
                'service_p95_us', 'service_p99_us', 'service_max_us',
                'tx_with_error_pct', 'tec_rise_intervals', 'tec_fall_intervals',
                'tec_rise_with_error_intervals', 'tec_fall_with_tx_intervals',
                'max_error_alerts_during_one_service',
                'max_error_alerts_between_tx_success',
            )
            rec = {'profile': profile, 'policy': policy, 'runs': len(batch)}
            for metric in metrics:
                rec[f'mean_{metric}'] = mean_or_none([r[metric] for r in batch if r[metric] is not None])
            rec['total_pending_warning'] = sum(r['a_pending_warning_inj'] for r in batch)
            rec['total_busoff'] = sum(r['a_busoff_detected_inj'] for r in batch)
            aggregated.append(rec)
    return aggregated


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--zips-dir', type=Path, default=Path('data/zips'))
    ap.add_argument('--out-dir', type=Path, default=Path('analysis/auditoria_temporal_CAN_60'))
    ap.add_argument('--allow-partial', action='store_true', help='Permite processar apenas ZIPs presentes')
    ap.add_argument('--reference-csv', type=Path, default=None,
                    help='CSV consolidado para conferir contagens de ERROR, TX_SUCCESS e pico TEC')
    args = ap.parse_args()
    missing = [run for run in RUNS if not (args.zips_dir / f'run_{run}_injection.zip').is_file()]
    if missing and not args.allow_partial:
        ap.error(f'Faltam {len(missing)} ZIPs: {missing}. Use --zips-dir correto ou --allow-partial.')
    results = []
    failures = []
    for run in RUNS:
        zip_path = args.zips_dir / f'run_{run}_injection.zip'
        if not zip_path.exists():
            continue
        try:
            r = inspect(zip_path)
            results.append(r)
            print(f'Run {run:03d} {r["profile"]:8} {r["policy"]:10} '
                  f'ERROR={r["a_error_inj"]:3} TX_OK={r["a_tx_success_inj"]:4} '
                  f'PEND_WARN={r["a_pending_warning_inj"]:3} '
                  f'TECp={str(r["tec_max_peak_recorded_inj"]):>3} '
                  f'serv_p99_us={str(round(r["service_p99_us"])) if r["service_p99_us"] is not None else "-":>6}')
        except (KeyError, ValueError, OSError, zipfile.BadZipFile) as exc:
            failures.append((run, str(exc)))
            print(f'FALHA ao analisar Run {run}: {exc}')
    if not results:
        ap.error('Nenhum ZIP processado com sucesso')
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / 'metricas_temporais_por_run.csv', results, FIELDS)
    groups = aggregate(results)
    if groups:
        write_csv(args.out_dir / 'resumo_temporal_por_grupo.csv', groups, list(groups[0]))
    differences = []
    if args.reference_csv:
        if not args.reference_csv.is_file():
            ap.error(f'CSV de referência não encontrado: {args.reference_csv}')
        with args.reference_csv.open(encoding='utf-8-sig', newline='') as f:
            reference = {int(r['run']): r for r in csv.DictReader(f)}
        checks = {
            'a_error_alerts_40s': 'a_error_inj',
            'a_tx_success_40s': 'a_tx_success_inj',
            'tec_peak_inj': 'tec_max_peak_recorded_inj',
        }
        for row in results:
            baseline = reference.get(row['run'])
            if not baseline:
                differences.append((row['run'], 'run ausente no consolidado'))
                continue
            for source_field, observed_field in checks.items():
                if source_field in baseline and str(baseline[source_field]):
                    try:
                        expected = int(float(baseline[source_field]))
                        observed = int(row[observed_field])
                    except (TypeError, ValueError):
                        differences.append((row['run'], f'campo inválido: {source_field}'))
                        continue
                    if expected != observed:
                        differences.append((row['run'], f'{source_field}: esperado {expected}, encontrado {observed}'))
    coverage_ok = not missing and not failures and not differences and len(results) == 60
    with (args.out_dir / 'AUDITORIA_STATUS.txt').open('w', encoding='utf-8') as f:
        f.write(f'Runs analisadas: {len(results)}/60\n')
        f.write(f'Com cobertura integral: {coverage_ok}\n')
        f.write(f'ZIPs ausentes: {missing}\n')
        f.write(f'Falhas: {failures}\n')
        f.write(f'Divergências com CSV consolidado: {differences}\n')
        f.write('AVISO: coincidencia temporal ERROR/servico nao conta tentativas ou retransmissoes CAN.\n')
        f.write('Limites das fases usam timestamps do host; intervalos do servico e TEC usam relogio do ESP32.\n')
        f.write('Estatisticas sao observacionais e descritivas; usar runs como unidades para comparacao.\n')
    print('\nARQUIVOS:', args.out_dir.resolve())
    print('Cobertura integral:', coverage_ok)
    if missing:
        print('Ausentes:', missing)
    if failures:
        print('Falhas:', failures)
    if differences:
        print('DIVERGENCIAS com CSV consolidado:', differences)
    return 0 if (coverage_ok or (args.allow_partial and not failures and not differences)) else 1


if __name__ == '__main__':
    raise SystemExit(main())
