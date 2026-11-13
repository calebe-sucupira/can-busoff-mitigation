#!/usr/bin/env python3
"""Regressao offline do host. Simula serial; nao abre portas nem gera pulsos."""
import importlib.util
import json
import queue
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
FILENAME = ROOT / 'executar_campanha_CAN_phase20.py'
spec = importlib.util.spec_from_file_location('runner_busoff', FILENAME)
runner = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)

class FakeSerialCapture:
    instances = {}
    stop_sent = 0
    active = False
    plan = None

    def __init__(self, name, port, baud, folder, stop, fault):
        self.name = name
        self.events = queue.Queue()
        self.errors = []
        self.lines = 5
        self.fault = fault
        self.stop = stop
        self.commands = []
        self.folder = folder
        self.closed = False
        self.__class__.instances[name] = self
        (folder / (name + '.csv')).write_text('timestamp_us,node,event,sequence,tec,rec,state,mode,detail\n')
        if name == 'node_a':
            raw = ('I (1) NODE_A: node-a-throttling-v1.3 | TWAI 125000 bit/s, throttling=0, rates=100/50/25 Hz\n'
                   '11\tDATA,100,SAMPLE,-1,0,0,ACTIVE,NORMAL,test=1\n'
                   '12\tDATA,200,SAMPLE,-1,0,0,ACTIVE,NORMAL,test=1\n')
        elif name == 'node_b':
            raw = ('11\tDATA,100,SAMPLE,-1,0,0,ACTIVE,-,test=1\n'
                   '12\tDATA,200,SAMPLE,-1,0,0,ACTIVE,-,test=1\n')
        else:
            raw = '11\tDATA,100,READY,-1,0,0,-,-,WAITING_COMMAND\n'
        (folder / (name + '.log')).write_text(raw)

    def send(self, text, emergency=False):
        self.commands.append((text,emergency))
        if self.name != 'pico': return
        p = self.__class__.plan
        def add(event, ts, detail):
            self.events.put(runner.parse_data_line(f'DATA,{ts},{event},-1,0,0,-,-,{detail}'))
        if text == '?':
            add('STATUS', 1, f'firmware={runner.VERSION};state=IDLE;run_id={p.run}')
        elif text.startswith('CFG,'):
            add('CONFIG_OK', 2, f'run_id={p.run};profile={p.profile};interval_min_us={p.minimum};interval_max_us={p.maximum};seed=0x{p.seed:08x};injection_us={p.duration * 1000000}')
        elif text == 's':
            self.__class__.active = True
            add('TEST_START', 3, f'run_id={p.run};profile={p.profile};injection_us={p.duration*1000000};baseline_us=5000000;recovery_us=5000000')
            add('NOISE_START', 1000000, f'run_id={p.run};profile={p.profile};interval_min_us={p.minimum};interval_max_us={p.maximum};seed=0x{p.seed:08x};pulse_us=8')
            add('NOISE_END', 1000000+p.duration*1000000, f'run_id={p.run};pulses={runner.ideal_pulses(p.seed,p.minimum,p.maximum,p.duration)}')
            add('TEST_END', 1000000+p.duration*1000000+5000000, f'run_id={p.run};pulses={runner.ideal_pulses(p.seed,p.minimum,p.maximum,p.duration)};missed_deadlines=0;max_late_us=0')
        elif text == 'x':
            self.__class__.stop_sent += 1
            self.__class__.active = False
            add('TEST_ABORTED', 99, 'run_id=998;pulses=0')
            add('TEST_ABORTED', 100, f'run_id={p.run};pulses=0')

    def close(self):
        self.closed = True


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        FakeSerialCapture.instances = {}
        FakeSerialCapture.stop_sent = 0
        FakeSerialCapture.active = False
        self.plan = runner.PlannedRun(999, 'ALTO', 9375, 14375, 0x6D2B79F5, 5, -1, 'REFERENCIA', 0, 0)
        FakeSerialCapture.plan = self.plan
        self.args = SimpleNamespace(output=Path(self.folder.name), node_a='/not-a-real-port-0', node_b='/not-a-real-port-1', pico='/not-a-real-port-2', baud=115200, node_a_binary=None)
        self.fake_wait_event = runner.wait_event
        self.sleep_patch = patch.object(runner.time,'sleep',lambda _:None)
        self.serial_patch = patch.object(runner, 'SerialCapture', FakeSerialCapture)
        self.sleep_patch.start()
        self.serial_patch.start()

    def tearDown(self):
        self.serial_patch.stop()
        self.sleep_patch.stop()
        self.folder.cleanup()

    def run_case(self, trigger=None):
        if trigger:
            def injecting_wait_event(pico, event, timeout, stop, node_a=None, fault=None):
                if event == 'NOISE_END':
                    trigger(node_a, fault)
                return self.fake_wait_event(pico,event,timeout,stop,node_a=node_a,fault=fault)
            with patch.object(runner,'wait_event',injecting_wait_event):
                result = runner.run_one(self.plan, self.args)
        else:
            result = runner.run_one(self.plan, self.args)
        return result

    def test_state_change_busoff_stops_pico_and_preserves_zip(self):
        def trigger(node_a,fault):
            node_a.events.put(runner.parse_data_line('DATA,2000000,STATE_CHANGE,-1,-1,-1,-,-,PASSIVE->BUS_OFF'))
        out = self.run_case(trigger)
        self.assertTrue(out['bus_off_detected'])
        self.assertTrue(out['stop_command_sent'])
        self.assertTrue(out['stop_acknowledged'])
        self.assertTrue(out['pico_idle_confirmed'])
        self.assertEqual(out['observation_status'],'BUS_OFF_OBSERVED_ABORTED')
        self.assertEqual(out['first_bus_off_event']['node_a_timestamp_us'],2000000)
        self.assertEqual(out['post_bus_off_observation_s'],2.0)
        self.assertFalse(out['valid'])
        self.assertEqual(FakeSerialCapture.stop_sent,1)
        self.assertFalse(FakeSerialCapture.active)
        control = Path(self.folder.name) / 'raw/run_999_injection/control_events.jsonl'
        self.assertIn('STOP_RESULT',control.read_text())
        import zipfile
        with zipfile.ZipFile(Path(self.folder.name)/'zips/run_999_injection.zip') as z:
            self.assertIsNone(z.testzip())
            self.assertIn('qc.json',z.namelist())
            self.assertTrue(json.loads(z.read('qc.json'))['bus_off_detected'])

    def test_failure_other_serial_triggers_stop_without_killing_pico_capture(self):
        def trigger(node_a,fault):
            fault.set()
        out = self.run_case(trigger)
        self.assertFalse(out['bus_off_detected'])
        self.assertTrue(out['stop_acknowledged'])
        self.assertTrue(out['pico_idle_confirmed'])
        self.assertEqual(FakeSerialCapture.stop_sent,1)
        self.assertEqual(out['observation_status'],'ABORTED_OTHER')

    def test_complete_run_valid(self):
        out = self.run_case()
        self.assertTrue(out['valid'])
        self.assertEqual(out['observation_status'],'FULL_DURATION_VERIFIED')
        self.assertFalse(out['bus_off_detected'])
        self.assertEqual(FakeSerialCapture.stop_sent,0)

    def test_busoff_sample_detected_but_recovery_ignored(self):
        sample = runner.parse_data_line('DATA,2000000,SAMPLE,-1,128,0,BUS_OFF,CRITICAL,tec_peak=256')
        recovery = runner.parse_data_line('DATA,2000000,STATE_CHANGE,-1,-1,-1,-,-,BUS_OFF->ACTIVE')
        self.assertTrue(runner.bus_off_detected(sample))
        self.assertFalse(runner.bus_off_detected(recovery))

    def test_ctrl_c_triggers_stop(self):
        def trigger(node_a, fault):
            raise KeyboardInterrupt()
        out = self.run_case(trigger)
        self.assertEqual(FakeSerialCapture.stop_sent, 1)
        self.assertTrue(out['stop_acknowledged'])
        self.assertEqual(out['observation_status'], 'ABORTED_OTHER')

    def test_absent_ack_is_reported_without_claiming_safe_stop(self):
        def trigger(node_a, fault):
            node_a.events.put(runner.parse_data_line('DATA,2000000,STATE_CHANGE,-1,-1,-1,-,-,PASSIVE->BUS_OFF'))
        with patch.object(runner, 'wait_abort_ack', lambda pico, stop, run_id: None):
            out = self.run_case(trigger)
        self.assertTrue(out['stop_command_sent'])
        self.assertFalse(out['stop_acknowledged'])
        self.assertFalse(out['pico_idle_confirmed'])
        self.assertTrue(any('Parada logica' in x for x in out['warnings']))

    def test_stop_is_attempted_even_if_control_log_fails(self):
        original = runner.control_event
        def fail_stop_logging(f,event_name,**kwargs):
            if event_name=='STOP_RESULT':
                raise OSError('I/O failure after stop command')
            return original(f,event_name,**kwargs)
        def trigger(node_a,fault):
            node_a.events.put(runner.parse_data_line('DATA,2000000,STATE_CHANGE,-1,-1,-1,-,-,PASSIVE->BUS_OFF'))
        with patch.object(runner,'control_event',fail_stop_logging):
            out = self.run_case(trigger)
        self.assertEqual(FakeSerialCapture.stop_sent,1)
        self.assertTrue(out['stop_acknowledged'])
        self.assertTrue(any('Falha no log' in w for w in out['warnings']))


if __name__=='__main__':
    print('TESTES COM PORTAS SERIAIS FALSAS; NENHUM HARDWARE E ACESSADO.')
    unittest.main(verbosity=2)
