#!/usr/bin/env python3
"""Executa grupos CAN com binarios precompilados. Dry-run e o padrao."""
import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from coletar_ensaios import load_plan


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def group_contiguous(plans):
    groups = []
    for p in plans:
        if not groups or groups[-1][0].condition != p.condition:
            groups.append([p])
        else:
            groups[-1].append(p)
    return groups


def check_image(path, label):
    if not path.is_file():
        raise ValueError(f'Falta binario {label}: {path}')
    if path.stat().st_size < 8192 or path.read_bytes()[:1] != b'\xe9':
        raise ValueError(f'{label} nao parece uma imagem ESP32 valida: {path}')


def main():
    ap = argparse.ArgumentParser(
        description='Campanha CAN complementar: grava binario pronto por grupo e coleta via Pico. '
                    'Por padrao apenas confere o plano, sem gravar ou iniciar testes.')
    ap.add_argument('--plan', type=Path, required=True)
    ap.add_argument('--reference-bin', type=Path, required=True)
    ap.add_argument('--adaptive-bin', type=Path, required=True)
    ap.add_argument('--node-a', default='/dev/ttyUSB0')
    ap.add_argument('--node-b', default='/dev/ttyACM0')
    ap.add_argument('--pico', default='/dev/ttyACM1')
    ap.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[3] / 'data')
    ap.add_argument('--from-run', type=int)
    ap.add_argument('--to-run', type=int)
    ap.add_argument('--between', type=float, default=3.0)
    ap.add_argument('--flash-baud', type=int, default=460800)
    ap.add_argument('--execute', action='store_true',
                    help='Habilita gravacao real do ESP32 e execucao fisica dos ensaios.')
    args = ap.parse_args()

    try:
        plans = load_plan(args.plan)
        selected = [p for p in plans if (args.from_run is None or p.run >= args.from_run)
                    and (args.to_run is None or p.run <= args.to_run)]
        if not selected:
            raise ValueError('Intervalo sem runs no plano.')
        if any(p.run <= 188 for p in selected):
            raise ValueError('IDs ate 188 sao reservados a campanha original. Use IDs novos.')
        if args.between < 0:
            raise ValueError('--between precisa ser nao negativo.')
        if args.node_a in {args.node_b, args.pico} or args.node_b == args.pico:
            raise ValueError('As tres portas devem ser diferentes.')
        groups = group_contiguous(selected)
        paths = {'REFERENCIA': args.reference_bin.resolve(),
                 'ADAPTATIVO': args.adaptive_bin.resolve()}
        print('PLANO DE TESTES COMPLEMENTARES')
        print(f'Arquivo: {args.plan} | {len(selected)} runs em {len(groups)} grupos')
        for i, group in enumerate(groups, 1):
            fw = paths[group[0].condition]
            print(f'{i}. Runs {group[0].run} a {group[-1].run}: {group[0].condition}, '
                  f'perfil(is) {", ".join(p.profile for p in group)}; binario {fw}')
        print('Restricao: so perfis BAIXO, MEDIO_V2 e ALTO, com intervalos oficiais.')
        print('Aviso: isso NAO valida eletricamente intensidades novas ou a duracao real dos pulsos.')
        if not args.execute:
            print('DRY-RUN CONCLUIDO: nenhum equipamento foi acessado.')
            return 0

        if 'exemplo' in args.plan.name.lower():
            raise ValueError('Plano de exemplo bloqueado para execucao fisica.')
        if importlib.util.find_spec('serial') is None:
            raise RuntimeError('Instale pyserial no ambiente Python antes da execucao.')
        if importlib.util.find_spec('esptool') is None:
            raise RuntimeError('Instale/ative o ambiente ESP-IDF com esptool antes da execucao.')
        for mode, path in paths.items():
            check_image(path, mode)
        hashes = {mode: sha256(path) for mode, path in paths.items()}
        if hashes['REFERENCIA'] == hashes['ADAPTATIVO']:
            raise ValueError('Os dois binarios sao identicos. Verifique ENABLE_THROTTLING.')
        raw = args.output / 'raw'
        zips = args.output / 'zips'
        for p in selected:
            if (raw / f'run_{p.run:03d}_injection').exists() or (zips / f'run_{p.run}_injection.zip').exists():
                raise ValueError(f'Run {p.run} ja possui dados; nao sobrescrever.')
        args.output.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        manifest_path = args.output / f'execucao_{stamp}.json'
        manifest = {'started_utc': datetime.now(timezone.utc).isoformat(),
                    'plan': str(args.plan.resolve()),
                    'node_a_port': args.node_a,
                    'app_offset': '0x10000',
                    'firmware': {mode: {'path': str(path), 'sha256': hashes[mode]}
                                 for mode, path in paths.items()},
                    'groups': []}
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        runner = Path(__file__).with_name('coletar_ensaios.py')
        for i, group in enumerate(groups, 1):
            mode = group[0].condition
            image_path = paths[mode]
            entry = {'mode': mode, 'from_run': group[0].run, 'to_run': group[-1].run,
                     'status': 'iniciado', 'started_utc': datetime.now(timezone.utc).isoformat()}
            manifest['groups'].append(entry)
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
            print(f'\n[{i}/{len(groups)}] Gravando binario precompilado: {mode}', flush=True)
            flash = [sys.executable, '-m', 'esptool', '--chip', 'esp32',
                     '--port', args.node_a, '--baud', str(args.flash_baud),
                     'write-flash', '0x10000', str(image_path)]
            try:
                subprocess.run(flash, check=True)
                time.sleep(3)
                cmd = [sys.executable, str(runner), '--plan', str(args.plan),
                       '--from-run', str(group[0].run), '--to-run', str(group[-1].run),
                       '--node-a', args.node_a, '--node-b', args.node_b,
                       '--pico', args.pico, '--output', str(args.output),
                       '--node-a-binary', str(image_path), '--between', str(args.between), '--execute']
                subprocess.run(cmd, check=True)
                entry['status'] = 'concluido'
            except (subprocess.CalledProcessError, KeyboardInterrupt) as e:
                entry['status'] = 'interrompido'
                entry['reason'] = str(e)
                return 1
            finally:
                entry['finished_utc'] = datetime.now(timezone.utc).isoformat()
                manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        print('\nLote complementar concluido. Confira QC de cada run.')
        print(f'Registro da execucao: {manifest_path}')
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(f'ERRO: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
