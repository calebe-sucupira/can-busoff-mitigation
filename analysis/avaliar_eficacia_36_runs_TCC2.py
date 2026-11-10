#!/usr/bin/env python3
"""Avaliação descritiva reprodutível dos 36 ZIPs oficiais CAN (153–188).

Executar na raiz do repositório:
  python3 analysis/avaliar_eficacia_36_runs_TCC2.py

Somente stdlib. Não modifica os dados brutos e não acessa hardware.
Taxa normalizada de alertas ERROR por TX_SUCCESS NÃO é probabilidade de falha.
"""
from pathlib import Path
import csv
import json
import re
import statistics as st
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'zips'
if not DATA.is_dir() and all((ROOT / f'run_{i}_injection.zip').exists() for i in range(153,189)):
    DATA = ROOT
OUT = ROOT / 'analysis' / 'avaliacao_eficacia_36_runs'
OUT.mkdir(parents=True, exist_ok=True)
FIELDS = ['timestamp_us','event','sequence','tec','rec','state','mode','detail']
PROFILES = ['BAIXO','MEDIO_V2','ALTO']
POLICIES = ['REFERENCIA','ADAPTATIVO']

def parse_details(s):
    return dict(f.split('=',1) for f in (s or '').split(';') if '=' in f)

def load_device(z, dev):
    out = []
    ignored = 0
    for line in z.read(f'{dev}.log').decode('utf-8','replace').splitlines():
        m = re.match(r'^(\d+)\tDATA,(.*)$', line)
        if not m:
            continue
        vals = next(csv.reader([m.group(2)]))
        if len(vals) != len(FIELDS):
            ignored += 1
            continue
        try:
            timestamp = int(vals[0])
        except ValueError:
            ignored += 1
            continue
        rec = dict(zip(FIELDS, vals))
        rec['node'] = dev
        out.append((int(m.group(1)), rec, timestamp))
    return out, ignored

def run_metrics(run):
    file = DATA / f'run_{run}_injection.zip'
    if not file.exists():
        raise RuntimeError(f'ZIP ausente: {file}')
    with zipfile.ZipFile(file) as z:
        assert z.testzip() is None, f'Run {run}: ZIP corrompido'
        metadata = json.loads(z.read('metadata.json'))
        qc = json.loads(z.read('qc.json'))
        assert qc['valid'] and not qc['warnings'], (run, qc)
        assert qc['run'] == metadata['run'] == run
        profile = metadata['planned']['profile']
        policy = metadata['condition']
        assert profile in PROFILES and policy in POLICIES
        assert metadata['planned']['injection_duration_s'] == 40
        assert metadata['planned']['pulse_width_us_nominal'] == 8
        assert metadata['expected_throttling'] == (policy == 'ADAPTATIVO')
        ctrl = [json.loads(x) for x in z.read('control_events.jsonl').decode().splitlines() if x.strip()]
        assert any(c['event'] == 'NODE_A_MODE_VERIFIED' and c['throttling'] == int(policy == 'ADAPTATIVO') for c in ctrl), run
        a, malformed_a = load_device(z, 'node_a')
        b, malformed_b = load_device(z, 'node_b')
        p, malformed_p = load_device(z, 'pico')
        pico = {r['event']: (h, r, local) for h,r,local in p}
        start = pico['NOISE_START'][0]
        end = pico['NOISE_END'][0]
        assert abs((end-start)/1e9-40) < .2  # Recepcao USB pode atrasar, especialmente apos carga serial
        def inside(records,event):
            return [(host, rec,local) for host,rec,local in records if rec['event'] == event and start <= host <= end]
        erra = len(inside(a,'ERROR'))
        errb = len(inside(b,'ERROR'))
        tx = len(inside(a,'TX_SUCCESS'))
        rx = len(inside(b,'RECEIVED'))
        samples = inside(a,'SAMPLE')
        assert samples, run
        peak = max(int(parse_details(rec['detail'])['tec_peak']) for _,rec,_ in samples)
        all_samples = [rec for _,rec,_ in a if rec['event']=='SAMPLE']
        assert all_samples,run
        final = parse_details(all_samples[-1]['detail'])
        gap = int(final['gap'])
        assert int(final['tx_failed']) == 0 and int(final['rejected']) == 0
        assert int(final['lost']) == 0
        assert int(final['produced']) - int(final['submitted']) == gap
        events = [(h,rec,local) for h,rec,local in a if rec['event']=='STATE_CHANGE']
        entered = None
        passive_s = 0
        passive_n = 0
        for _,rec,local in events:
            v = rec['detail']
            if v.endswith('->PASSIVE'):
                assert entered is None,(run,v)
                entered=local
                passive_n+=1
            elif v.startswith('PASSIVE->'):
                assert entered is not None,(run,v)
                passive_s += (local-entered)/1e6
                entered = None
        assert entered is None
        bo = sum(rec['event']=='BUS_OFF' or '->BUS_OFF' in rec['detail'] for _,rec,_ in a)
        assert peak <= 255 and bo == 0, (run,peak,bo)
        assert int(qc['pulses']) == int(metadata['planned']['ideal_pulses'])
        assert int(qc['missed_deadlines']) == 0
        assert abs((pico['NOISE_END'][2]-pico['NOISE_START'][2])/1e6 - qc['injection_actual_s']) < 0.001
        return {
            'run':run,'block':int(metadata['block']),'profile':profile,'policy':policy,
            'seed_hex':metadata['planned']['seed_hex'],'pulse_commands':int(qc['pulses']),
            'tec_peak':peak,'a_error_alerts_40s':erra,'b_error_alerts_40s':errb,
            'a_tx_success_40s':tx,'b_received_40s':rx,
            'a_error_alerts_per_1000_success':round(1000*erra/tx,5) if tx else None,
            'a_error_alerts_per_s':round(erra/40,5),'a_tx_success_hz':round(tx/40,5),
            'passive_entries':passive_n,'passive_time_s':round(passive_s,6),
            'gap_total_run':gap,'busoff':bo,'bad_log_lines_a':malformed_a,
            'bad_log_lines_b':malformed_b,'bad_log_lines_pico':malformed_p,
        }

