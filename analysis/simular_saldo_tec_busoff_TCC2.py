#!/usr/bin/env python3
"""Exploracao offline do TEC. Nao simula quadros CAN nem valida um perfil fisico."""
import argparse
import csv
import io
import json
import zipfile
from collections import defaultdict
from pathlib import Path

RUNS = (155, 156, 160, 163, 165, 170, 173, 174, 178, 181, 183, 188,
        191, 192, 193, 194, 195, 196)


def carregar(root):
    result = {}
    for run in RUNS:
        p = root / f'run_{run}_injection.zip'
        with zipfile.ZipFile(p) as z:
            meta = json.loads(z.read('metadata.json'))
            qc = json.loads(z.read('qc.json'))
            if not qc['valid'] or meta['planned']['profile'] != 'ALTO':
                raise ValueError(f'Run {run} nao atende aos requisitos')
            samples=[]
            for row in csv.DictReader(io.StringIO(z.read('node_a.csv').decode('utf-8-sig'))):
                if row['event'] != 'SAMPLE':
                    continue
                data=dict(v.split('=',1) for v in row['detail'].split(';') if '=' in v)
                samples.append((int(row['timestamp_us']),int(row['tec']),int(data['errors']),int(data['tx_ok'])))
            intervals=[]
            for a,b in zip(samples,samples[1:]):
                dt=(b[0]-a[0])/1000
                intervals.append({'start':a[0], 'end':b[0], 'regular':80<=dt<=120,
                                  'tec':a[1], 'd_errors':b[2]-a[2],
                                  'd_ok':b[3]-a[3], 'd_tec':b[1]-a[1]})
            result[run]=(meta['condition'],intervals)
    return result


def streaks(rows, only_high):
    longest=0
    current=0
    for row in rows:
        active=(row['regular'] and row['d_errors']>0 and
                (not only_high or row['tec']>=96))
        if active:
            current += 1
            longest=max(longest,current)
        else:
            current=0
    return longest


