#!/usr/bin/env python3
import queue
import threading
import unittest
from types import SimpleNamespace
from executar_campanha_CAN_seguro import (
    BusOffDetected, bus_off_detected, check_node_a_bus_off,
    parse_data_line, wait_abort_ack, wait_event,
)

class FakePico:
    def __init__(self, entries):
        self.events = queue.Queue()
        for entry in entries:
            self.events.put(parse_data_line(entry))

class TesteSeguranca(unittest.TestCase):
    def test_detecta_entrada_bus_off(self):
        for line in (
            'DATA,100,STATE_CHANGE,-1,-1,-1,-,-,PASSIVE->BUS_OFF',
            'DATA,101,SAMPLE,-1,256,0,BUS_OFF,CRITICAL,tec_peak=256;lost=0',
        ):
            self.assertTrue(bus_off_detected(parse_data_line(line)))

    def test_nao_confunde_saida_do_bus_off(self):
        for line in (
            'DATA,100,STATE_CHANGE,-1,-1,-1,-,-,BUS_OFF->ACTIVE',
            'DATA,101,SAMPLE,-1,120,0,PASSIVE,CRITICAL,tec_peak=145;lost=0',
            'DATA,102,RECOVERY,-1,-1,-1,-,-,result=ESP_OK',
        ):
            self.assertFalse(bus_off_detected(parse_data_line(line)))

    def test_guard_interrompe_espera(self):
        a = FakePico(['DATA,100,STATE_CHANGE,-1,-1,-1,-,-,PASSIVE->BUS_OFF'])
        p = FakePico([])
        with self.assertRaises(BusOffDetected):
            wait_event(p, 'NOISE_END', timeout=.3, stop=threading.Event(), node_a=a)

    def test_parada_confirmada(self):
        p = FakePico(['DATA,101,COMMAND,-1,0,0,-,-,STOP_REQUEST',
                      'DATA,102,TEST_ABORTED,-1,0,0,-,-,run_id=300;pulses=5'])
        event = wait_abort_ack(p, threading.Event(), timeout=.3)
        self.assertEqual(event['event'], 'TEST_ABORTED')

    def test_estado_inicial_normal(self):
        a = FakePico(['DATA,100,STATE_CHANGE,-1,-1,-1,-,-,ACTIVE->PASSIVE'])
        check_node_a_bus_off(a)
        p = FakePico(['DATA,101,NOISE_END,-1,0,0,-,-,run_id=999;pulses=42'])
        event = wait_event(p,'NOISE_END',timeout=.3,stop=threading.Event(),node_a=a)
        self.assertEqual(event['event'], 'NOISE_END')

if __name__ == '__main__':
    unittest.main(verbosity=2)
