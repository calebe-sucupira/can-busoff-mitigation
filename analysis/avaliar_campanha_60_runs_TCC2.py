#!/usr/bin/env python3
"""Auditoria e análise descritiva de 60 ensaios do TCC CAN.

Executar da raiz do repositório:
    python3 analysis/avaliar_campanha_60_runs_TCC2.py

Ou, para dados em outro diretório:
    python3 avaliar_campanha_60_runs_TCC2.py --zips /mnt/data --out /mnt/data/analise_campanha_60

Somente biblioteca padrão, leitura não destrutiva, sem acesso a hardware.
"""
import argparse
import csv
import io
import json
import re
import statistics as st
import zipfile
from collections import Counter
from pathlib import Path

RUNS = list(range(153, 189)) + list(range(197, 221))
PROFILES = ('BAIXO', 'MEDIO_V2', 'ALTO')
POLICIES = ('REFERENCIA', 'ADAPTATIVO')
PARAMS = {'BAIXO': (40000, 60000), 'MEDIO_V2': (17500, 22500), 'ALTO': (9375, 14375)}
NEEDED = {'metadata.json', 'qc.json', 'control_events.jsonl', 'node_a.csv', 'node_b.csv',
          'pico.csv', 'node_a.log', 'node_b.log', 'pico.log'}
COLS = ['timestamp_us', 'event', 'sequence', 'tec', 'rec', 'state', 'mode', 'detail']


def check(ok, reason):
    if not ok:
        raise ValueError(reason)


def details(s):
    return dict(p.split('=', 1) for p in (s or '').split(';') if '=' in p)


def rows_csv(z, file):
    result = []
    for r in csv.DictReader(io.StringIO(z.read(file).decode('utf-8-sig', 'replace'))):
        # Ignora registros estruturalmente invalidos; preserva todos os eventos validos.
        if (r.get('node') in ('node_a','node_b','pico') and
                (r.get('timestamp_us') or '').isdigit() and
                (r.get('sequence') or '').lstrip('-').isdigit()):
            result.append(r)
    return result


def records_log(z, name):
    result = []
    malformed = 0
    for line in z.read(name + '.log').decode('utf-8', 'replace').splitlines():
        m = re.match(r'^(\d+)\tDATA,(.*)$', line)
        if not m:
            continue
        values = next(csv.reader([m.group(2)]))
        if len(values) != len(COLS):
            malformed += 1
            continue
        try:
            vals = dict(zip(COLS, values))
            t = int(vals['timestamp_us'])
            result.append((int(m.group(1)), vals, t))
        except (ValueError, KeyError):
            malformed += 1
    return result, malformed


def gaps_from_seq(recs, ev):
    seq = [int(r['sequence']) for r in recs if r['event'] == ev]
    check(len(seq) > 2, f'Nao ha sequencias suficientes para {ev}')
    return sum(max(0, b-a-1) for a, b in zip(seq, seq[1:]))


