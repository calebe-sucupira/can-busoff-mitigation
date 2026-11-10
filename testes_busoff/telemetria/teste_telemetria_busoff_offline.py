#!/usr/bin/env python3
"""Valida a logica da variante de marcos no computador, sem acessar hardware."""
from pathlib import Path

MARKERS=(160,192,224,240)

def trace(seq):
    reported=0
    out=[]
    for tec in seq:
        mask=sum((1<<i) for i,t in enumerate(MARKERS) if tec>=t)
        if mask & ~reported:
            out.append(tec)
        reported |= mask
    return out

assert trace([0,90,127,143,160,159,170,191,192,210,225,241]) == [160,192,225,241]
assert trace([0,255,1,255]) == [255]
assert trace([0,120,140,156]) == []
assert trace([160,155,160,170,192,180,192]) == [160,192]
assert len(trace(list(range(0,256)))) == 4
src=Path(__file__).with_name('main_busoff_trace.c').read_text()
assert 'reported_tec_markers' in src and 'new_tec_marker' in src
assert 'state_changed || heartbeat || new_tec_marker' in src
assert 'node-a-throttling-v1.3-busoff-trace' in src
print('OK: 5 verificacoes da logica de marcos e 3 verificacoes textuais.')
print('NAO representa compilacao C nem teste em ESP32.')
