#!/usr/bin/env python3
"""Valida a nova agenda temporal apenas por simulacao; nenhum hardware e acessado."""
import csv
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODULE = ROOT / "executar_campanha_CAN_phase20.py"
spec = importlib.util.spec_from_file_location("phase_runner", MODULE)
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)

INTERVAL = 20000
SHIFT = 500
BLOCK = 50


def generate(duration_s):
    timestamp = INTERVAL
    pulse_count = 0
    rows = []
    while timestamp < duration_s * 1_000_000:
        pulse_count += 1
        phase_offset = (((pulse_count - 1) // BLOCK) * SHIFT) % 10000
        rows.append((pulse_count, timestamp, phase_offset))
        timestamp += INTERVAL + (SHIFT if pulse_count % BLOCK == 0 else 0)
    return rows


class ScheduleTests(unittest.TestCase):
    def test_pulses_match_host_prediction(self):
        for duration_s in (5, 10, 20, 40):
            a = generate(duration_s)
            b = runner.ideal_pulses(0x6d2b79f5, 20000, 20000,
                                    duration_s, "PHASE20")
            self.assertEqual(len(a), b)

    def test_no_interval_shorter_than_historical_minimum(self):
        for a, b in zip(generate(40), generate(40)[1:]):
            self.assertGreaterEqual(b[1] - a[1], 20000)
        self.assertEqual(max(b[1] - a[1]
                             for a, b in zip(generate(40), generate(40)[1:])), 20500)

    def test_phase_shift_every_50_pulses(self):
        rows = generate(40)
        self.assertEqual(rows[0][2], 0)
        self.assertEqual(rows[49][2], 0)
        self.assertEqual(rows[50][2], 500)
        self.assertEqual(rows[100][2], 1000)
        self.assertEqual(rows[1000][2], 0)

    def test_configuration_and_stop_maintained_in_source(self):
        s = (ROOT / 'main_phase20.c').read_text()
        for text in ('"PHASE20"', 'PHASE_INTERVAL_US 20000u',
                     'PHASE_SHIFT_US 500u', 'PHASE_HOLD_PULSES 50u',
                     'injector_prepare_idle(', '"TEST_ABORTED"',
                     '"PHASE_STEP"', 'duration_s > PHASE_MAX_DURATION_S'):
            self.assertIn(text,s)

    def test_plan_parsing_and_reference(self):
        plan = runner.load_plan(ROOT / 'plano_piloto_phase20.csv')
        self.assertEqual(len(plan), 3)
        self.assertEqual({p.condition for p in plan}, {'REFERENCIA'})
        self.assertTrue(all(p.profile == 'PHASE20' for p in plan))

if __name__ == '__main__':
    unittest.main(verbosity=2)
