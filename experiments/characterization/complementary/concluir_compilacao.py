#!/usr/bin/env python3
"""Finaliza as duas compilacoes concluidas sem recompilar nem gravar hardware.

Use com compilar_binarios.py quando os dois workspaces ja foram compilados.
Esta versao requer que ambos os workspaces ja tenham sido compilados.
"""
import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from compilar_binarios import (APPS, MODES, check_sources, sha256,
                                       verify_build)

SUPPORT_FILES = ('bootloader/bootloader.bin', 'partition_table/partition-table.bin')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def active_sdkconfig(path):
    # Caminhos e comentarios nao sao configuracoes do alvo.
    return {line.partition('=')[0]: line.partition('=')[2]
            for line in path.read_text(encoding='utf-8').splitlines()
            if line.startswith('CONFIG_') and '=' in line}


def confirm_flash_layout(ws):
    build = ws / 'build'
    args = read_json(build / 'flasher_args.json')
    expected = {
        'bootloader': ('0x1000', 'bootloader/bootloader.bin'),
        'partition-table': ('0x8000', 'partition_table/partition-table.bin'),
        'app': ('0x10000', 'node_a.bin'),
    }
    for item, (address, filename) in expected.items():
        entry = args.get(item, {})
        if entry.get('offset') != address or entry.get('file') != filename:
            raise ValueError(f'Layout inesperado em {ws.name}/{item}: {entry!r}')
        if entry.get('encrypted') not in (False, 'false', 'False', None):
            raise ValueError(f'Imagem criptografada nao suportada: {ws.name}/{item}')
    if args.get('extra_esptool_args', {}).get('chip') != 'esp32':
        raise ValueError(f'Alvo inesperado em {ws.name}')
    return args


def main():
    parser = argparse.ArgumentParser(
        description='Recupera e valida binarios dos dois workspaces ja compilados, sem novo build.')
    parser.add_argument('--project', required=True, type=Path, help='firmware/node-a')
    parser.add_argument('--output', type=Path,
                        default=Path('build/variantes_node_a'))
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    outdir = args.output.expanduser().resolve()
    try:
        digest = check_sources(project)
        builds = {}
        configurations = {}
        layouts = {}
        hashes_aux = {}
        images = {}
        for name, mode in MODES.items():
            ws = outdir / 'workspaces' / name.lower()
            if not ws.is_dir():
                raise ValueError(f'Workspace ainda nao compilado: {ws}')
            images[name], hashes_aux[name] = verify_build(ws, mode)
            configurations[name] = active_sdkconfig(ws / 'sdkconfig')
            layouts[name] = confirm_flash_layout(ws)
            builds[name] = {
                'enable_throttling': mode,
                'path': str(outdir / APPS[name]),
                'sha256': sha256(images[name]),
                'support_images_sha256': hashes_aux[name],
            }
            print(f'{name}: imagem compilada valida; ENABLE_THROTTLING={mode}')
        if configurations['REFERENCIA'] != configurations['ADAPTATIVO']:
            differ = sorted(set(configurations['REFERENCIA']) ^ set(configurations['ADAPTATIVO']) |
                            {k for k in configurations['REFERENCIA'] if
                             configurations['REFERENCIA'].get(k) != configurations['ADAPTATIVO'].get(k)})
            raise ValueError('sdkconfig diverge entre os modos: ' + ', '.join(differ[:12]))
        config = configurations['REFERENCIA']
        if config.get('CONFIG_SECURE_BOOT') == 'y' or config.get('CONFIG_SECURE_FLASH_ENC_ENABLED') == 'y':
            raise ValueError('Secure boot / flash encryption exigem verificacao especifica.')
        if layouts['REFERENCIA'].get('flash_settings') != layouts['ADAPTATIVO'].get('flash_settings'):
            raise ValueError('Configuracoes de gravacao divergentes entre os modos.')
        if hashes_aux['REFERENCIA']['partition_table/partition-table.bin'] != \
           hashes_aux['ADAPTATIVO']['partition_table/partition-table.bin']:
            raise ValueError('As tabelas de particao sao diferentes. Nao liberar alternancia.')
        if builds['REFERENCIA']['sha256'] == builds['ADAPTATIVO']['sha256']:
            raise ValueError('Aplicativos identicos: nao foi possivel distinguir as politicas.')
        warn_boot = (hashes_aux['REFERENCIA']['bootloader/bootloader.bin'] !=
                     hashes_aux['ADAPTATIVO']['bootloader/bootloader.bin'])
        if warn_boot:
            print('AVISO: bootloaders distintos em bytes, apesar das mesmas configuracoes.')
            print('A automacao grava somente o aplicativo em 0x10000; NAO grava bootloader.')
            print('Isto requer validacao de boot de CADA modo no ESP32 antes dos ensaios.')
        else:
            print('Bootloaders e tabelas de particao identicos nos dois modos.')

        for name in MODES:
            dest = outdir / APPS[name]
            if dest.exists():
                if sha256(dest) != builds[name]['sha256']:
                    raise ValueError(f'O binario existente diverge da compilacao: {dest}')
            else:
                shutil.copy2(images[name], dest)
            print(f'{name}: {dest}')

        manifest = {
            'created_utc': datetime.now(timezone.utc).isoformat(),
            'project': str(project),
            'source_sha256': digest,
            'images': builds,
            'app_flash_offset': '0x10000',
            'flash_settings': layouts['REFERENCIA'].get('flash_settings'),
            'bootloader_bytes_identical': not warn_boot,
            'partition_tables_identical': True,
            'sdkconfigs_identical': True,
            'note': ('Compilacoes recuperadas sem rebuild. Nenhuma gravacao realizada. '
                     'Validar boot e modo de cada binario antes de qualquer teste fisico.'),
        }
        manifest_path = outdir / 'registro_binarios.json'
        if manifest_path.exists():
            old = read_json(manifest_path)
            if old.get('source_sha256') != digest or \
               any(old.get('images', {}).get(n, {}).get('sha256') != builds[n]['sha256'] for n in MODES):
                raise ValueError('Registro anterior tem hashes diferentes; nada sera sobrescrito.')
            print(f'Registro valido existente: {manifest_path}')
        else:
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
                                     encoding='utf-8')
            print(f'Registro gerado: {manifest_path}')
        print('VALIDACAO LOGICA CONCLUIDA. Nenhum arquivo foi recompilado ou gravado no ESP32.')
        return 0
    except (ValueError, RuntimeError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f'ERRO: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
