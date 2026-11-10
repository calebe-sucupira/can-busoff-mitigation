#!/usr/bin/env python3
"""Auditoria somente leitura de rastreabilidade histórica do Nó A (TCC CAN).

Não compila, não altera o Git, não grava dispositivos e não modifica artefatos.
Busca cópias históricas do aplicativo e inspeciona definições de compilação.
"""
import argparse
import csv
import hashlib
import json
import re
import shlex
import subprocess
import zipfile
from collections import defaultdict
from pathlib import Path

ORIGINAL_ADAPTATIVO = '4e4fae386a6c46addd32ef862b35a4d769ba570479ff8528d418f6c5e23cb707'
ORIGINAL_REFERENCIA = '4e65131036fcd9db999a5fe67f4874f7d2c319b4d5d3caa89ad65e871c6a14e5'
COMPLEMENTAR_ADAPTATIVO = 'e65d74af829c0307988542a2483300d2f8435a9674dafce1c9b1495da56cf3db'
COMPLEMENTAR_REFERENCIA = '559b0773e025a2639186503acd75b3ccc30ea7caebbe966ae457a0d65ce0dd6e'
TARGETS = {
    ORIGINAL_ADAPTATIVO: 'ORIGINAL/ADAPTATIVO',
    ORIGINAL_REFERENCIA: 'ORIGINAL/REFERENCIA',
    COMPLEMENTAR_ADAPTATIVO: 'COMPLEMENTAR/ADAPTATIVO',
    COMPLEMENTAR_REFERENCIA: 'COMPLEMENTAR/REFERENCIA',
}


def hash_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def local_files(root):
    # Evita circular por .git/ e por ambientes virtuais, sem atravessar symlinks.
    for p in root.rglob('*.bin'):
        if any(part in ('.git', '.venv', 'venv', 'node_modules') for part in p.parts):
            continue
        if not p.is_symlink() and p.is_file() and p.stat().st_size <= 8 * 1024 * 1024:
            yield p


def scan_archives(root, max_archives=2000):
    count = 0
    for p in root.rglob('*.zip'):
        if any(part in ('.git', '.venv', 'venv', 'node_modules') for part in p.parts) or p.is_symlink():
            continue
        if p.stat().st_size > 500 * 1024 * 1024:
            continue
        count += 1
        if count > max_archives:
            break
        try:
            with zipfile.ZipFile(p) as z:
                for entry in z.infolist():
                    name = entry.filename.rsplit('/', 1)[-1].lower()
                    if not (name.endswith('.bin') and ('node_a' in name or 'node-a' in name)):
                        continue
                    if not 0 < entry.file_size <= 8 * 1024 * 1024:
                        continue
                    digest = hashlib.sha256(z.read(entry)).hexdigest()
                    if digest in TARGETS:
                        yield {'origem': 'ZIP', 'caminho': str(p), 'membro': entry.filename,
                               'sha256': digest, 'grupo': TARGETS[digest]}
        except (OSError, zipfile.BadZipFile, RuntimeError, ValueError):
            pass


def parse_compile_entry(entry):
    cmd = entry.get('arguments')
    if not isinstance(cmd, list):
        try:
            cmd = shlex.split(entry.get('command', ''))
        except ValueError:
            cmd = []
    defs = []
    for i, token in enumerate(cmd):
        if token.startswith('-D') and len(token) > 2:
            defs.append(token[2:])
        elif token == '-D' and i + 1 < len(cmd):
            defs.append(cmd[i + 1])
    return defs