def illustrative(initial, errors_per_window, adaptive, max_windows=600):
    tec=initial
    trace=[]
    for k in range(max_windows):
        # Aproximacao intencional: transmissao bem-sucedida por janela de 100 ms;
        # nao reproduz o estado interno TWAI nem a sincronizacao de erros.
        if not adaptive or tec<96:
            successes=10
        elif tec<128:
            successes=5
        else:
            successes=2 if k%2==0 else 3
        tec=max(0,tec+8*errors_per_window-successes)
        trace.append((k+1,tec,successes))
        if tec>=256:
            return len(trace),trace
    return None,trace


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--zip-dir',type=Path,default=Path(__file__).resolve().parent.parent/'data'/'zips')
    ap.add_argument('--output-dir',type=Path,default=Path(__file__).resolve().parent/'analise_temporal_tec'/'simulacao_busoff')
    a=ap.parse_args()
    data=carregar(a.zip_dir)
    a.output_dir.mkdir(parents=True,exist_ok=True)
    summary=[]
    for run,(mode,rows) in data.items():
        critical=[r for r in rows if r['regular'] and r['tec']>=96 and r['d_errors']>0]
        summary.append({'run':run,'mode':mode,'regular_windows':sum(r['regular'] for r in rows),
                        'error_windows_tec96':len(critical),
                        'max_consecutive_windows_errors_any_tec':streaks(rows,False),
                        'max_consecutive_windows_errors_tec96':streaks(rows,True),
                        'max_errors_in_100ms_tec96':max([r['d_errors'] for r in critical],default=0)})
    csvpath=a.output_dir/'persistencia_erros_18_runs.csv'
    with csvpath.open('w',newline='',encoding='utf-8') as f:
        dw=csv.DictWriter(f,fieldnames=list(summary[0]))
        dw.writeheader();dw.writerows(summary)
    scenarios=[]
    for start in (96,128):
        for e in (0,1,2):
            for mode in (False,True):
                reach,trace=illustrative(start,e,mode)
                scenarios.append({'tec_inicial':start,'eventos_error_por_100ms':e,
                                  'modo':'REATIVO' if mode else 'REFERENCIA',
                                  'tempo_para_256_s':f'{reach/10:.1f}' if reach is not None else 'nao em 60 s',
                                  'tec_ao_encerrar_modelo':trace[-1][1]})
    scpath=a.output_dir/'cenarios_ilustrativos.csv'
    with scpath.open('w',newline='',encoding='utf-8') as f:
        dw=csv.DictWriter(f,fieldnames=list(scenarios[0]))
        dw.writeheader();dw.writerows(scenarios)
    print('Conjuntos analisados:',len(summary))
    print('Maximo de janelas regulares consecutivas com ERROR em qualquer TEC:',
          max(r['max_consecutive_windows_errors_any_tec'] for r in summary))
    print('Maximo de janelas consecutivas com ERROR e TEC inicial >=96:',
          max(r['max_consecutive_windows_errors_tec96'] for r in summary))
    print('Run com maior sequência crítica:',
          [(r['run'],r['mode'],r['max_consecutive_windows_errors_tec96']) for r in summary
           if r['max_consecutive_windows_errors_tec96']==max(s['max_consecutive_windows_errors_tec96'] for s in summary)])
    for s in scenarios:
        if s['eventos_error_por_100ms']==1:
            print('CENARIO',s)
    report=['# Investigacao offline do saldo de TEC e risco de Bus-Off','',
      'Base: registros SAMPLE do No A, nos 12 ensaios ALTO oficiais e 6 exploratorios (191–196).',
      'Janelas regulares: 80 a 120 ms. Nao foram executados testes fisicos.','',
      '## Observacao direta', '',
      f'- Maior sequencia de janelas regulares com novo evento ERROR e TEC inicial >=96: **{max(r["max_consecutive_windows_errors_tec96"] for r in summary)}**.',
      f'- Maior sequencia com novo evento ERROR em qualquer faixa de TEC: **{max(r["max_consecutive_windows_errors_any_tec"] for r in summary)}**.',
      '- Essas contagens dependem da discretizacao em cerca de 100 ms; pulsos/erros podem ocorrer concentrados dentro de uma janela.',
      '', '## Simulacao ilustrativa (nao e modelo fisico validado)', '',
      'Em cada janela de 100 ms, a evolucao aproximada e `TEC_prox = max(0, TEC_atual + 8*eventos_ERROR - TX_sucesso)`.',
      'Para a referencia admite-se 10 sucessos/janela; para a politica, 10 se TEC<96, 5 se 96<=TEC<128, e 2/3 alternados quando TEC>=128.',
      'Os eventos ERROR sao impostos artificialmente e nao dependem da quantidade de transmissoes. Isso NAO descreve fielmente o controlador real.',
      '', '| TEC inicial | Eventos ERROR/100 ms | Modo | Tempo ate >=256 |', '|---:|---:|---|---:|']
    for s in scenarios:
        report.append(f'| {s["tec_inicial"]} | {s["eventos_error_por_100ms"]} | {s["modo"]} | {s["tempo_para_256_s"]} |')
    report += ['', '## Cautelas metodologicas', '',
      '- `ERROR` e um evento de software; nao e necessariamente um erro fisico CAN independente nem uma medida universal de TEC +8.',
      '- A politica modifica as tentativas de transmissao e, portanto, tambem altera a oportunidade de gerar novos eventos. Nao e valido manter os mesmos erros como forca externa para prever o resultado real.',
      '- As janelas de um mesmo ensaio sao correlacionadas; o perfil do injetor nao e sincronizado com o inicio dos quadros.',
      '- O resultado nao valida eletricamente o injetor, nem estabelece frequencia ou intensidade segura de curtos.',
      '- A observacao de uma eventual entrada em Bus-Off exigiria o evento STATE_CHANGE no equipamento; um valor calculado de TEC >=256 nao a comprova.',
      '', '## Implicacao', '',
      'Os registros sustentam que o saldo entre erros e transmissões bem-sucedidas determina a tendencia observada do TEC. A simulacao sugere por que a frequencia de transmissao pode alterar a recuperacao, mas nao permite prever que um novo perfil fisico produziria Bus-Off.',
      '']
    (a.output_dir/'RELATORIO_SIMULACAO_TEC_BUSOFF.md').write_text('\n'.join(report),encoding='utf-8')
    print('Saidas:',a.output_dir)

if __name__=='__main__': main()
