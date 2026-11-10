#!/usr/bin/env python3
"""Comparacao OFFLINE das agendas de pulsos CAN. Nunca acessa serial ou hardware.

ALTO: PRNG xorshift32 do firmware Pico, intervalo uniforme 9375..14375 us.
CANDIDATO: apenas hipotese de agenda, repetindo 32 x 10000 us e
24 x 14375 us, sem autorizar teste eletrico, sem alterar Pico.
"""

from statistics import mean

DURATION_US = 40_000_000
PULSE_US = 8
SEED_OFFICIAL = 0x02AE6661


def high_original(seed=SEED_OFFICIAL, duration_us=DURATION_US):
    value = seed
    current = 0
    timestamps = []
    intervals = []
    while True:
        value ^= (value << 13) & 0xFFFFFFFF
        value ^= value >> 17
        value ^= (value << 5) & 0xFFFFFFFF
        value &= 0xFFFFFFFF
        gap = 9375 + value % (14375 - 9375 + 1)
        current += gap
        if current >= duration_us:
            break
        timestamps.append(current)
        intervals.append(gap)
    return timestamps, intervals


def candidate_timing(duration_us=DURATION_US):
    current = 0
    timestamps = []
    intervals = []
    i = 0
    while True:
        gap = 10000 if i % 56 < 32 else 14375
        current += gap
        if current >= duration_us:
            break
        timestamps.append(current)
        intervals.append(gap)
        i += 1
    return timestamps, intervals


def summary(label, times, intervals):
    active = len(times) * PULSE_US
    print(label)
    print(f"  pulsos: {len(times)}")
    print(f"  intervalo minimo: {min(intervals)} us")
    print(f"  intervalo maximo: {max(intervals)} us")
    print(f"  intervalo medio: {mean(intervals):.1f} us")
    print(f"  tempo nominal total de acionamento: {active / 1000:.3f} ms")
    print(f"  fracao nominal de acionamento: {100 * active / DURATION_US:.5f}%")
    print()


if __name__ == '__main__':
    x, a = high_original()
    y, b = candidate_timing()
    print("ANALISE APENAS MATEMATICA: NAO VERIFICA CORRENTE, TENSAO OU SEGURANCA ELETRICA")
    summary('ALTO oficial, seed 0x02AE6661', x, a)
    summary('Candidato de distribuicao temporal — NAO VALIDADO', y, b)
    assert min(b) >= 9375 and max(b) <= 14375
    print('OBS: nao ha sincronismo eletrico com o CAN, nem previsao de erros/Bus-Off.')
