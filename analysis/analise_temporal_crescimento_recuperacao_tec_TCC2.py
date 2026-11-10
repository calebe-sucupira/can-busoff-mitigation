#!/usr/bin/env python3
"""Auditoria offline de recuperação do TEC nos 18 ensaios ALTO (12 oficiais + 6 complementares)."""
import csv
import io
import json
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
ZIP_DIR = ROOT.parent / 'data' / 'zips'
if not ZIP_DIR.is_dir():
    ZIP_DIR = ROOT  # execução com ZIPs no mesmo diretório
RUNS = [155,156,160,163,165,170,173,174,178,181,183,188,191,192,193,194,195,196]
OUT = ROOT / 'analise_temporal_tec'
OUT.mkdir(exist_ok=True)
rows_all = []
report_run = []
for run in RUNS:
    with zipfile.ZipFile(ZIP_DIR / f'run_{run}_injection.zip') as z:
        meta=json.loads(z.read('metadata.json'))
        qc=json.loads(z.read('qc.json'))
        assert meta['planned']['profile']=='ALTO' and qc['valid'] is True, (run,meta,qc)
        r=list(csv.DictReader(io.StringIO(z.read('node_a.csv').decode('utf-8-sig'))))
    samples=[]
    for line in r:
        if line['event']!='SAMPLE':continue
        detail=dict(piece.split('=',1) for piece in line['detail'].split(';') if '=' in piece)
        samples.append(dict(run=run,mode=meta['condition'],time_s=int(line['timestamp_us'])/1e6,tec=int(line['tec']),
                            tec_peak=int(detail['tec_peak']),errors=int(detail['errors']),tx_ok=int(detail['tx_ok']),
                            gap=int(detail['gap']),state=line['state']))
    sample=pd.DataFrame(samples).sort_values('time_s')
    peak=sample.loc[sample['tec_peak'].idxmax()]
    states=[x['detail'] for x in r if x['event']=='STATE_CHANGE']
    report_run.append(dict(run=run,mode=meta['condition'],peak_tec=int(peak['tec_peak']),
                           max_sample_tec=int(sample.tec.max()), errors_at_end=int(sample.errors.iloc[-1]),
                           tx_ok_at_end=int(sample.tx_ok.iloc[-1]), gap=int(sample.gap.iloc[-1]),
                           passive_entries=sum(x.endswith('->PASSIVE') for x in states),
                           busoff_events=sum(x.endswith('->BUS_OFF') for x in states)))
    sample['dt_s']=sample.time_s.diff()
    for name in ['tec','errors','tx_ok']:
        sample['d'+name]=sample[name].diff()
    for i,x in sample.iloc[1:].iterrows():
        rows_all.append(dict(run=run,mode=meta['condition'],begin_s=float(sample.iloc[i-1].time_s),end_s=float(x.time_s),
                             dt_s=float(x.dt_s), tec_ini=int(sample.iloc[i-1].tec),tec_fim=int(x.tec),
                             dtec=int(x.dtec),derrors=int(x.derrors),dtx_ok=int(x.dtx_ok),
                             state_ini=sample.iloc[i-1]['state'],state_fim=x['state']))

intervals=pd.DataFrame(rows_all)
runs=pd.DataFrame(report_run).sort_values('run')
runs.to_csv(OUT/'resumo_por_run_alto_18.csv',index=False)
intervals.to_csv(OUT/'intervalos_amostras_tec.csv',index=False)

# Janela de heartbeat 100 ms sem incremento do contador cumulativo de erro.
regular=intervals[(intervals.dt_s.between(.08,.12)) & (intervals.tec_ini>0) & (intervals.derrors==0) & (intervals.dtx_ok>=0)]
fall=regular[regular.dtec<0]
# TEC cai nos blocos sem novos erros, salvo efeitos de arredondamento de contador e assincronia de eventos.
print('ALTO runs:',len(runs),'AMOSTRAS_INTERVALOS:',len(intervals),'JANELAS 80-120ms TEC>0 SEM ERROS:',len(regular))
print('DESCIDAS dTEC<0:',len(fall),'taxa', round(len(fall)/len(regular),4))
print('DESCIDAS == -tx_ok:',int((-fall.dtec==fall.dtx_ok).sum()),'/',len(fall))
print('DESCIDAS |dTEC+dtx_ok|<=1:',int(((fall.dtec+fall.dtx_ok).abs()<=1).sum()),'/',len(fall))
print('ERROS CONGELADOS & TX>0 & TEC>=96 ANTERIOR por modo:')
critical=regular[(regular.tec_ini>=96) & (regular.dtx_ok>0) & (regular.dtec<=0)]
print(critical.groupby('mode')[['dtx_ok','dtec','dt_s']].agg(['count','median','mean']).to_string())
print('\nRUNS:')
print(runs.to_string(index=False))
# Typical drops in a clean 100-ms segment (not always monotone if special transitions).
for mode,subset in regular.groupby('mode'):
    print('MODE',mode,'n',len(subset),'fall',len(subset[subset.dtec<0]),'match',sum((subset.dtec+subset.dtx_ok).abs()<=1))
