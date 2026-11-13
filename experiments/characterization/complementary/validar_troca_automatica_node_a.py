#!/usr/bin/env python3
"""Valida alternancia de dois aplicativos do No A. Nao acessa Pico nem executa ensaios."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BIN_DIR = ROOT / 'binarios_node_a_complementar'
EXPECTED_MODES = (
    ('REFERENCIA', 'node_a_referencia.bin', 0),
    ('ADAPTATIVO', 'node_a_adaptativo.bin', 1),
)
STARTUP = re.compile(r'TWAI\s+125000\s+bit/s,\s*throttling=([01]),\s*rates=100/50/25\s+Hz')
MAC_LINE = re.compile(r'MAC:\s*([0-9a-f:]{17})', flags=re.IGNORECASE)


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as src:
        for part in iter(lambda: src.read(131072), b''):
            h.update(part)
    return h.hexdigest()


def preflight(root):
    folder = root / 'binarios_node_a_complementar'
    manifest_file = folder / 'manifesto_binarios.json'
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    if manifest.get('app_flash_offset') != '0x10000':
        raise ValueError('Offset de aplicacao inesperado no manifesto.')
    if manifest.get('partition_tables_identical') is not True:
        raise ValueError('Tabelas de particoes nao estao confirmadas como identicas.')
    if manifest.get('sdkconfigs_identical') is not True:
        raise ValueError('sdkconfigs nao estao confirmadas como identicas.')
    results = []
    for mode, basename, flag in EXPECTED_MODES:
        binary = folder / basename
        if not binary.is_file() or binary.stat().st_size < 8192:
            raise ValueError(f'Arquivo binario ausente ou incompleto: {binary}')
        with binary.open('rb') as f:
            if f.read(1) != b'\xe9':
                raise ValueError(f'Cabecalho de aplicacao ESP32 invalido: {binary}')
        entry = manifest.get('images', {}).get(mode, {})
        digest = sha256(binary)
        if entry.get('sha256') != digest:
            raise ValueError(f'Hash do binario {mode} nao coincide com o manifesto.')
        if entry.get('enable_throttling') != flag:
            raise ValueError(f'Valor ENABLE_THROTTLING nao coincide no manifesto: {mode}')
        results.append((mode, binary, flag, digest))
    if results[0][3] == results[1][3]:
        raise ValueError('As imagens nao podem ser identicas.')
    return results


def run_esptool(port, *cmd):
    result = subprocess.run(
        [sys.executable, '-m', 'esptool', '--chip', 'esp32', '--port', port, *cmd],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=90, check=False,
    )
    print(result.stdout, end='' if result.stdout.endswith('\n') else '\n', flush=True)
    if result.returncode:
        raise RuntimeError(f'esptool retornou erro (codigo {result.returncode}).')
    return result.stdout


def identify_board(port, expected_mac):
    print(f'\nVerificando a placa em {port}...', flush=True)
    out = run_esptool(port, 'flash-id')
    m = MAC_LINE.search(out)
    if not m:
        raise RuntimeError('MAC da placa nao foi identificada; nao iniciar gravacao.')
    actual = m.group(1).lower()
    if actual != expected_mac.lower():
        raise RuntimeError(f'MAC inesperada: {actual}; esperada: {expected_mac}. Nao gravar.')
    print(f'MAC confirmada: {actual}', flush=True)


def capture_startup(port, expected_flag, seconds, log_path):
    try:
        import serial
    except ImportError as exc:
        raise RuntimeError('pyserial nao instalado no Python ativo.') from exc

    # Serial so do No A. Nao ha codigo para configurar nem acionar o Pico.
    serial_port = serial.Serial()
    serial_port.port = port
    serial_port.baudrate = 115200
    serial_port.timeout = 0.25
    serial_port.write_timeout = 0.5
    serial_port.rtscts = False
    serial_port.dsrdtr = False
    serial_port.dtr = False
    serial_port.rts = False
    serial_port.open()
    try:
        serial_port.dtr = False
        serial_port.rts = False
        time.sleep(0.15)
        serial_port.reset_input_buffer()
        # Pulso de EN via RTS, mantendo IO0 alto (DTR desativado).
        serial_port.rts = True
        time.sleep(0.18)
        serial_port.rts = False
        deadline = time.monotonic() + seconds
        lines = []
        with log_path.open('w', encoding='utf-8') as log:
            while time.monotonic() < deadline:
                line = serial_port.readline().decode('utf-8', errors='replace').strip()
                if not line:
                    continue
                lines.append(line)
                log.write(line + '\n')
                m = STARTUP.search(line)
                if m:
                    flag = int(m.group(1))
                    print(f'Inicializacao encontrada: {line}', flush=True)
                    if flag != expected_flag:
                        raise RuntimeError(
                            f'Firmware identificado com throttling={flag}, esperado={expected_flag}.')
                    return line
        recent = ' | '.join(lines[-5:]) if lines else '(nenhuma linha recebida)'
        raise RuntimeError(
            f'Nao foi possivel confirmar throttling={expected_flag} em {seconds}s. '
            f'Ultimas linhas: {recent}. Confira o log {log_path}.')
    finally:
        serial_port.close()


def main():
    ap = argparse.ArgumentParser(description='Teste isolado de troca automatica do No A, sem injetor.')
    ap.add_argument('--port', default='/dev/ttyUSB0')
    ap.add_argument('--expected-mac', default='78:1c:3c:dc:39:f8')
    ap.add_argument('--timeout', type=float, default=12.0)
    ap.add_argument('--execute', action='store_true', help='Grava os dois aplicativos no No A; nao injeta pulsos.')
    args = ap.parse_args()
    try:
        if args.timeout < 3:
            raise ValueError('--timeout precisa ser de ao menos 3 segundos.')
        images = preflight(ROOT)
        print('BINARIOS CONFIRMADOS PELO MANIFESTO')
        for mode, binary, flag, digest in images:
            print(f'{mode}: throttling={flag} | {binary.name} | sha256={digest[:16]}...')
        if not args.execute:
            print('SIMULACAO CONCLUIDA. Nenhuma porta aberta e nenhuma gravacao realizada.')
            return 0

        identify_board(args.port, args.expected_mac)
        result_dir = ROOT / 'validacao_troca_node_a'
        result_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        report = {'started_at_utc': datetime.now(timezone.utc).isoformat(),
                  'node_a_port': args.port, 'mac': args.expected_mac, 'runs': []}
        report_path = result_dir / f'teste_{stamp}.json'
        for mode, binary, flag, digest in images:
            row = {'mode': mode, 'throttling_expected': flag,
                   'bin': str(binary), 'sha256': digest, 'status': 'iniciado'}
            report['runs'].append(row)
            report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
            print(f'\nGRAVANDO {mode} (throttling={flag})...', flush=True)
            try:
                run_esptool(args.port, '--baud', '460800', 'write-flash', '0x10000', str(binary))
                time.sleep(1.0)
                logfile = result_dir / f'{stamp}_{mode.lower()}_serial.log'
                startup = capture_startup(args.port, flag, args.timeout, logfile)
                row.update({'status': 'validado', 'boot_message': startup, 'serial_log': str(logfile)})
                print(f'{mode}: OK', flush=True)
            except Exception as exc:
                row.update({'status': 'falhou', 'reason': str(exc)})
                raise
            finally:
                report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        print('\nTROCA AUTOMATICA VALIDADA. Nenhum comando foi enviado ao Pico.')
        print(f'Relatorio: {report_path}')
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired,
            json.JSONDecodeError, KeyError) as exc:
        print(f'ERRO: {exc}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
