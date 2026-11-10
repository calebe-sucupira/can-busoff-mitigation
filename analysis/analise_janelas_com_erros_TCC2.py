#!/usr/bin/env python3
"""Analisa crescimento/recuperacao do TEC nos 18 ensaios ALTO sem alterar os ZIPs."""
import argparse
import csv
import io
import json
import statistics
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

RUNS = (155, 156, 160, 163, 165, 170, 173, 174, 178, 181, 183, 188,
        191, 192, 193, 194, 195, 196)

def extract(zip_dir):
    out = []
    for run in RUNS:
        with zipfile.ZipFile(zip_dir / f'run_{run}_injection.zip') as z:
            meta = json.loads(z.read('metadata.json'))
            qc = json.loads(z.read('qc.json'))
            if meta['planned']['profile'] != 'ALTO' or qc['valid'] is not True:
                raise ValueError(f'Run {run} nao e ALTO valido')
            mode = meta['condition']
            src = csv.DictReader(io.StringIO(z.read('node_a.csv').decode('utf-8-sig')))
            samples = []
            for line in src:
                if line['event'] != 'SAMPLE':
                    continue
                detail = dict(part.split('=', 1) for part in line['detail'].split(';') if '=' in part)
                samples.append((int(line['timestamp_us']), int(line['tec']),
                                int(detail['errors']), int(detail['tx_ok'])))
        for a, b in zip(samples, samples[1:]):
            dt_ms = (b[0] - a[0]) / 1000
            if not 80 <= dt_ms <= 120:
                continue
            out.append({
                'run': run, 'modo': mode, 'inicio_us': a[0], 'fim_us': b[0],
                'dt_ms': round(dt_ms, 3), 'tec_inicial': a[1], 'tec_final': b[1],
                'delta_tec': b[1] - a[1], 'delta_erros': b[2] - a[2],
                'delta_tx_ok': b[3] - a[3],
            })
    return out

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parent.parent
    ap.add_argument('--zip-dir', type=Path, default=root / 'data' / 'zips')
    ap.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent / 'analise_temporal_tec')
    args = ap.parse_args()
    rows = extract(args.zip_dir)
    critical = [r for r in rows if r['tec_inicial'] >= 96 and r['delta_erros'] > 0]
    if not critical:
        raise RuntimeError('Nenhuma janela critica encontrada')
    for r in critical:
        r['saldo_aproximado'] = 8 * r['delta_erros'] - r['delta_tx_ok']
        r['residuo'] = r['delta_tec'] - r['saldo_aproximado']
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_csv = args.output_dir / 'janelas_tec_alto_com_erros.csv'
    with out_csv.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(critical[0]))
        writer.writeheader()
        writer.writerows(critical)
    print(f'Janelas regulares nos 18 ensaios: {len(rows)}')
    print(f'Janelas com TEC inicial >=96 e novos eventos ERROR: {len(critical)}')
    report = ['# Janelas com erros e TEC elevado — ensaios ALTO', '',
              'Base: 12 ensaios oficiais ALTO e Runs 191–196. Janelas de 80–120 ms, '
              'selecionadas por TEC inicial >= 96 e incremento do contador `errors`.', '',
              '| Modo | Janelas | TEC sobe | TEC cai | Correspondencia com 8×Δerrors−Δtx_ok |',
              '|---|---:|---:|---:|---:|']
    for mode in ('REFERENCIA', 'ADAPTATIVO'):
        part = [r for r in critical if r['modo'] == mode]
        up = sum(r['delta_tec'] > 0 for r in part)
        down = sum(r['delta_tec'] < 0 for r in part)
        match = sum(r['residuo'] == 0 for r in part)
        print(f'{mode}: {len(part)} janelas, TEC sobe {up}, cai {down}, relacao aproximada exata {match}/{len(part)}')
        report.append(f'| {mode} | {len(part)} | {up} | {down} | {match}/{len(part)} |')
    report += ['', '## Janelas com exatamente um incremento de `errors`', '',
               '| Modo | Janelas | Mediana Δtx_ok | Mediana ΔTEC |',
               '|---|---:|---:|---:|']
    for mode in ('REFERENCIA', 'ADAPTATIVO'):
        part = [r for r in critical if r['modo'] == mode and r['delta_erros'] == 1]
        if part:
            tx_med = statistics.median(r['delta_tx_ok'] for r in part)
            tec_med = statistics.median(r['delta_tec'] for r in part)
            print(f'{mode} - 1 incremento ERROR: {len(part)} janelas; mediana TX={tx_med:g}; mediana dTEC={tec_med:g}')
            report.append(f'| {mode} | {len(part)} | {tx_med:g} | {tec_med:g} |')
    report += ['', '## Interpretacao e limites', '',
               '- As janelas sao **correlacionadas**, nao repeticoes independentes. A comparacao entre modos nao isola o efeito causal do algoritmo.',
               '- `errors` e um contador de eventos fornecido pelo firmware, nao uma medicao direta da quantidade de bits CAN corrompidos.',
               '- A relacao `ΔTEC ≈ 8×Δerrors − Δtx_ok` resume um padrao **observado neste subconjunto**, nao deve ser tratada como lei geral do CAN.',
               '- Os valores de TEC foram amostrados; eventos intermediarios podem nao aparecer no log. Verificar `STATE_CHANGE` para Bus-Off.',
               '- Nao usar essas correlacoes para validar eletricamente um perfil de injecao mais intenso.',
               '- Os ensaios nao demonstram mitigacao de Bus-Off: o estado nao ocorreu no conjunto analisado.',
               '', f'CSV detalhado: `{out_csv.name}`.', '']
    out_md = args.output_dir / 'RELATORIO_JANELAS_TEC_COM_ERROS.md'
    out_md.write_text('\n'.join(report), encoding='utf-8')
    print(f'Arquivos: {out_csv} e {out_md}')

if __name__ == '__main__':
    main()
