#!/usr/bin/env python3
"""Prepara copia isolada do projeto Pico PHASE20; nao compila, nao grava ou abre serial."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

EXPECTED_SHA256 = '9cd6b0d32c6a6b879bfe832a7e0d00d04b3d5a130aec1dd85ddf9db5175ac7dd'

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    package = Path(__file__).resolve().parent
    original = repo / 'firmware' / 'pico-injector'
    main_c = original / 'main.c'
    if not main_c.is_file():
        parser.error(f'Nao encontrei: {main_c}')
    original_hash = sha256(main_c)
    if original_hash != EXPECTED_SHA256:
        parser.error('O main.c atual difere do fonte auditado. Nao alterei nada. '
                     f'SHA256 encontrado: {original_hash}')
    if sha256(original/'injector.pio') != sha256(package/'injector.pio'):
        parser.error('injector.pio difere do fonte auditado. Nao alterei nada.')
    target = args.output.resolve() if args.output else repo.parent / '_pico_phase20_TCC_CAN'
    if target.exists():
        parser.error(f'Destino ja existe; nenhum arquivo sobrescrito: {target}')
    shutil.copytree(original, target, ignore=shutil.ignore_patterns('build', 'build-*', '__pycache__', '*.uf2', '*.elf', '*.bin', '*.hex'))
    shutil.copy2(package/'main_phase20.c', target/'main.c')
    (target/'MANIFESTO_PHASE20.json').write_text(json.dumps({
        'repo_original': str(repo),
        'origem': str(original),
        'origem_main_sha256': original_hash,
        'variante_main_sha256': sha256(target/'main.c'),
        'pio_sha256': sha256(target/'injector.pio'),
        'profile': 'PHASE20',
        'pulse_us_nominal': 8,
        'interval_us_nominal': 20000,
        'phase_shift_us': 500,
        'phase_every_pulses': 50,
        'max_injection_s': 40,
        'hardware_accessed': False,
    },indent=2, ensure_ascii=False)+'\n')
    print('WORKSPACE PREPARADO:',target)
    print('CODIGO ORIGINAL PRESERVADO:',main_c)
    print('VARIANTE:',target/'main.c')
    print('MANIFESTO:',target/'MANIFESTO_PHASE20.json')
    print('Nenhum firmware gravado e nenhuma porta serial acessada.')
    print('Compile quando desejar: cmake -S "'+str(target)+'" -B "'+str(target/'build')+'"')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
