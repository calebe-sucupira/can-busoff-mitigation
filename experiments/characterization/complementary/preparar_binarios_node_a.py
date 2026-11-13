#!/usr/bin/env python3
"""Gera as duas imagens do No A uma vez, sem editar o projeto original.

Sem --build, confere os arquivos e mostra a acao prevista (dry-run).
Requer ESP-IDF instalado e ambiente ativado para compilacao real.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

MODES = {'REFERENCIA': 0, 'ADAPTATIVO': 1}
APPS = {'REFERENCIA': 'node_a_referencia.bin', 'ADAPTATIVO': 'node_a_adaptativo.bin'}
ESSENTIAL = ('CMakeLists.txt', 'main/CMakeLists.txt', 'main/main.c', 'main/throttle_policy.h', 'sdkconfig')


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_digest(project):
    h = hashlib.sha256()
    for rel in ESSENTIAL:
        path = project / rel
        if not path.is_file():
            raise ValueError(f'Arquivo necessario ausente: {path}')
        h.update(rel.encode('utf-8') + b'\x00')
        h.update(path.read_bytes())
    # Inclui outros fontes e configuracoes que possam afetar a compilacao.
    for directory in ('main', 'components'):
        folder = project / directory
        if folder.is_dir():
            for path in sorted(folder.rglob('*')):
                if path.is_file() and '__pycache__' not in path.parts:
                    rel = path.relative_to(project).as_posix()
                    if rel in ESSENTIAL:
                        continue
                    h.update(rel.encode('utf-8') + b'\x00')
                    h.update(path.read_bytes())
    for name in ('sdkconfig.defaults', 'dependencies.lock', 'partitions.csv'):
        path = project / name
        if path.is_file():
            h.update(name.encode('utf-8') + b'\x00')
            h.update(path.read_bytes())
    return h.hexdigest()


def check_sources(project):
    digest = source_digest(project)
    main = (project / 'main/main.c').read_text(encoding='utf-8')
    cmake = (project / 'main/CMakeLists.txt').read_text(encoding='utf-8')
    if '#ifndef ENABLE_THROTTLING' not in main:
        raise ValueError('O main.c nao possui o seletor #ifndef ENABLE_THROTTLING esperado.')
    if 'idf_component_register' not in cmake:
        raise ValueError('O CMakeLists.txt do componente nao tem idf_component_register.')
    return digest


def copy_project(project, dest, mode):
    # Copia apenas o projeto, sem saidas e caches antigos.
    shutil.copytree(project, dest, ignore=shutil.ignore_patterns(
        'build', 'build_*', '.git', '__pycache__', '*.pyc', '.idea', '.vscode'))
    cmake = dest / 'main/CMakeLists.txt'
    with cmake.open('a', encoding='utf-8') as f:
        f.write(f'\n# Definicao aplicada somente na copia de compilacao.\n'
                f'target_compile_definitions(${{COMPONENT_LIB}} PRIVATE ENABLE_THROTTLING={mode})\n')


def verify_build(workspace, mode):
    build = workspace / 'build'
    image = build / 'node_a.bin'
    if not image.is_file() or image.stat().st_size < 8192 or image.read_bytes()[:1] != b'\xe9':
        raise ValueError(f'Imagem ESP32 ausente ou invalida: {image}')
    flash_path = build / 'flasher_args.json'
    flash = json.loads(flash_path.read_text(encoding='utf-8'))
    if flash.get('app', {}).get('offset') != '0x10000':
        raise ValueError(f'Offset de aplicacao inesperado em {flash_path}')
    if flash.get('extra_esptool_args', {}).get('chip') != 'esp32':
        raise ValueError(f'Chip alvo inesperado em {flash_path}')
    commands = json.loads((build / 'compile_commands.json').read_text(encoding='utf-8'))
    matches = [line for line in commands
               if Path(line.get('file', '')).name == 'main.c'
               and '/main/' in line.get('file', '').replace('\\', '/')]
    if not any(f'-DENABLE_THROTTLING={mode}' in (entry.get('command', '') or ' '.join(entry.get('arguments', [])))
               for entry in matches):
        raise ValueError(f'Nao consegui confirmar -DENABLE_THROTTLING={mode} na compilacao.')
    hashes = {}
    for rel in ('bootloader/bootloader.bin', 'partition_table/partition-table.bin'):
        file = build / rel
        if not file.is_file():
            raise ValueError(f'Arquivo de flash esperado ausente: {file}')
        hashes[rel] = sha256(file)
    return image, hashes


def verify_existing(outdir, digest):
    manifest = outdir / 'manifesto_binarios.json'
    if not manifest.exists():
        return False
    info = json.loads(manifest.read_text(encoding='utf-8'))
    if info.get('source_sha256') != digest:
        raise ValueError('O codigo-fonte mudou desde a geracao dos binarios. '
                         'Escolha outra pasta --output para preservar a versao anterior.')
    for mode, fname in APPS.items():
        file = outdir / fname
        if not file.is_file() or sha256(file) != info.get('images', {}).get(mode, {}).get('sha256'):
            raise ValueError(f'Binario preexistente nao confere com manifesto: {file}')
    return True


def main():
    ap = argparse.ArgumentParser(description='Compila e guarda No A REFERENCIA/ADAPTATIVO sem mexer no main.c original.')
    ap.add_argument('--project', type=Path, required=True, help='Diretorio firmware/node-a do seu repositorio.')
    ap.add_argument('--output', type=Path, default=Path('binarios_node_a_complementar'))
    ap.add_argument('--build', action='store_true', help='Habilita as duas compilacoes (padrao: simulacao).')
    args = ap.parse_args()
    project = args.project.expanduser().resolve()
    outdir = args.output.expanduser().resolve()
    try:
        digest = check_sources(project)
        print(f'Projeto: {project}')
        print(f'Destino: {outdir}')
        print(f'Codigo-fonte (SHA-256): {digest}')
        for name, mode in MODES.items():
            print(f'  {name}: ENABLE_THROTTLING={mode} -> {APPS[name]}')
        if verify_existing(outdir, digest):
            print('Os dois binarios ja existem e seus hashes conferem. Nenhuma compilacao necessaria.')
            return 0
        if not args.build:
            print('DRY-RUN: nada compilado ou alterado. Use --build apos conferir os caminhos.')
            return 0
        if outdir.exists() and any(outdir.iterdir()):
            raise ValueError('A pasta de destino nao esta vazia e nao tem manifesto valido. '
                             'Escolha outra pasta --output para evitar sobrescrita.')
        if not shutil.which('idf.py'):
            raise RuntimeError('idf.py nao encontrado. Ative o ESP-IDF com source ~/esp/esp-idf/export.sh.')
        outdir.mkdir(parents=True, exist_ok=True)
        builds = {}
        for name, mode in MODES.items():
            ws = outdir / 'workspaces' / name.lower()
            print(f'\nPreparando {name} (ENABLE_THROTTLING={mode})...', flush=True)
            copy_project(project, ws, mode)
            subprocess.run(['idf.py', '-C', str(ws), 'build'], check=True)
            image, hashes = verify_build(ws, mode)
            dest = outdir / APPS[name]
            shutil.copy2(image, dest)
            builds[name] = {'enable_throttling': mode, 'path': str(dest),
                            'sha256': sha256(dest), 'support_images_sha256': hashes}
        if builds['REFERENCIA']['sha256'] == builds['ADAPTATIVO']['sha256']:
            raise ValueError('Os dois binarios gerados sao iguais. Verifique as compilacoes.')
        if builds['REFERENCIA']['support_images_sha256'] != builds['ADAPTATIVO']['support_images_sha256']:
            raise ValueError('Bootloader ou particoes divergem entre os modos. Nao executar flash automatico.')
        manifest = {'created_utc': datetime.now(timezone.utc).isoformat(),
                    'project': str(project), 'source_sha256': digest,
                    'images': builds, 'app_flash_offset': '0x10000',
                    'note': 'Builds nao validados no ESP32. Confirmar boot de cada modo antes da campanha.'}
        (outdir / 'manifesto_binarios.json').write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('\nPRONTO: dois binarios separados e manifesto com hashes.')
        for name in MODES:
            print(f'  {name}: {builds[name]["path"]}')
        print('PROXIMO: validar ambos os modos no ESP32; ainda nao iniciar ensaios complementares.')
        return 0
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f'ERRO: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