def fnum(n,digits=2): return f'{n:.{digits}f}'
def percentage(new,old): return 100*(new/old-1) if old else float('nan')
def write_csv(path, rows):
    with path.open('w',newline='',encoding='utf-8') as f:
        w = csv.DictWriter(f,fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

rows = [run_metrics(i) for i in range(153,189)]
assert len(rows) == 36
assert sorted(r['run'] for r in rows)==list(range(153,189))
assert all(sum(r['profile']==p and r['policy']==m for r in rows)==6 for p in PROFILES for m in POLICIES)
assert sum(r['busoff'] for r in rows)==0
write_csv(OUT/'metricas_por_run.csv', rows)

stats = []
for p in PROFILES:
    for m in POLICIES:
        sel = [r for r in rows if r['profile']==p and r['policy']==m]
        tec = [r['tec_peak'] for r in sel]
        errs=sum(r['a_error_alerts_40s'] for r in sel)
        tx=sum(r['a_tx_success_40s'] for r in sel)
        berrs=sum(r['b_error_alerts_40s'] for r in sel)
        rx=sum(r['b_received_40s'] for r in sel)
        stats.append({
            'profile':p,'policy':m,'n':len(sel),
            'tec_peak_mean':round(st.mean(tec),4),'tec_peak_sd':round(st.stdev(tec),4),
            'tec_peak_range':f'{min(tec)}-{max(tec)}',
            'runs_tec_ge_96':sum(r['tec_peak']>=96 for r in sel),
            'runs_tec_ge_128':sum(r['tec_peak']>=128 for r in sel),
            'a_error_alerts_total':errs,'a_error_alerts_mean':round(errs/6,4),
            'a_tx_success_total':tx,'a_tx_success_mean':round(tx/6,4),
            'a_error_alerts_per_1000_tx_success':round(1000*errs/tx,4),
            'b_error_alerts_total':berrs,'b_received_total':rx,
            'b_error_alerts_per_1000_rx':round(1000*berrs/rx,4),
            'passive_entries_total':sum(r['passive_entries'] for r in sel),
            'passive_time_total_s':round(sum(r['passive_time_s'] for r in sel),6),
            'runs_passive':sum(r['passive_entries']>0 for r in sel),
            'gap_total_run':sum(r['gap_total_run'] for r in sel),
            'runs_gap_positive':sum(r['gap_total_run']>0 for r in sel),
            'busoff_total':sum(r['busoff'] for r in sel),
        })
write_csv(OUT/'resumo_por_perfil_politica.csv',stats)
paired=[]
for p in PROFILES:
    for block in range(1,7):
        rr=[r for r in rows if r['profile']==p and r['block']==block]
        assert len(rr)==2 and {r['policy'] for r in rr}==set(POLICIES),(p,block,rr)
        ref=next(r for r in rr if r['policy']=='REFERENCIA')
        adp=next(r for r in rr if r['policy']=='ADAPTATIVO')
        assert ref['seed_hex'].lower()==adp['seed_hex'].lower()
        paired.append({
          'profile':p,'block':block,'seed_hex':ref['seed_hex'],
          'reference_run':ref['run'],'adaptive_run':adp['run'],
          'delta_tec_peak':adp['tec_peak']-ref['tec_peak'],
          'delta_error_alerts':adp['a_error_alerts_40s']-ref['a_error_alerts_40s'],
          'delta_tx_success':adp['a_tx_success_40s']-ref['a_tx_success_40s'],
          'delta_error_alerts_per_1000_tx':round(adp['a_error_alerts_per_1000_success']-ref['a_error_alerts_per_1000_success'],5),
          'delta_passive_time_s':round(adp['passive_time_s']-ref['passive_time_s'],6),
          'delta_gap_total_run':adp['gap_total_run']-ref['gap_total_run'],
        })
write_csv(OUT/'comparacao_por_bloco_mesma_semente.csv',paired)

lines=[]
lines += ['# Avaliação quantitativa da política reativa — campanha oficial (Runs 153–188)', '',
'## Escopo, qualidade e cuidado com as métricas','',
'Análise descritiva dos **36 arquivos brutos ZIP**: três perfis, duas políticas e seis blocos por condição. '
'Cada ensaio tem 40 s de injeção (além de baseline e recuperação). Os ZIPs passaram na validação QC e na verificação de integridade. '
'As contagens de `ERROR`, `TX_SUCCESS` e `RECEIVED` foram extraídas dos logs com carimbo de tempo de captura do computador e delimitadas pelo período `NOISE_START`–`NOISE_END` do Pico. '
'Os picos de TEC foram obtidos dos registros de monitoramento (`tec_peak`).', '',
'**Importante:** `ERROR` é um alerta/evento disponibilizado pelo firmware/controlador. '
'`ERROR` dividido por `TX_SUCCESS` é um **indicador descritivo de alertas por mil transmissões bem-sucedidas**, **não** probabilidade de falha por tentativa, taxa de erro de bits nem perda de quadros. '
'O número de tentativas internas e retransmissões não foi contabilizado por esse denominador. '
'Contagens por modo agregam seis ensaios e não devem ser tratadas como milhares de observações independentes.', '',
'## Comparação por perfil', '',
'| Perfil | Política | Pico TEC (média ± DP) | ERROR A /40 s (média) | TX OK A /40 s (média) | ERROR A/1000 TX OK | Error Passive (s, soma) | Gap (soma da RUN) |',
'|---|---|---:|---:|---:|---:|---:|---:|']
for p in PROFILES:
    for m in POLICIES:
        t=next(x for x in stats if x['profile']==p and x['policy']==m)
        lines.append('| '+ ' | '.join([p,m,fnum(t['tec_peak_mean'])+' ± '+fnum(t['tec_peak_sd']),fnum(t['a_error_alerts_mean']),fnum(t['a_tx_success_mean']),fnum(t['a_error_alerts_per_1000_tx_success']),fnum(t['passive_time_total_s'],3),str(t['gap_total_run'])])+' |')
lines += ['', '## Diferenças agregadas (reativo em relação à referência)', '',
'| Perfil | Eventos ERROR A | TX OK A | Alertas por 1000 TX OK | Picos TEC (média) |',
'|---|---:|---:|---:|---:|']
for p in PROFILES:
    ref=next(x for x in stats if x['profile']==p and x['policy']=='REFERENCIA')
    adp=next(x for x in stats if x['profile']==p and x['policy']=='ADAPTATIVO')
    lines.append('| '+ ' | '.join([p,fnum(percentage(adp['a_error_alerts_total'],ref['a_error_alerts_total']))+'%',fnum(percentage(adp['a_tx_success_total'],ref['a_tx_success_total']))+'%',fnum(percentage(adp['a_error_alerts_per_1000_tx_success'],ref['a_error_alerts_per_1000_tx_success']))+'%',fnum(adp['tec_peak_mean']-ref['tec_peak_mean'])])+' |')
lines += ['', '## Comparações dentro dos seis blocos (mesma semente, sem sincronização elétrica)', '',
'Os blocos usam a mesma semente por perfil, mas os pulsos **não** são sincronizados aos quadros CAN; comparação descritiva não equivale a pareamento físico de cada perturbação.', '',
'| Perfil | Δ TEC pico (adap−ref) por bloco | Δ alertas/1000 TX OK por bloco |',
'|---|---|---|']
for p in PROFILES:
    ps=[x for x in paired if x['profile']==p]
    lines.append('| '+p+' | '+', '.join(f"{r['delta_tec_peak']:+d}" for r in ps)+' | '+', '.join(f"{r['delta_error_alerts_per_1000_tx']:+.2f}" for r in ps)+' |')
lines += ['', '## Interpretação e limitações', '',
'1. **BAIXO:** em todos os ensaios o TEC permaneceu abaixo de 96, e `gap=0`; não houve contenção de submissões. Diferenças entre políticas neste perfil não medem atuação efetiva do controle.',
'2. **MÉDIO_V2:** houve atuação limitada: apenas um dos seis ensaios reativos apresentou atualizações substituídas (`gap` total 10). Por isso, o perfil oferece pouca exposição à política para avaliar sua eficácia.',
'3. **ALTO:** os seis ensaios reativos apresentaram atualização substituída, com queda clara do total de TX bem-sucedidas. A contagem de alertas `ERROR` caiu menos que as transmissões, aumentando ligeiramente o indicador por mil TX bem-sucedidas. Essa normalização **não demonstra** risco causal maior por mensagem.',
'4. **TEC e Error Passive:** o pico médio de TEC no ALTO permaneceu semelhante entre os modos. O tempo acumulado em `Error Passive` foi maior com contenção, consistente com o mecanismo observado em janelas sem erros: menos transmissões bem-sucedidas também significam menos oportunidades de redução do TEC. Isso é uma **explicação plausível**, não prova causal isolada.',
'5. **Bus-Off:** não ocorreu em nenhuma das 36 RUNs. Não se pode afirmar prevenção, adiamento ou redução da frequência de Bus-Off; o modo sem política também não entrou nesse estado.',
'6. **Amostragem e eventos:** alertas e amostras são observáveis pelo firmware, não uma instrumentação elétrica independente. O intervalo de captura tem pequena incerteza nos eventos próximos às transições de fase. A RUN 187 tem uma linha inicial corrompida antes dos dados válidos; o script a ignora sem alterar os arquivos brutos.',
'7. **Inferência estatística:** n=6 por condição, ordem não aleatorizada individualmente e perfis sem sincronização pulso/quadro. Evitar tratar alertas individuais como replicações. As diferenças reportadas são descritivas, e a ausência de diferença sistemática no pico TEC não prova equivalência.',
'8. **Gap:** `gap_total_run` contabiliza atualizações substituídas pela aplicação, não perdas de quadros no barramento. Não é usado como numerador de erro CAN.',
'', '## Próximo passo sugerido', '',
'Construir a seção de Resultados e Discussão com essas tabelas e com as análises temporais já reproduzidas. '
'Para investigar Bus-Off real, seria preciso uma condição de referência que atinja esse estado com segurança elétrica verificável; não intensificar o curto no hardware sem instrumentação adequada. '
'A medição de duração de tarefas do RTOS, se ainda constar entre os objetivos finais, exige uma verificação específica da instrumentação atual.', '',
'## Reprodutibilidade', '',
'Rodar a partir da raiz do projeto: `python3 analysis/avaliar_eficacia_36_runs_TCC2.py`. '
'Entradas: `data/zips/run_153_injection.zip` até `run_188_injection.zip`. '
'Saídas em `analysis/avaliacao_eficacia_36_runs/`. O código usa somente a biblioteca padrão.', '']
(OUT/'RELATORIO_EFICACIA_36_RUNS.md').write_text('\n'.join(lines),encoding='utf-8')
print('36 ZIPs validados; todos os QC válidos. Resultados em:',OUT)
for p in PROFILES:
 for m in POLICIES:
  x=next(a for a in stats if a['profile']==p and a['policy']==m)
  print(p,m,'TEC',x['tec_peak_mean'],'ERROR',x['a_error_alerts_total'],'TX',x['a_tx_success_total'],'PER1K',x['a_error_alerts_per_1000_tx_success'],'PASS',x['passive_time_total_s'],'GAP',x['gap_total_run'],'THR',x['runs_tec_ge_96'])
print('Linhas de LOG malformadas ignoradas:',[(r['run'],r['bad_log_lines_a']) for r in rows if r['bad_log_lines_a']])