def inspect_compilations(repo):
    base = repo / 'automacao_complementar_CAN_TCC2_v2' / 'binarios_node_a_complementar' / 'workspaces'
    dirs = {'PRINCIPAL': repo / 'firmware/node-a',
            'REFERENCIA': base / 'referencia',
            'ADAPTATIVO': base / 'adaptativo'}
    info = {}
    for label, directory in dirs.items():
        detail = {'workspace': str(directory), 'exists': directory.is_dir(), 'sources': {},
                  'macro_effective': 'NAO_VERIFICADO', 'compiler_defines': [],
                  'main_compile_command_found': False}
        for name in ('main.c', 'throttle_policy.h'):
            p = directory / 'main' / name
            detail['sources'][name] = hash_file(p) if p.is_file() else None
        s = directory / 'sdkconfig'
        detail['sources']['sdkconfig'] = hash_file(s) if s.is_file() else None
        p = directory / 'build' / 'compile_commands.json'
        if p.is_file():
            try:
                cmds = json.loads(p.read_text(encoding='utf-8'))
                for entry in cmds:
                    source = entry.get('file', '').replace('\\', '/')
                    if source.endswith('/main/main.c'):
                        detail['main_compile_command_found'] = True
                        defs = parse_compile_entry(entry)
                        detail['compiler_defines'] = sorted(set(defs))
                        modes = [d for d in defs if d.startswith('ENABLE_THROTTLING')]
                        detail['macro_effective'] = ', '.join(sorted(set(modes))) if modes else 'MACRO_NAO_ENCONTRADA_NA_LINHA'
                        break
            except (OSError, ValueError, TypeError):
                detail['macro_effective'] = 'ERRO_AO_LER_COMPILE_COMMANDS'
        info[label] = detail
    return info


def git_history(repo):
    if not (repo / '.git').exists():
        return ['Sem diretorio .git visivel.']
    paths = ['firmware/node-a/main/main.c', 'firmware/node-a/main/throttle_policy.h',
             'firmware/node-a/CMakeLists.txt', 'firmware/node-a/main/CMakeLists.txt']
    result = subprocess.run(['git', '-C', str(repo), 'log', '--all', '-n', '25',
                             '--date=short', '--format=%h | %ad | %s', '--', *paths],
                            capture_output=True, text=True, check=False, timeout=25)
    return result.stdout.splitlines() if result.returncode == 0 else ['Git indisponivel: ' + result.stderr.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--search-root', type=Path,
                        help='Por padrao busca no proprio repositorio; pode usar ~/Documentos/tcc para incluir backups.')
    parser.add_argument('--out', type=Path, default=Path('analysis/diagnostico_linhagem_compilacao_CAN.json'))
    args = parser.parse_args()
    repo = args.repo.expanduser().resolve()
    root = (args.search_root or repo).expanduser().resolve()
    matches = []
    for p in local_files(root):
        try:
            sha = hash_file(p)
        except OSError:
            continue
        if sha in TARGETS:
            matches.append({'origem': 'BIN', 'caminho': str(p), 'membro': '',
                            'sha256': sha, 'grupo': TARGETS[sha]})
    matches.extend(scan_archives(root))
    snapshots = inspect_compilations(repo)
    history = git_history(repo)
    data = {'repo': str(repo), 'search_root': str(root), 'matched_artifacts': matches,
            'build_inspection': snapshots, 'source_history': history,
            'conclusion_rule': ('Hash igual identifica bytes iguais; hashes diferentes nao comprovam mudanca funcional. '
                                'Fontes atuais e flags de build nao comprovam o historico sem vinculacao documental.')}
    dest = args.out.expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('RELATORIO:', dest)
    print('ARTEFATOS LOCALIZADOS POR GRUPO:')
    groups = defaultdict(list)
    for m in matches:
        groups[m['grupo']].append(m)
    for group in ('ORIGINAL/REFERENCIA','ORIGINAL/ADAPTATIVO','COMPLEMENTAR/REFERENCIA','COMPLEMENTAR/ADAPTATIVO'):
        print(' ', group, len(groups[group]))
        for m in groups[group][:5]:
            print('   ', m['origem'], m['caminho'], m['membro'])
    print('COMPILACAO DE main.c:')
    for name, d in snapshots.items():
        print(' ', name, '| main', str(d['sources']['main.c'])[:12],
              '| macro', d['macro_effective'])
    print('HISTORICO GIT: ', len(history), 'registros (consulte JSON)')
    print('Observacao: diagnostico documental, sem prova automatica de equivalencia funcional.')

if __name__ == '__main__':
    main()
