#!/usr/bin/env python3
"""Audita proveniencia de binarios do No A sem recompilar ou gravar hardware."""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

RUNS = tuple(range(153, 189)) + tuple(range(197, 221))
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
SKIP_DIRS = {'.git', '.venv', 'venv', 'node_modules', '__pycache__',
             '.idea', '.pytest_cache', 'data', '.mypy_cache'}


def digest_file(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def sha_candidate(value):
    if isinstance(value, str) and SHA256.fullmatch(value):
        return value.lower()
    return None


def load_run(zips_dir, number):
    path = zips_dir / f'run_{number}_injection.zip'
    if not path.is_file():
        raise ValueError(f'Run {number}: ZIP ausente: {path}')
    with zipfile.ZipFile(path) as archive:
        metadata = json.loads(archive.read('metadata.json'))
        qc = json.loads(archive.read('qc.json'))
    campaign = 'ORIGINAL' if number <= 188 else 'COMPLEMENTAR'
    if metadata.get('run') != number or qc.get('run') != number:
        raise ValueError(f'Run {number}: ID inconsistente')
    policy = metadata.get('condition')
    if policy not in ('REFERENCIA', 'ADAPTATIVO'):
        raise ValueError(f'Run {number}: politica inesperada {policy!r}')
    if int(metadata.get('expected_throttling', -1)) != int(policy == 'ADAPTATIVO'):
        raise ValueError(f'Run {number}: flag de politica nao confere')
    h = sha_candidate(metadata.get('node_a_binary_sha256'))
    if h is None:
        raise ValueError(f'Run {number}: node_a_binary_sha256 ausente/invalido')
    return {
        'run': number, 'campanha': campaign, 'politica': policy,
        'perfil': metadata.get('planned', {}).get('profile', ''),
        'sha256_app': h,
        'qc_valid': qc.get('valid') is True,
    }


def walk_candidates(directories):
    visited = set()
    for root in directories:
        root = root.expanduser().resolve()
        if not root.is_dir():
            continue
        for directory, names, files in os.walk(root, followlinks=False):
            here = Path(directory)
            names[:] = [name for name in names if name not in SKIP_DIRS]
            for name in files:
                item = here / name
                if item.suffix.lower() == '.bin' or (
                    item.suffix.lower() == '.json' and
                    any(token in name.lower() for token in ('manifest', 'manifesto', 'binario'))
                ) or name == 'throttle_policy.h' or (
                    name == 'main.c' and (here / 'throttle_policy.h').is_file()
                ) or name == 'sdkconfig' or name == 'compile_commands.json':
                    resolved = str(item.resolve())
                    if resolved not in visited:
                        visited.add(resolved)
                        yield item


def find_json_hashes(data, prefix=''):
    if isinstance(data, dict):
        for key, value in data.items():
            path = f'{prefix}.{key}' if prefix else str(key)
            yield from find_json_hashes(value, path)
    elif isinstance(data, list):
        for idx, value in enumerate(data):
            yield from find_json_hashes(value, f'{prefix}[{idx}]')
    else:
        h = sha_candidate(data)
        if h:
            yield prefix, h


def active_sdkconfig(path):
    try:
        result = {}
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if line.startswith('CONFIG_') and '=' in line:
                key, val = line.split('=', 1)
                result[key] = val
        return result
    except OSError:
        return {}


def source_snapshots(found_files):
    folders = set()
    for p in found_files:
        if p.name == 'throttle_policy.h' and (p.parent / 'main.c').is_file():
            folders.add(p.parent)
    rows = []
    for folder in sorted(folders):
        row = {'diretorio': str(folder)}
        for name in ('main.c', 'throttle_policy.h'):
            row[name + '_sha256'] = digest_file(folder / name)
        cfg = (folder.parent / 'sdkconfig')
        row['sdkconfig_path'] = str(cfg) if cfg.is_file() else ''
        if cfg.is_file():
            cfg_data = active_sdkconfig(cfg)
            row['sdkconfig_active_sha256'] = hashlib.sha256(
                json.dumps(cfg_data, sort_keys=True).encode('utf-8')).hexdigest()
        else:
            row['sdkconfig_active_sha256'] = ''
        rows.append(row)
    return rows


def csv_out(dest, records, fields):
    with dest.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--project', type=Path, default=Path.cwd())
    cli.add_argument('--zips-dir', type=Path, default=Path('data/zips'))
    cli.add_argument('--out-dir', type=Path, default=Path('analysis/auditoria_proveniencia_CAN_60'))
    cli.add_argument('--search-dir', type=Path, action='append', default=[],
                     help='diretorio adicional para procurar aplicativos .bin e manifestos')
    args = cli.parse_args()
    project = args.project.resolve()
    zips_dir = args.zips_dir if args.zips_dir.is_absolute() else project / args.zips_dir
    out_dir = args.out_dir if args.out_dir.is_absolute() else project / args.out_dir
    try:
        runs = [load_run(zips_dir, n) for n in RUNS]
        if any(not r['qc_valid'] for r in runs):
            raise ValueError('Ha runs com qc.valid diferente de true')
        groups = defaultdict(list)
        for r in runs:
            groups[(r['campanha'], r['politica'])].append(r)
        summary = []
        for campaign in ('ORIGINAL', 'COMPLEMENTAR'):
            for policy in ('REFERENCIA', 'ADAPTATIVO'):
                group = groups[campaign, policy]
                unique = sorted({x['sha256_app'] for x in group})
                if len(group) != (18 if campaign == 'ORIGINAL' else 12):
                    raise ValueError(f'{campaign}/{policy}: numero incorreto de runs')
                if len(unique) != 1:
                    raise ValueError(f'{campaign}/{policy}: hashes divergentes dentro do grupo')
                summary.append({'campanha': campaign, 'politica': policy,
                                'n_runs': len(group), 'sha256_app': unique[0]})
        expected_hashes = {row['sha256_app'] for row in summary}
        found = list(walk_candidates([project, *args.search_dir]))
        binaries = []
        manifests = []
        other_source_files = []
        for path in found:
            if path.suffix.lower() == '.bin':
                h = digest_file(path)
                binaries.append({'caminho': str(path), 'sha256': h,
                                 'bytes': path.stat().st_size,
                                 'encontrado_nos_logs': h in expected_hashes})
            elif path.suffix.lower() == '.json' and 'compile_commands' not in path.name:
                try:
                    data = json.loads(path.read_text(encoding='utf-8'))
                    for key, h in find_json_hashes(data):
                        if h in expected_hashes or 'source' in key.lower():
                            manifests.append({'manifesto': str(path), 'campo': key,
                                              'sha256': h,
                                              'corresponde_a_binario': h in expected_hashes})
                except (OSError, ValueError, UnicodeError):
                    pass
            else:
                other_source_files.append(path)
        snapshots = source_snapshots(other_source_files)
        confirmed = defaultdict(list)
        for binrow in binaries:
            if binrow['encontrado_nos_logs']:
                confirmed[binrow['sha256']].append(binrow['caminho'])
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_out(out_dir / 'hashes_por_run.csv', runs,
                ['run', 'campanha', 'politica', 'perfil', 'sha256_app', 'qc_valid'])
        csv_out(out_dir / 'hashes_por_campanha.csv', summary,
                ['campanha', 'politica', 'n_runs', 'sha256_app'])
        csv_out(out_dir / 'inventario_binarios.csv', binaries,
                ['caminho', 'sha256', 'bytes', 'encontrado_nos_logs'])
        csv_out(out_dir / 'manifestos_e_hashes.csv', manifests,
                ['manifesto', 'campo', 'sha256', 'corresponde_a_binario'])
        csv_out(out_dir / 'instantaneos_fontes.csv', snapshots,
                ['diretorio', 'main.c_sha256', 'throttle_policy.h_sha256',
                 'sdkconfig_path', 'sdkconfig_active_sha256'])

        phases_identical = all(
            next(row['sha256_app'] for row in summary if row['campanha'] == 'ORIGINAL' and row['politica'] == p)
            == next(row['sha256_app'] for row in summary if row['campanha'] == 'COMPLEMENTAR' and row['politica'] == p)
            for p in ('REFERENCIA', 'ADAPTATIVO')
        )
        lines = [
            '# Auditoria de proveniencia dos aplicativos do No A', '',
            '## Cobertura', '',
            f'- Runs examinados: **{len(runs)}/60**; validacao dos hashes em metadados: **OK**.',
            '- Os hashes representam SHA-256 do aplicativo registrado em cada ZIP.',
            '- A origem exata dos executaveis so e comprovada se arquivos .bin encontrados forem identicos aos hashes.', '',
            '## Grupos', '',
            '| Campanha | Politica | Runs | SHA-256 | Arquivos .bin coincidentes |',
            '|---|---|---:|---|---:|',
        ]
        for row in summary:
            h = row['sha256_app']
            lines.append(f"| {row['campanha']} | {row['politica']} | {row['n_runs']} | `{h}` | {len(confirmed[h])} |")
        lines += [
            '', '## Interpretacao metodologica', '',
            f'- Binarios iguais byte a byte entre campanhas para cada politica: **{str(phases_identical).upper()}**.',
            '- Hashes distintos **nao** comprovam mudanca funcional e **nao** comprovam equivalencia.',
            '- Manifestos podem apontar para hashes, mas a correspondencia dos arquivos reais exige conferir .bin.',
            '- Fontes encontradas agora sao instantaneos atuais; vinculacao a compilacoes historicas depende de evidencia.',
            '- A comparabilidade funcional completa entre campanhas permanece **NAO COMPROVADA** ate auditoria de fontes e compilacao historica.',
            '', '## Arquivos binarios correspondentes encontrados', ''
        ]
        for row in summary:
            lines.append(f"- {row['campanha']} / {row['politica']}: " +
                         (', '.join(f'`{x}`' for x in confirmed[row['sha256_app']])
                          if confirmed[row['sha256_app']] else '**NAO LOCALIZADO**'))
        lines += ['', '## Pistas adicionais', '',
                  f'- Manifestos com hashes relacionados: {len(manifests)} registros.',
                  f'- Pares atuais de fontes C encontrados: {len(snapshots)}.',
                  '- Consulte `manifestos_e_hashes.csv` e `instantaneos_fontes.csv`.',
                  '- Nenhum firmware foi compilado, gravado, modificado ou executado.', '']
        (out_dir / 'PARECER_PRELIMINAR.md').write_text('\n'.join(lines), encoding='utf-8')
        print('Proveniencia offline: 60/60 runs, 4 grupos consistentes.')
        for row in summary:
            h = row['sha256_app']
            print(f"  {row['campanha']:13} {row['politica']:11} n={row['n_runs']:2} "
                  f"sha256={h[:16]}... binarios_locais={len(confirmed[h])}")
        print('Binarios byte a byte iguais entre campanhas:', phases_identical)
        print('Equivalencia funcional entre campanhas: NAO COMPROVADA')
        print('Resultados em:', out_dir)
        return 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f'ERRO: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