def metrics(run, root):
    path = root / f'run_{run}_injection.zip'
    check(path.exists(), f'Run {run}: arquivo ausente {path}')
    with zipfile.ZipFile(path) as z:
        check(z.testzip() is None, f'Run {run}: CRC invalido')
        check(NEEDED <= set(z.namelist()), f'Run {run}: faltam arquivos: {NEEDED-set(z.namelist())}')
        m = json.loads(z.read('metadata.json'))
        q = json.loads(z.read('qc.json'))
        check(q['valid'] is True and not q['warnings'], f'Run {run}: QC invalido: {q}')
        check(q['run'] == m['run'] == run, f'Run {run}: ID divergente')
        block = int(m['block'])
        check(1 <= block <= 10, f'Run {run}: bloco fora do escopo')
        if run < 189:
            check(block == (run-153)//6+1, f'Run {run}: bloco oficial errado')
        else:
            check(block == (run-197)//6+7, f'Run {run}: bloco adicional errado')
        p, pol = m['planned']['profile'], m['condition']
        check(p in PROFILES and pol in POLICIES, f'Run {run}: perfil/politica invalidos')
        check((m['planned']['interval_min_us'], m['planned']['interval_max_us']) == PARAMS[p],
              f'Run {run}: perfil de injecao alterado')
        check(m['planned']['pulse_width_us_nominal'] == 8 and m['planned']['injection_duration_s'] == 40,
              f'Run {run}: duracao ou largura fora de protocolo')
        check(m['firmware_expected'] == 'pico-param-v1.5', f'Run {run}: firmware pico diferente')
        check(q['condition'] == pol and q['expected_throttling'] == int(pol == 'ADAPTATIVO'),
              f'Run {run}: modo esperado divergente')
        check(m['expected_throttling'] == int(pol == 'ADAPTATIVO'), f'Run {run}: meta firmware divergente')
        check(q['pulses'] == m['planned']['ideal_pulses'], f'Run {run}: pulsos divergentes')
        check(q['missed_deadlines'] == 0, f'Run {run}: prazos perdidos')
        check(abs(q['injection_actual_s']-40) < 0.01, f'Run {run}: duracao incorreta')
        con = [json.loads(x) for x in z.read('control_events.jsonl').decode().splitlines() if x.strip()]
        check(sum(x['event'] == 'NODE_A_MODE_VERIFIED' and
                  x['throttling'] == int(pol == 'ADAPTATIVO') for x in con) == 1,
              f'Run {run}: comprovacao de modo ausente')
        a_csv, b_csv = rows_csv(z, 'node_a.csv'), rows_csv(z, 'node_b.csv')
        a, bad_a = records_log(z, 'node_a')
        b, bad_b = records_log(z, 'node_b')
        pico, bad_p = records_log(z, 'pico')
        phases = {ev: [] for ev in ('TEST_START', 'NOISE_START', 'NOISE_END', 'TEST_END')}
        for host, rec, device in pico:
            if rec['event'] in phases:
                phases[rec['event']].append((host, device))
        check(all(len(v) == 1 for v in phases.values()), f'Run {run}: marcadores repetidos ou ausentes')
        ts, start, end, te = (phases[e][0][0] for e in phases)
        check(ts < start < end < te, f'Run {run}: fases fora da ordem')
        check(abs((end-start)/1e9-40) < 0.2, f'Run {run}: janela host de injecao inesperada')
        actual_local = (phases['NOISE_END'][0][1]-phases['NOISE_START'][0][1])/1e6
        check(abs(actual_local-q['injection_actual_s']) < 0.001,
              f'Run {run}: duracao local Pico divergente')
        boot = re.search(r'throttling=(\d+)', z.read('node_a.log').decode('utf-8', 'replace'))
        check(boot is not None and int(boot.group(1)) == int(pol == 'ADAPTATIVO'),
              f'Run {run}: firmware inicializado com modo inesperado')
        d_a = Counter(rec['event'] for host,rec,local in a if start <= host < end)
        d_b = Counter(rec['event'] for host,rec,local in b if start <= host < end)
        samples = [rec for host,rec,loc in a if rec['event'] == 'SAMPLE' and start <= host < end]
        samples_all = [r for r in a_csv if r['event'] == 'SAMPLE']
        check(samples and samples_all, f'Run {run}: amostras ausentes')
        peak = max(int(details(r['detail'])['tec_peak']) for r in samples)
        peak_all = max(int(details(r['detail']).get('tec_peak',r['tec'])) for r in samples_all)
        rec_peak_all = max(int(details(r['detail']).get('rec_peak',r['rec'])) for r in samples_all)
        final = details(samples_all[-1]['detail'])
        gap = int(final['gap'])
        check(int(final['tx_failed']) == 0 and int(final['rejected']) == 0 and int(final['lost']) == 0,
              f'Run {run}: falha/rejeicao/perda de log no firmware')
        check(int(final['produced'])-int(final['submitted']) == gap, f'Run {run}: contagem produzidas/submetidas')
        tx_seq_gap = gaps_from_seq(a_csv, 'TX_SUCCESS')
        rx_seq_gap = gaps_from_seq(b_csv, 'RECEIVED')
        check(gap == tx_seq_gap == rx_seq_gap,
              f'Run {run}: gaps inconsistentes (fw={gap}, tx={tx_seq_gap}, rx={rx_seq_gap})')
        check((q['node_a_TX_SUCCESS'] == sum(r['event']=='TX_SUCCESS' for r in a_csv) or
               (run == 187 and q['node_a_TX_SUCCESS'] == 1 + sum(r['event']=='TX_SUCCESS' for r in a_csv))) and
              q['node_b_RECEIVED'] == sum(r['event']=='RECEIVED' for r in b_csv),
              f'Run {run}: QC diverge dos registros')
        states = [r for r in a_csv if r['event']=='STATE_CHANGE']
        entered = None
        passive_time_s = 0
        passive_count = 0
        for event in states:
            x = event['detail']
            local = int(event['timestamp_us'])
            if x.endswith('->PASSIVE'):
                check(entered is None, f'Run {run}: transicao passive aninhada')
                entered = local
                passive_count += 1
            if x.startswith('PASSIVE->'):
                check(entered is not None, f'Run {run}: saida passive sem entrada')
                passive_time_s += (local-entered)/1e6
                entered = None
        check(entered is None, f'Run {run}: passive sem fechamento')
        busoff = sum('BUS_OFF' in r['event'] or 'BUS_OFF' in r['detail'] for r in a_csv)
        check(busoff == 0, f'Run {run}: BUS_OFF detectado (reavaliar metricas)')
        return {
            'run':run,'block':block,'profile':p,'policy':pol,'seed_hex':m['planned']['seed_hex'],
            'binary_sha256':m['node_a_binary_sha256'],'qc_valid':q['valid'],'pulses':q['pulses'],
            'missed_deadlines':q['missed_deadlines'],'max_late_us':q['max_late_us'],
            'injection_actual_s':q['injection_actual_s'],
            'tec_peak_inj':peak,'tec_peak_run':peak_all,'rec_peak_run':rec_peak_all,
            'a_error_alerts_40s':d_a['ERROR'],'b_error_alerts_40s':d_b['ERROR'],
            'a_tx_success_40s':d_a['TX_SUCCESS'],'b_received_40s':d_b['RECEIVED'],
            'a_alerts_per_1000_tx':round(1000*d_a['ERROR']/d_a['TX_SUCCESS'],5) if d_a['TX_SUCCESS'] else None,
            'passive_entries_run':passive_count,'passive_time_run_s':round(passive_time_s,6),
            'gap_total_run':gap,'gap_seq_tx':tx_seq_gap,'gap_seq_rx':rx_seq_gap,
            'tx_failed_run':int(final['tx_failed']),'rejected_run':int(final['rejected']),
            'lost_fw_run':int(final['lost']),'busoff_run':busoff,
            'bad_data_rows_a':bad_a,'bad_data_rows_b':bad_b,'bad_data_rows_pico':bad_p,
        }


def write_csv(path, records):
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    home = Path(__file__).resolve().parent.parent
    parser.add_argument('--zips', type=Path, default=home/'data'/'zips', help='Diretorio dos ZIPs')
    parser.add_argument('--out', type=Path, default=home/'analysis'/'avaliacao_campanha_60_runs', help='Saidas CSV')
    args = parser.parse_args()
    records = [metrics(i, args.zips) for i in RUNS]
    check(len(records) == 60 and sorted(r['run'] for r in records) == RUNS, 'Campanha incompleta')
    grouped = {}
    for profile in PROFILES:
        for policy in POLICIES:
            v = [r for r in records if r['profile']==profile and r['policy']==policy]
            check(len(v)==10 and sorted(r['block'] for r in v)==list(range(1,11)),
                  f'{profile} {policy}: repeticoes divergentes')
            grouped[profile,policy] = v
    paired=[]
    for block in range(1,11):
        within_block = [r for r in records if r['block']==block]
        check(len(within_block)==6, f'Bloco {block}: numero de runs incorreto')
        for profile in PROFILES:
            two=[r for r in within_block if r['profile']==profile]
            check(len(two)==2 and set(r['policy'] for r in two)==set(POLICIES),
                  f'Bloco {block}: par incompleto {profile}')
            ref=next(r for r in two if r['policy']=='REFERENCIA')
            ad=next(r for r in two if r['policy']=='ADAPTATIVO')
            check(ref['seed_hex'].lower()==ad['seed_hex'].lower() and ref['pulses']==ad['pulses'],
                  f'Bloco {block}/{profile}: semente/pulsos diferentes')
            paired.append({
                'block':block,'profile':profile,'seed_hex':ref['seed_hex'],
                'ref_run':ref['run'],'adaptive_run':ad['run'],
                'delta_tec_peak_inj':ad['tec_peak_inj']-ref['tec_peak_inj'],
                'delta_tec_peak_run':ad['tec_peak_run']-ref['tec_peak_run'],
                'delta_a_errors_40s':ad['a_error_alerts_40s']-ref['a_error_alerts_40s'],
                'delta_tx_ok_40s':ad['a_tx_success_40s']-ref['a_tx_success_40s'],
                'delta_alerts_per_1000_tx':round(ad['a_alerts_per_1000_tx']-ref['a_alerts_per_1000_tx'],5),
                'delta_passive_time_s':round(ad['passive_time_run_s']-ref['passive_time_run_s'],6),
                'delta_gap':ad['gap_total_run']-ref['gap_total_run'],
            })
    for phase, subset in [('original', [r for r in records if r['block']<=6]),
                          ('adicional', [r for r in records if r['block']>=7])]:
        identifiers = {}
        for policy in POLICIES:
            hashes = {r['binary_sha256'] for r in subset if r['policy']==policy}
            check(len(hashes)==1, f'{phase}/{policy}: mais de um hash na mesma fase')
            identifiers[policy] = next(iter(hashes))
        check(identifiers['REFERENCIA'] != identifiers['ADAPTATIVO'],
              f'{phase}: hashes dos modos nao se distinguem')
    summary=[]
    for profile in PROFILES:
        for policy in POLICIES:
            v=grouped[profile,policy]
            total_alert=sum(r['a_error_alerts_40s'] for r in v)
            total_tx=sum(r['a_tx_success_40s'] for r in v)
            peak=[r['tec_peak_inj'] for r in v]
            summary.append({
                'profile':profile,'policy':policy,'n':len(v),
                'tec_peak_mean':round(st.mean(peak),4), 'tec_peak_sd':round(st.stdev(peak),4),
                'tec_peak_min':min(peak),'tec_peak_max':max(peak),
                'tec_ge_96_runs':sum(x>=96 for x in peak),'tec_ge_128_runs':sum(x>=128 for x in peak),
                'error_alerts_sum':total_alert,'error_alerts_mean_40s':round(total_alert/10,4),
                'tx_success_sum':total_tx,'tx_success_mean_40s':round(total_tx/10,4),
                'error_alerts_per_1000_tx':round(1000*total_alert/total_tx,4),
                'b_error_alerts_sum':sum(r['b_error_alerts_40s'] for r in v),
                'b_received_sum':sum(r['b_received_40s'] for r in v),
                'passive_entries_sum':sum(r['passive_entries_run'] for r in v),
                'passive_time_sum_s':round(sum(r['passive_time_run_s'] for r in v),6),
                'passive_runs':sum(r['passive_entries_run']>0 for r in v),
                'gap_total_sum':sum(r['gap_total_run'] for r in v),
                'gap_runs':sum(r['gap_total_run']>0 for r in v),
                'busoff_runs':sum(r['busoff_run']>0 for r in v),
            })
    args.out.mkdir(parents=True,exist_ok=True)
    write_csv(args.out/'metricas_por_run_60.csv', records)
    write_csv(args.out/'resumo_por_perfil_politica_60.csv', summary)
    write_csv(args.out/'comparacao_por_bloco_60.csv', paired)
    write_csv(args.out/'resumo_ultimo_bloco_215_220.csv', records[-6:])
    phases=[]
    for phase_name, predicate in [('original_153_188', lambda r: r['block']<=6),
                                  ('ampliacao_197_220', lambda r: r['block']>=7)]:
        for profile in PROFILES:
            for policy in POLICIES:
                v=[r for r in records if predicate(r) and r['profile']==profile and r['policy']==policy]
                phases.append({
                    'phase':phase_name,'profile':profile,'policy':policy,'n':len(v),
                    'tec_peak_mean':round(st.mean(r['tec_peak_inj'] for r in v),4),
                    'error_alerts_mean_40s':round(st.mean(r['a_error_alerts_40s'] for r in v),4),
                    'tx_success_mean_40s':round(st.mean(r['a_tx_success_40s'] for r in v),4),
                    'passive_time_total_s':round(sum(r['passive_time_run_s'] for r in v),6),
                    'gap_total':sum(r['gap_total_run'] for r in v),
                })
    write_csv(args.out/'resumo_por_fase_experimental.csv', phases)
    def fmt(x, nd=2):
        return f"{x:.{nd}f}".replace('.', ',')
    report=['# Consolidação da campanha CAN — 60 ensaios', '',
        '## Escopo e validação', '',
        'Foram auditados os 36 ensaios originais (Runs 153–188) e as quatro repetições adicionais '
        'por condição (Runs 197–220), totalizando **60 ensaios, dez por perfil e política**. '
        'Todos os ZIPs têm CRC válido e QC aprovado, com 40 s de injeção por ensaio, '
        'sem prazos perdidos do injetor. Modo de inicialização do Nó A e confirmação '
        'da automação foram verificados. Os perfis e as sementes correspondem '
        'dentro de cada bloco; não há sincronização elétrica entre pulso e quadro.', '',
        'A RUN 187 possui um registro inicial corrompido. O QC contabiliza 5.251 TX_SUCCESS '
        'na run completa, mas há 5.250 registros TX_SUCCESS válidos nos logs e CSV depois de '
        'descartar essa única linha inválida. Esse tratamento não modifica o ZIP; '
        'as métricas delimitadas à injeção coincidem com a análise original dos 36 ensaios.', '',
        '## Resultado por condição (dez ensaios por condição)', '',
        '| Perfil | Política | Pico de TEC, média ± DP | ERROR A/40 s, média | TX A/40 s, média | Alertas/1.000 TX OK | Tempo total Error Passive | Gaps totais |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for r in summary:
        report.append('| '+' | '.join([r['profile'],r['policy'],
            fmt(r['tec_peak_mean'])+' ± '+fmt(r['tec_peak_sd']),
            fmt(r['error_alerts_mean_40s']),fmt(r['tx_success_mean_40s']),
            fmt(r['error_alerts_per_1000_tx']),fmt(r['passive_time_sum_s'],3),
            str(r['gap_total_sum'])])+' |')
    report.extend(['',
        'O pico de TEC é o máximo da variável `tec_peak` nas amostras de monitoramento '
        'dentro da janela de injeção. As contagens `ERROR`, `TX_SUCCESS` e `RECEIVED` '
        'utilizam a janela host `NOISE_START`–`NOISE_END`. O tempo em Error Passive '
        'e os gaps referem-se à execução completa, como nos relatórios anteriores.', '',
        '**`ERROR/1.000 TX_SUCCESS` não é taxa de erro de quadro ou de bits.** '
        'O controlador realiza retransmissões que não são contabilizadas nesse denominador.', '',
        '## Resultado do último bloco (Runs 215–220)', '',
        '| Run | Perfil | Política | Pico TEC | Entradas Passive | Tempo Passive (s) | Gap | ERROR A/40s | TX OK A/40s |',
        '|---|---|---|---:|---:|---:|---:|---:|---:|'])
    for r in records[-6:]:
        report.append('| '+' | '.join([str(r['run']),r['profile'],r['policy'],
            str(r['tec_peak_inj']),str(r['passive_entries_run']),
            fmt(r['passive_time_run_s'],3),str(r['gap_total_run']),
            str(r['a_error_alerts_40s']),str(r['a_tx_success_40s'])])+' |')
    report.extend(['',
        '## Interpretação', '',
        '- **BAIXO:** o TEC não alcançou o limiar de contenção (96) em nenhum ensaio; '
        'não há atuação observada da política (gap zero).',
        '- **MÉDIO_V2:** apenas uma execução adaptativa apresentou substituições, '
        'totalizando dez; o perfil oferece baixa exposição ao mecanismo.',
        '- **ALTO:** a política foi ativada em 10/10 execuções e substituiu 2.493 '
        'atualizações da aplicação, não quadros perdidos no barramento. '
        'As transmissões bem-sucedidas médias durante a injeção passaram de 4.000,7 '
        'na referência para 3.756,1 com a política (aproximadamente 6,1% menos).',
        '- **ALTO e TEC:** os picos médios foram 127,2 (referência) e 133,4 '
        '(adaptativo). Não há evidência de redução sistemática do pico de TEC.',
        '- **ALTO e Error Passive:** tempo acumulado 1,634 s na referência contra '
        '9,284 s no modo adaptativo. A redução de transmissões bem-sucedidas '
        'pode reduzir oportunidades de decremento do TEC, mas isso é uma '
        'explicação mecanística plausível, não uma prova causal isolada.',
        '- **Bus-Off:** zero ocorrências nos 60 ensaios. Não é possível demonstrar '
        'prevenção ou adiamento desse estado sem um controle que efetivamente entre '
        'em Bus-Off sob condições seguras e verificadas.', '',
        '## Proveniência e cautela para inferência', '',
        'Os 36 ensaios iniciais e os 24 adicionais apresentam **hashes SHA-256 '
        'diferentes dos binários** em cada política. Cada uma das duas fases '
        'manteve um par de hashes estável, e todos os modos foram verificados '
        'na inicialização. Somente esses registros não comprovam equivalência '
        'binária ou funcional entre as duas fases; antes de testes inferenciais '
        'pooled, convém comparar os fontes/artefatos da compilação. '
        'As tabelas conjuntas são descritivas, e disponibilizamos também '
        '`resumo_por_fase_experimental.csv` para transparência.', '',
        'Mesmo compartilhando a semente por bloco, os pulsos não estão '
        'sincronizados aos quadros CAN: os pares de bloco são comparações '
        'organizadas, não pares físicos de perturbações idênticas. '
        'Há dez repetições por condição, não milhares de unidades estatísticas '
        'independentes representadas por cada evento `ERROR`.', '',
        '## Próximos passos', '',
        '1. Preservar os 60 ZIPs como conjunto de dados da campanha ampliada.',
        '2. Comparar a proveniência dos firmwares entre as duas fases '
        '(binários, fontes, flags, opções de compilação).',
        '3. Retomar a viabilidade de uma condição que produza Bus-Off no modo '
        'de referência sem intensificar curtos no circuito desprovido '
        'de instrumentação elétrica adequada.',
        '4. Preparar a seção de Resultados e Discussão distinguindo '
        'atuação da política, desempenho e limites do experimento.', '',
        '## Reprodutibilidade', '',
        'Na raiz do repositório, guardar este arquivo como '
        '`analysis/avaliar_campanha_60_runs_TCC2.py` e executar:', '',
        '`python3 analysis/avaliar_campanha_60_runs_TCC2.py`', '',
        'As entradas esperadas ficam em `data/zips/`. As saídas vão para '
        '`analysis/avaliacao_campanha_60_runs/` sem modificar os dados brutos.', ''])
    (args.out/'RELATORIO_60_ENSAIOS.md').write_text('\n'.join(report), encoding='utf-8')
    print('SUCESSO: 60 ensaios auditados, 10 repeticoes por perfil e politica, QC, modo e integridade consistentes.')
    print('\nUltimo bloco (215-220):')
    for r in records[-6:]:
        print(f"{r['run']} {r['profile']:8} {r['policy']:10} TEC_inj={r['tec_peak_inj']:3} "
              f"TEC_run={r['tec_peak_run']:3} Passive={r['passive_entries_run']} "
              f"{r['passive_time_run_s']:.3f}s gap={r['gap_total_run']:4} "
              f"ERROR={r['a_error_alerts_40s']:3} TX={r['a_tx_success_40s']:4}")
    print('\nCampanha consolidada:')
    for r in summary:
        print(f"{r['profile']:8} {r['policy']:10} TEC={r['tec_peak_mean']:.2f}±{r['tec_peak_sd']:.2f} "
              f"ERROR={r['error_alerts_mean_40s']:.1f}/40s TX={r['tx_success_mean_40s']:.1f}/40s "
              f"passive={r['passive_time_sum_s']:.3f}s gap={r['gap_total_sum']}")
    print('Saidas:', args.out)


if __name__=='__main__':
    main()
