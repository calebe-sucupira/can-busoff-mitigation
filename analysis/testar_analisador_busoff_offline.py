#!/usr/bin/env python3
"""Testes de parser com ZIPs sintéticos; nenhum hardware é acessado."""
import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from analisar_run_busoff import analyze

HEADER = 'timestamp_us,node,event,sequence,tec,rec,state,mode,detail\n'


def csvlog(items, dev):
    lines = [HEADER]
    logs = []
    for host_ns, us, event, seq, tec, rec, state, mode, detail in items:
        lines.append(f'{us},{dev},{event},{seq},{tec},{rec},{state},{mode},{detail}\n')
        logs.append(f'{host_ns}\tDATA,{us},{event},{seq},{tec},{rec},{state},{mode},{detail}\n')
    return ''.join(lines), ''.join(logs)


def build_zip(path, busoff):
    start = 1_000_000_000
    pico = [(start, 100, 'NOISE_START', -1, 0, 0, '-', '-',
             'run_id=999;profile=BAIXO;interval_min_us=40000;interval_max_us=60000')]
    if busoff:
        pico.append((start + 500_000_000, 200, 'TEST_ABORTED', -1, 0, 0, '-', '-',
                     'run_id=999;pulses=9'))
    else:
        pico.extend([(start + 600_000_000, 200, 'NOISE_END', -1, 0, 0, '-', '-',
                      'run_id=999;pulses=9'),
                     (start + 800_000_000, 300, 'TEST_END', -1, 0, 0, '-', '-',
                      'run_id=999;pulses=9')])
    a = [(start + 100_000_000, 1000, 'SAMPLE', -1, 90, 0, 'ACTIVE', 'NORMAL',
          'tec_peak=93;produced=10;submitted=10;tx_ok=8;gap=0;pending=0;lost=0'),
         (start + 200_000_000, 2000, 'SAMPLE', -1, 100, 0, 'WARNING', 'ALERT',
          'tec_peak=108;produced=20;submitted=18;tx_ok=16;gap=2;pending=1;lost=0'),
         (start + 280_000_000, 2800, 'TX_SUCCESS', 15, -1, -1, '-', '-', 'latency_us=1030')]
    if busoff:
        a.extend([(start + 320_000_000, 3200, 'SAMPLE', -1, 128, 0, 'PASSIVE', 'CRITICAL',
                   'tec_peak=140;produced=30;submitted=24;tx_ok=20;gap=6;pending=1;lost=0'),
                  (start + 390_000_000, 3900, 'STATE_CHANGE', -1, -1, -1, '-', '-',
                   'PASSIVE->BUS_OFF'),
                  (start + 420_000_000, 4200, 'SAMPLE', -1, 128, 0, 'BUS_OFF', 'CRITICAL',
                   'tec_peak=128;produced=39;submitted=30;tx_ok=20;gap=9;pending=0;lost=0'),
                  (start + 630_000_000, 6300, 'STATE_CHANGE', -1, -1, -1, '-', '-',
                   'BUS_OFF->ACTIVE')])
    else:
        a.append((start + 350_000_000, 3500, 'SAMPLE', -1, 60, 0, 'ACTIVE', 'NORMAL',
                  'tec_peak=111;produced=40;submitted=40;tx_ok=39;gap=0;pending=0;lost=0'))
    b = [(start + 300_000_000, 3100, 'RECEIVED', 15, -1, -1, '-', '-', 'id=0x100')]
    meta = {'run': 999, 'condition': 'REFERENCIA', 'expected_throttling': 0,
            'planned': {'profile': 'BAIXO', 'seed_hex': '0x6d2b79f5',
                        'interval_min_us': 40000, 'interval_max_us': 60000}}
    qc = {'run': 999, 'valid': not busoff,
          'observation_status': 'BUS_OFF_OBSERVED_ABORTED' if busoff else 'FULL_DURATION_VERIFIED',
          'bus_off_detected': busoff, 'stop_command_sent': busoff,
          'stop_acknowledged': busoff, 'pico_idle_confirmed': busoff}
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('metadata.json', json.dumps(meta))
        z.writestr('qc.json', json.dumps(qc))
        for key, data in [('pico', pico), ('node_a', a), ('node_b', b)]:
            cs, ls = csvlog(data, key)
            z.writestr(f'{key}.csv', cs)
            z.writestr(f'{key}.log', ls)


class Checks(unittest.TestCase):
    def test_busoff_abort_valid_as_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            zip_path = base / 'run_999_injection.zip'
            build_zip(zip_path, busoff=True)
            summary = analyze(zip_path, base / 'output')
            self.assertTrue(summary['bus_off_raw'])
            self.assertFalse(summary['qc_valid'] == 'true')
            self.assertEqual(summary['first_busoff_event'], 'STATE_CHANGE')
            self.assertAlmostEqual(summary['first_busoff_approx_since_noise_s'], .39)
            self.assertEqual(summary['max_tec_peak_in_injection'], 140)
            self.assertTrue(summary['observed_tec_ge_128'])
            self.assertTrue(summary['stop_ack'])
            self.assertTrue((base/'output'/'run_999'/'progressao_tec.csv').is_file())

    def test_complete_without_busoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            zip_path = base / 'run_999_injection.zip'
            build_zip(zip_path, busoff=False)
            summary = analyze(zip_path, base/'output')
            self.assertFalse(summary['bus_off_raw'])
            self.assertEqual(summary['pico_end_event'], 'NOISE_END')
            self.assertEqual(summary['observation_status'], 'FULL_DURATION_VERIFIED')
            self.assertEqual(summary['max_tec_peak_in_injection'], 111)
            self.assertFalse(summary['observed_tec_ge_128'])

    def test_recovery_is_not_new_busoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            zip_path = base / 'run_999_injection.zip'
            build_zip(zip_path, busoff=True)
            summary = analyze(zip_path, base/'output')
            self.assertEqual(summary['first_busoff_node_a_us'], 3900)
            with (base/'output'/'run_999'/'eventos_criticos.csv').open() as f:
                events = list(csv.DictReader(f))
            rec = next(x for x in events if x['detail'] == 'BUS_OFF->ACTIVE')
            self.assertEqual(rec['bus_off_entry'], 'False')


if __name__ == '__main__':
    unittest.main(verbosity=2)