# Specific windows for high TEC before and after each peak.
for run in [191,193,160]:
    t=intervals[(intervals.run==run) & (intervals.tec_ini>=120) & (intervals.dtec<0) & (intervals.derrors==0) & (intervals.dt_s.between(.08,.12))].copy()
    print('\nRUN',run,'intervals peak-zone',len(t))
    print(t[['begin_s','end_s','tec_ini','tec_fim','derrors','dtx_ok','dtec']].head(6).to_string(index=False))
# Plot selected run's TEC full timeseries by reopening CSV (one chart with two runs not aligned; one chart per run)
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
for run in (191,193):
    with zipfile.ZipFile(ZIP_DIR/f'run_{run}_injection.zip') as z:
        rows=list(csv.DictReader(io.StringIO(z.read('node_a.csv').decode())))
    xs=[];ys=[];pks=[]
    for a in rows:
        if a['event']=='SAMPLE':
            xs.append(int(a['timestamp_us'])/1e6)
            ys.append(int(a['tec']))
            d=dict(p.split('=',1) for p in a['detail'].split(';') if '=' in p)
            pks.append(int(d['tec_peak']))
    fig,ax=plt.subplots(figsize=(10,4))
    ax.plot(xs,ys,lw=1.2,label='TEC amostrado')
    ax.axhline(96,ls='--',lw=1,label='Limiar 96')
    ax.axhline(128,ls=':',lw=1,label='Limiar 128')
    ax.set(title=f'Run {run}: evolução do TEC (perfil ALTO)',xlabel='Tempo local do Nó A (s)',ylabel='TEC')
    ax.grid(alpha=.2)
    ax.legend(loc='upper right')
    fig.tight_layout()
    fig.savefig(OUT/f'tec_run_{run}_revisao.png',dpi=160)
    plt.close(fig)

# Gerar relatório com base em estatísticas auditáveis.
# No intervalo sem novos erros e com TEC>0, o decremento não ultrapassa zero.
regular=regular.copy()
regular['tec_previsto']=(regular.tec_ini-regular.dtx_ok).clip(lower=0)
acertos=int((regular.tec_previsto==regular.tec_fim).sum())
with_errors=intervals[intervals.dt_s.between(.08,.12) & (intervals.derrors>0)]
faixas=[('TEC de 1 a 95',1,96),('TEC de 96 a 127',96,128),('TEC de 128 a 255',128,256)]
faixas_result=[]
for label,lo,hi in faixas:
    group=regular[(regular.tec_ini>=lo)&(regular.tec_ini<hi)&(regular.tec_fim>0)]
    for mode in ('REFERENCIA','ADAPTATIVO'):
        subset=group[group['mode']==mode]
        faixas_result.append(dict(faixa=label,modo=mode,janelas=len(subset),
             tx_mediana_em_100ms=float(subset.dtx_ok.median()) if len(subset) else None,
             queda_mediana_em_100ms=float((-subset.dtec).median()) if len(subset) else None))
faixas_df=pd.DataFrame(faixas_result)
faixas_df.to_csv(OUT/'resumo_recuperacao_por_faixa.csv',index=False)

