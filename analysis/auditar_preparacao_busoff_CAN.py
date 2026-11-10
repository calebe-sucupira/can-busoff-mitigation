#!/usr/bin/env python3
"""Auditoria documental LOCAL dos caminhos de Bus-Off, parada e captura.

Somente leitura do projeto (incluindo fontes guardados em ZIPs pequenos).
Nao abre portas, nao compila, nao grava firmware e nao envia pulsos.
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

EXCLUDE_DIRS = {'.git', '.venv', 'venv', 'node_modules', 'build', 'managed_components', '__pycache__', '.idea', 'data', 'out', 'dist', 'workspaces'}
MAX_SOURCE_BYTES = 600_000
MAX_ARCHIVE_BYTES = 110_000_000
MAX_ZIP_MEMBERS = 1200
FILENAME_RE = re.compile(r'(bus.?off|pico|inject|injec|campanha|captur|node.?a|throttle|automacao|automatiza|seguro|control)', re.I)
TARGET_SCRIPT_RE = re.compile(r'(executar|validar|captur|busoff|seguro|campanha|automacao|automatiza)', re.I)
TARGET_ARCHIVES = re.compile(r'(firmware|automacao.*busoff|busoff.*automacao|pico.*inject|injetor)', re.I)

MARKERS = {
    'A_EVENTO_BUSOFF': r'\bTWAI_ERROR_BUS_OFF\b|\bBUS_OFF\b|\bon_state_change\b',
    'B_ESTADO_E_RECUPERACAO': r'\bcontroller_bus_off\b|\btwai_node_recover\b|\bRECOVERY\b',
    'C_DETECTOR_HOST': r'\bbus_off_detected\b|\bSTATE_CHANGE\b|\bBUS_OFF\b',
    'D_COMANDO_STOP_PICO': r'\bTEST_ABORTED\b|\bABORTED\b|\bb[\'\"]x[\'\"]|\bSTOP\b|\bstop_injection\b',
    'E_COMPROVACAO_PARADA': r'\bTEST_ABORTED\b|\bNOISE_END\b|\bSTATUS\b|\bIDLE\b|\bpio_sm_set_enabled\b|\bsm_set_enabled\b',
    'F_FALHAS_SERIAL_TIMEOUT': r'\bSerialException\b|\bTimeoutError\b|\bwrite_timeout\b|\btimeout\b|\bwatchdog\b|\bdisconnect\b',
    'G_CAPTURA_AUDITAVEL': r'\bmetadata\.json\b|\bcontrol_events\.jsonl\b|\bqc\.json\b|\bnode_a\.log\b|\bnode_b\.log\b|\bpico\.log\b|\bSTATE_CHANGE\b',
    'H_MONITOR_PROG_TEC': r'\btec_peak\b|\btec\b|\bERROR_PASSIVE\b|\bTWAI_ERROR_PASSIVE\b|\bSAMPLE\b',
}
COMPILED = {k: re.compile(v, re.I) for k,v in MARKERS.items()}


def candidate_kind(name: str) -> str | None:
    stem = Path(name).name
    if stem == 'injector.pio':
        return 'pico_pio'
    if stem == 'main.c' and ('pico-injector' in name or 'pico_injector' in name or 'pico' in name.lower()):
        return 'pico_main'
    if stem == 'main.c' and re.search(r'node[-_]a', name, re.I):
        return 'node_a_main'
    if stem.endswith('.py') and TARGET_SCRIPT_RE.search(stem):
        return 'automacao_python'
    if stem.endswith(('.c', '.h', '.pio')) and FILENAME_RE.search(name):
        return 'outro_firmware'
    return None


def local_sources(repo: Path):
    import os
    for folder, dirs, files in os.walk(repo):
        dirs[:] = sorted(x for x in dirs if x not in EXCLUDE_DIRS and not x.startswith('.pytest_cache'))
        base = Path(folder)
        for name in sorted(files):
            if name == 'auditar_preparacao_busoff_CAN.py':
                continue
            path = base / name
            rel = path.relative_to(repo).as_posix()
            kind = candidate_kind(rel)
            if kind:
                try:
                    if path.stat().st_size <= MAX_SOURCE_BYTES:
                        yield rel, kind, path.read_bytes()
                except OSError:
                    continue
            if name.lower().endswith('.zip') and TARGET_ARCHIVES.search(name):
                try:
                    if path.stat().st_size > MAX_ARCHIVE_BYTES:
                        continue
                    with zipfile.ZipFile(path) as z:
                        members = z.infolist()
                        if len(members) > MAX_ZIP_MEMBERS:
                            continue
                        for item in members:
                            if item.is_dir() or item.file_size > MAX_SOURCE_BYTES:
                                continue
                            k = candidate_kind(item.filename)
                            if k:
                                try:
                                    yield f'{rel}::{item.filename}', k, z.read(item)
                                except (OSError, RuntimeError, zipfile.BadZipFile):
                                    continue
                except (OSError, zipfile.BadZipFile):
                    continue


def audit(repo: Path, out: Path) -> dict:
    inventory, evidence = [], []
    unique = set()
    errors = []
    for name, kind, blob in local_sources(repo):
        sha = hashlib.sha256(blob).hexdigest()
        if (name, sha) in unique:
            continue
        unique.add((name, sha))
        try:
            source = blob.decode('utf-8-sig')
        except UnicodeDecodeError:
            errors.append(f'{name}: codificacao nao UTF-8; nao interpretado')
            continue
        syntax = 'NAO_APLICAVEL'
        if name.lower().endswith('.py'):
            try:
                ast.parse(source, filename=name)
                syntax = 'OK'
            except SyntaxError as exc:
                syntax = f'ERRO_LINHA_{exc.lineno}'
                errors.append(f'{name}: Python SyntaxError linha {exc.lineno}: {exc.msg}')
        entries = []
        for line_no, line in enumerate(source.splitlines(), 1):
            for marker, pat in COMPILED.items():
                if pat.search(line):
                    entries.append(marker)
                    # Trechos sao limitados para revisao; nao inferir controle de fluxo.
                    evidence.append(dict(arquivo=name, tipo=kind, categoria=marker,
                                         linha=line_no, trecho=line.strip()[:200]))
        inventory.append(dict(arquivo=name, tipo=kind, bytes=len(blob), sha256=sha,
                              sintaxe_python=syntax, achados=len(entries)))
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'inventario_fontes.csv').open('w', newline='', encoding='utf-8') as f:
        w=csv.DictWriter(f, fieldnames=['arquivo','tipo','bytes','sha256','sintaxe_python','achados'])
        w.writeheader(); w.writerows(inventory)
    with (out / 'evidencias_codigo.csv').open('w', newline='', encoding='utf-8') as f:
        w=csv.DictWriter(f, fieldnames=['arquivo','tipo','categoria','linha','trecho'])
        w.writeheader(); w.writerows(evidence)
    categories=Counter(x['categoria'] for x in evidence)
    kind_cats=defaultdict(set)
    for row in evidence:
        kind_cats[row['tipo']].add(row['categoria'])
    caminhos_host = [f for f in inventory if f['tipo'] == 'automacao_python' and
                    {'C_DETECTOR_HOST','D_COMANDO_STOP_PICO','E_COMPROVACAO_PARADA'} <=
                    {e['categoria'] for e in evidence if e['arquivo'] == f['arquivo']}]
    checks={
        'no_a_marcas_busoff': 'A_EVENTO_BUSOFF' in kind_cats['node_a_main'],
        'no_a_marcas_recuperacao': 'B_ESTADO_E_RECUPERACAO' in kind_cats['node_a_main'],
        'pico_marcas_stop': 'D_COMANDO_STOP_PICO' in kind_cats['pico_main'],
        'pico_marcas_saida': 'E_COMPROVACAO_PARADA' in kind_cats['pico_main'],
        'host_marcas_busoff': 'C_DETECTOR_HOST' in kind_cats['automacao_python'],
        'host_marcas_stop': 'D_COMANDO_STOP_PICO' in kind_cats['automacao_python'],
        'host_marcas_confirmacao': 'E_COMPROVACAO_PARADA' in kind_cats['automacao_python'],
        'host_marcas_timeout': 'F_FALHAS_SERIAL_TIMEOUT' in kind_cats['automacao_python'],
        'host_marcas_captura': 'G_CAPTURA_AUDITAVEL' in kind_cats['automacao_python'],
    }
    report={
        'gerado_em_utc':datetime.now(timezone.utc).isoformat(),
        'repo':str(repo), 'fontes_examinados':len(inventory),
        'evidencias_encontradas':len(evidence),
        'categorias':dict(categories), 'indicadores_textuais':checks,
        'erros_de_leitura_ou_sintaxe':errors,
        'aviso':'INDICADORES TEXTUAIS NAO COMPROVAM CAMINHO DE CONTROLE, EFETIVIDADE DE STOP OU SEGURANCA ELETRICA',
        'nenhuma_porta_serial_aberta':True, 'nenhum_codigo_do_projeto_modificado':True,
    }
    (out / 'diagnostico.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    statuses='\n'.join(f'| {k} | {"LOCALIZADO" if v else "NAO LOCALIZADO (pode ser falso negativo)"} |' for k,v in checks.items())
    examples=[]
    for category in MARKERS:
        matching=[r for r in evidence if r['categoria']==category]
        matching.sort(key=lambda x: (x['tipo'] not in ('automacao_python','pico_main','node_a_main'),x['arquivo'],x['linha']))
        for r in matching[:4]:
            clean=r['trecho'].replace('`',"'").replace('|','/')
            examples.append(f'| {category} | `{r["arquivo"]}:{r["linha"]}` | `{clean[:95]}` |')
    host_paths = '\n'.join('- `' + f['arquivo'] + '`' for f in caminhos_host) or '- Nenhum arquivo com as tres categorias textuais no mesmo documento.'
    md=f'''# Auditoria documental de preparacao do estudo Bus-Off

> Gerado automaticamente em {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. Nenhum dispositivo acessado e nenhum ensaio executado.

## Escopo e limites

Foram lidos **{len(inventory)} arquivos-fonte/copies em arquivos ZIP** e encontradas **{len(evidence)} ocorrencias textuais**.
Esta verificacao usa expressoes regulares: **nao executa o firmware nem comprova** que o Pico realmente interrompe um curto em Bus-Off.
A ausencia de uma marca pode ser falso negativo, especialmente quando um arquivo esta fora do repositorio.

## Indicadores no codigo

| Item pesquisado | Resultado textual |
|---|---|
{statuses}

Arquivos Python com marcas textuais de **BUS_OFF + STOP + confirmacao** no mesmo arquivo (ainda sem prova de fluxo):

{host_paths}

## Exemplos para revisao manual

| Categoria | Local | Trecho |
|---|---|---|
{chr(10).join(examples) or '| - | - | Nao houve ocorrencias |'}

## Pontos que exigem comprovacao antes de qualquer novo ensaio fisico

1. Distinguir **entrada** em Bus-Off de um estado historico ou transicao de recuperacao. Os eventos devem ser datados usando o relogio de captura do host e o relogio local do dispositivo, sem presumir sincronismo em microssegundos.
2. Demonstrar no **fluxo real da automacao** que a entrada em Bus-Off do No A dispara parada do Pico e confirmacao (`TEST_ABORTED` e/ou `STATUS IDLE`). A presenca de palavras nos arquivos nao constitui prova.
3. Confirmar que **falha serial, timeout, Ctrl+C e perda do No A** nao mantem o gerador ativo. `x` via USB e parada logica; so nao constituem protecao eletrica independente.
4. Verificar saida desligada no inicio e no final, falha segura apos reset, e tratamento de comando desconhecido no firmware Pico. Exige revisao de circuito/firmware; nao pode ser verificado somente por logs.
5. Preservar brutos dos tres dispositivos, marcadores de estado, `TEC`, eventos de recepcao, motivo da parada e configuracao. **Nao descartar eventos apos o primeiro Bus-Off**; preservar janela de recuperacao, se eletricamente admissivel.
6. **Nenhum novo perfil de pulso esta autorizado por esta auditoria**. A corrente diferencial nao foi medida; sem isso nao se infere seguranca de uma intensidade intermediaria.

## Proximos artefatos a conferir

- `diagnostico.json`: resultados de verificacao textual e possiveis erros de leitura;
- `evidencias_codigo.csv`: arquivo, linha e fragmento de cada referencia no fonte;
- `inventario_fontes.csv`: lista de fontes e hashes.

''' 
    (out / 'RELATORIO_PREPARACAO_BUSOFF.md').write_text(md, encoding='utf-8')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,default=Path('.'))
    p.add_argument('--out',type=Path,default=Path('analysis/preparacao_busoff_CAN'))
    args=p.parse_args()
    if not args.repo.is_dir():
        p.error(f'Repositorio nao encontrado: {args.repo}')
    result=audit(args.repo.resolve(),args.out.resolve())
    print('PREPARACAO DOCUMENTAL CAN/Bus-Off — SOMENTE LEITURA')
    print('Arquivos examinados:',result['fontes_examinados'])
    print('Evidencias textuais:',result['evidencias_encontradas'])
    for label,found in result['indicadores_textuais'].items():
        print(f'  {label}:', 'LOCALIZADO' if found else 'NAO LOCALIZADO')
    print('Relatorio:',(args.out.resolve()/'RELATORIO_PREPARACAO_BUSOFF.md'))
    if result['erros_de_leitura_ou_sintaxe']:
        print('AVISOS:',*result['erros_de_leitura_ou_sintaxe'],sep='\n - ')

if __name__=='__main__':
    main()
