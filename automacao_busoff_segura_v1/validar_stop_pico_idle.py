#!/usr/bin/env python3
"""Verifica comando x somente com Pico em IDLE. Nao inicia ensaios."""
import argparse
import time


def read_event(port, name, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        raw = port.readline()
        if not raw:
            continue
        line = raw.decode('utf-8', errors='replace').strip()
        if line.startswith('DATA,'):
            parts = line.split(',', 8)
            if len(parts) == 9 and parts[2] == name:
                return parts[8]
    raise TimeoutError(f'Sem confirmacao {name}.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='/dev/ttyACM1')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        print('SIMULACAO: apenas consultas ? e comando x; NUNCA envia s ou CFG.')
        print(f'Porta prevista: {args.port}')
        return
    import serial
    with serial.Serial(args.port, 115200, timeout=0.1, write_timeout=1,
                       dsrdtr=False, rtscts=False) as port:
        port.dtr = True
        port.rts = False
        time.sleep(2)
        port.reset_input_buffer()
        port.write(b'?')
        port.flush()
        status = read_event(port, 'STATUS', 6)
        print('STATUS inicial:', status)
        if 'state=IDLE' not in status or 'firmware=pico-param-v1.5' not in status:
            raise RuntimeError('Pico nao esta ocioso ou versao inesperada: NENHUM STOP enviado.')
        port.write(b'x')
        port.flush()
        stopped = read_event(port, 'TEST_ABORTED', 6)
        print('TEST_ABORTED:', stopped)
        port.write(b'?')
        port.flush()
        status = read_event(port, 'STATUS', 6)
        print('STATUS final:', status)
        if 'state=IDLE' not in status:
            raise RuntimeError('Pico nao confirmou IDLE final.')
        print('STOP LOGICO VALIDADO, SEM INICIAR PULSOS. Estado eletrico GP2 NAO aferido.')


if __name__ == '__main__':
    main()