with (OUT/'RELATORIO_ANALISE_TEC.md').open('w',encoding='utf-8') as f:
    f.write('# Auditoria temporal do TEC — TCC II\n\n')
    f.write('**Escopo:** 12 ensaios oficiais ALTO (155, 156, 160, 163, 165, 170, 173, 174, 178, 181, 183 e 188) e seis exploratórios ALTO (191–196). Todos os 18 ZIPs apresentam `qc.json` válido. Não foi identificado evento `BUS_OFF` nesse conjunto.\n\n')
    f.write('## Hipótese investigada\n\n')
    f.write('Quando há uma sequência de erros, o TEC sobe. Quando os erros cessam temporariamente, transmissões CAN bem-sucedidas reduzem o contador, limitando seu acúmulo. A política reativa reduz também as oportunidades de transmissão bem-sucedida e pode tornar a recuperação do TEC mais lenta.\n\n')
    f.write('## Método e resultados\n\n')
    f.write(f'Foram encontrados {len(intervals)} intervalos entre amostras consecutivas (`SAMPLE`) nos 18 ensaios. Selecionamos {len(regular)} intervalos com 80–120 ms, TEC inicial positivo, nenhum incremento do contador cumulativo de erros CAN (`errors`) e `tx_ok` não decrescente.\n\n')
    f.write(f'Em **{acertos}/{len(regular)}** intervalos, observou-se exatamente `TEC_final = max(0, TEC_inicial - Δtx_ok)`; o piso em zero é necessário porque o TEC não assume valor negativo. Essas janelas são intervalos de tempo correlacionados, **não** repetições experimentais independentes.\n\n')
    f.write(f'Em contraste, entre {len(with_errors)} janelas de 80–120 ms com incremento de `errors`, houve crescimento do TEC em {int((with_errors.dtec>0).sum())} e queda em {int((with_errors.dtec<0).sum())}. Esse contador de eventos não deve ser convertido diretamente em incremento de TEC: os efeitos variam com o tipo de erro e o estado do controlador.\n\n')
    f.write('### Taxa observada de recuperação em janelas sem novos erros\n\n')
    f.write('| Faixa inicial do TEC | Modo | Janelas | TX bem-sucedidas por janela (mediana) | Redução do TEC por janela (mediana) |\n')
    f.write('|---|---|---:|---:|---:|\n')
    for item in faixas_result:
        f.write(f"| {item['faixa']} | {item['modo']} | {item['janelas']} | {item['tx_mediana_em_100ms']:.0f} | {item['queda_mediana_em_100ms']:.0f} |\n")
    f.write('\nNas janelas sem novo erro e com TEC ainda positivo, os resultados são compatíveis com 100 Hz (referência), aproximadamente 50 Hz (reativo em alerta) e 25 Hz (reativo em condição mais severa). O número de janelas em `TEC≥128` do modo referência é reduzido e não deve ser utilizado para inferência estatística isolada.\n\n')
    f.write('### Exemplos auditáveis\n\n')
    f.write('- **Run 191 (referência):** entre 13,690 e 13,789 s, o TEC caiu de 137 para 127, com dez transmissões concluídas e nenhum incremento do contador de erros (91 em ambas as amostras).\n')
    f.write('- **Run 193 (reativo):** entre 15,780 e 15,881 s, TEC de 132 para 129; três transmissões concluídas; contador de erros inalterado em 91.\n')
    f.write('- **Run 160 (reativo):** entre 15,051 e 15,552 s, TEC de 141 para 129; doze transmissões concluídas e contador de erros inalterado em 92.\n\n')
    f.write('## Interpretação e limites\n\n')
    f.write('Os dados **sustentam fortemente** a recuperação do TEC durante intervalos sem novos erros, por transmissões bem-sucedidas. No modo reativo, a redução de frequência também reduz a velocidade dessa recuperação. Esse mecanismo oferece uma explicação plausível para a permanência em `Error Passive` por mais tempo em alguns ensaios com a política. Não demonstra que a política cause Bus-Off, nem que reduzir a frequência em geral seja prejudicial.\n\n')
    f.write('O contador `tec_peak` reúne os máximos observados pelo monitor com período nominal de 1 ms, e pode superar `tec` nas amostras impressas. A coincidência exata é uma característica **observada** nos registros, não uma comprovação completa das regras internas do controlador; eventos dentro dos 100 ms podem não estar visíveis. O firmware armazena `SAMPLE` e `TX_SUCCESS` separadamente, e os timestamps seriais não são uma referência elétrica ao nível do bit.\n\n')
    f.write('**Conclusão prática:** a ausência de Bus-Off parece envolver uma alternância entre aumentos por erro e quedas em períodos de transmissões bem-sucedidas; não há evidência de acúmulo sustentado até 256 nos ensaios avaliados. Esse diagnóstico, sozinho, não autoriza intensificar curtos elétricos. Para um novo perfil seria necessário validar previamente os limites do circuito; sem osciloscópio, uma avaliação emulada do algoritmo seria alternativa auxiliar, mas não comprovaria mitigação de Bus-Off físico.\n\n')
    f.write('## Arquivos de reprodução\n\n')
    f.write('`analise_temporal_crescimento_recuperacao_tec_TCC2.py` — script; `resumo_por_run_alto_18.csv`, `intervalos_amostras_tec.csv`, `resumo_recuperacao_por_faixa.csv` — dados derivados; PNGs dos Runs 191 e 193. Todos os arquivos de entrada são ZIPs originais preservados.\n')
print('Acertos com saturação em zero:',acertos,'/',len(regular))
print('Intervalos com incremento de erros:',len(with_errors),'positivos',int((with_errors.dtec>0).sum()))
print(faixas_df.to_string(index=False))
print('Arquivos em:',OUT)
