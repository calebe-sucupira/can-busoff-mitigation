#!/usr/bin/env python3
"""Testes do coordenador integral; nenhum acesso a hardware ou ESP-IDF."""
import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('integral_phase20', HERE/'executar_campanha_integral_phase20.py')
co = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = co
spec.loader.exec_module(co)
runner = co.load_runner(HERE/'executar_campanha_CAN_phase20.py')


def fake_zip(path, run, mode, kind='busoff', recovery=True, stop_ack=True, extra_busoff=False):
    parts = []
    if kind == 'busoff':
        parts.append('1000000000\tDATA,1000,STATE_CHANGE,-1,-1,-1,-,-,PASSIVE->BUS_OFF')
        if extra_busoff:
            parts.append('1100000000\tDATA,1500,STATE_CHANGE,-1,-1,-1,-,-,ACTIVE->BUS_OFF')
        if recovery:
            parts.append('1100000001\tDATA,1800,STATE_CHANGE,-1,-1,-1,-,-,BUS_OFF->ACTIVE')
    base = 1800000000 if kind == 'busoff' else 1000000000
    for i in range(5):
        parts.append(f'{base+i*120000000}\tDATA,{2000+i*100},SAMPLE,-1,0,0,ACTIVE,NORMAL,tec_peak=0')
    for i in range(25):
        parts.append(f'{base+i*20000000}\tDATA,{2000+i*10},TX_SUCCESS,{i},-1,-1,-,-,latency_us=900')
    events = '\n'.join(parts)+'\n'
    qc = {'run':run, 'condition':mode, 'valid':kind != 'busoff',
          'observation_status': 'BUS_OFF_OBSERVED_ABORTED' if kind == 'busoff' else 'FULL_DURATION_VERIFIED',
          'bus_off_detected':kind == 'busoff', 'stop_command_sent':stop_ack,
          'stop_acknowledged':stop_ack,'pico_idle_confirmed':stop_ack,'warnings':[]}
    pico = (f'500000000\tDATA,100,NOISE_START,-1,0,0,-,-,run_id={run};profile=PHASE20\n'
            f'1300000000\tDATA,200,TEST_ABORTED,-1,0,0,-,-,run_id={run};pulses=50\n'
            f'1400000000\tDATA,300,STATUS,-1,0,0,-,-,state=IDLE;run_id={run}\n') if kind == 'busoff' else (
            f'500000000\tDATA,100,NOISE_START,-1,0,0,-,-,run_id={run};profile=PHASE20\n'
            f'4000000000\tDATA,200,NOISE_END,-1,0,0,-,-,run_id={run};pulses=1999\n'
            f'5000000000\tDATA,300,TEST_END,-1,0,0,-,-,run_id={run};pulses=1999\n')
    with zipfile.ZipFile(path,'w') as z:
        for name, data in {'qc.json':json.dumps(qc), 'metadata.json':json.dumps({
                'run':run,'condition':mode,'expected_throttling':0 if mode=='REFERENCIA' else 1}),
                'node_a.log':events, 'node_b.log':'', 'pico.log':pico, 'control_events.jsonl':''}.items():
            z.writestr(name,data)
    return qc


class CampaignChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def plan(self, run=304, mode='ADAPTATIVO'):
        return runner.PlannedRun(run,'PHASE20',20000,20000,0x6D2B79F5,40,1999,
                                 mode, 1 if mode=='ADAPTATIVO' else 0,1)

    def test_plan_40_and_blocks(self):
        plans, blocks = co.load_and_validate_plan(runner,HERE/'plano_campanha_phase20_40_runs.csv')
        self.assertEqual(len(plans),40)
        self.assertEqual(sum(x.condition=='ADAPTATIVO' for x in plans),20)
        self.assertEqual(blocks[0], [1,'ADAPTATIVO',5])
        self.assertEqual(blocks[-1], [8,'REFERENCIA',5])

    def test_busoff_with_recovery_is_valid_result(self):
        plan=self.plan()
        path=self.root/'yes.zip'
        qc=fake_zip(path,304,'ADAPTATIVO')
        self.assertEqual(co.verify_run_zip(path,plan,qc)['status'],'BUS_OFF')

    def test_busoff_without_ack_stops(self):
        p=self.plan(); f=self.root/'no_ack.zip'
        qc=fake_zip(f,304,'ADAPTATIVO',stop_ack=False)
        with self.assertRaisesRegex(RuntimeError,'confirmacao'):
            co.verify_run_zip(f,p,qc)

    def test_busoff_without_recovery_stops(self):
        p=self.plan(); f=self.root/'no_rec.zip'
        qc=fake_zip(f,304,'ADAPTATIVO',recovery=False)
        with self.assertRaisesRegex(RuntimeError,'BUS_OFF->ACTIVE'):
            co.verify_run_zip(f,p,qc)

    def test_repeated_busoff_stops(self):
        p=self.plan(); f=self.root/'double.zip'
        qc=fake_zip(f,304,'ADAPTATIVO',extra_busoff=True)
        with self.assertRaisesRegex(RuntimeError,'entradas BUS_OFF=2'):
            co.verify_run_zip(f,p,qc)

    def test_complete_without_busoff_is_accepted(self):
        p=self.plan(); f=self.root/'full.zip'
        qc=fake_zip(f,304,'ADAPTATIVO',kind='full')
        self.assertEqual(co.verify_run_zip(f,p,qc)['status'],'FULL_DURATION')

    def test_one_command_switches_firmware_and_continues_busoff(self):
        plans=[self.plan(304,'ADAPTATIVO'),self.plan(305,'ADAPTATIVO'),self.plan(306,'REFERENCIA')]
        calls=[]; flashes=[]; slept=[]
        targets={'ADAPTATIVO':(self.root/'a',self.root/'adapt.bin'),
                 'REFERENCIA':(self.root/'r',self.root/'ref.bin')}
        for pth in [targets['ADAPTATIVO'][1],targets['REFERENCIA'][1]]:
            pth.write_bytes(b'firmware')
        args=SimpleNamespace(resume=False,skip_first_flash=True,node_a='/dev/mock',node_b='/dev/mock',
                             pico='/dev/mock',baud=115200,idf_bin='mock',between=30,
                             approved_binary_sha256={'ADAPTATIVO':co.sha256(targets['ADAPTATIVO'][1]),
                                                     'REFERENCIA':co.sha256(targets['REFERENCIA'][1])})
        output=self.root/'output'; (output/'zips').mkdir(parents=True)
        def fake_run(plan,args):
            calls.append(plan.run)
            zp=args.output/'zips'/f'run_{plan.run}_injection.zip'
            return fake_zip(zp,plan.run,plan.condition,kind='busoff')
        result=co.campaign(plans,runner,output,targets,args,self.root/'j.log',
            flash_func=lambda proj,port,idf: flashes.append(str(proj)),
            run_func=fake_run,sleep=lambda s:slept.append(s))
        self.assertEqual(calls,[304,305,306])
        self.assertEqual(flashes,[str(self.root/'r')])
        self.assertEqual(slept,[30,30])
        self.assertTrue(all(r['bus_off'] for r in result))

    def test_failure_halts_future_runs(self):
        plans=[self.plan(304),self.plan(305)]
        targets={'ADAPTATIVO':(self.root/'a', self.root/'a.bin')}
        targets['ADAPTATIVO'][1].write_bytes(b'F')
        args=SimpleNamespace(resume=False,skip_first_flash=True,node_a='mock',node_b='mock',
                             pico='mock',baud=115200,idf_bin='mock',between=30,
                             approved_binary_sha256={'ADAPTATIVO':co.sha256(targets['ADAPTATIVO'][1])})
        output=self.root/'output'; (output/'zips').mkdir(parents=True)
        count=[]
        def fake_run(plan,args):
            count.append(plan.run)
            return fake_zip(args.output/'zips'/f'run_{plan.run}_injection.zip',plan.run,
                            plan.condition,stop_ack=False)
        with self.assertRaises(RuntimeError):
            co.campaign(plans,runner,output,targets,args,self.root/'j.log',
                flash_func=lambda *a:None,run_func=fake_run,sleep=lambda s:None)
        self.assertEqual(count,[304])

    def test_resume_flashes_first_remaining(self):
        plans=[self.plan(304),self.plan(305)]
        targets={'ADAPTATIVO':(self.root/'a', self.root/'a.bin')}
        targets['ADAPTATIVO'][1].write_bytes(b'F')
        args=SimpleNamespace(resume=True,skip_first_flash=True,node_a='mock',node_b='mock',
                             pico='mock',baud=115200,idf_bin='mock',between=30,
                             approved_binary_sha256={'ADAPTATIVO':co.sha256(targets['ADAPTATIVO'][1])})
        out=self.root/'data'; (out/'zips').mkdir(parents=True)
        fake_zip(out/'zips'/'run_304_injection.zip',304,'ADAPTATIVO')
        flash_log=[]; calls=[]
        def fake_run(p,a):
            calls.append(p.run)
            return fake_zip(a.output/'zips'/f'run_{p.run}_injection.zip',p.run,p.condition)
        co.campaign(plans,runner,out,targets,args,self.root/'j.log',
            flash_func=lambda *a:flash_log.append(1),run_func=fake_run,sleep=lambda t:None)
        self.assertEqual(calls,[305])
        self.assertEqual(flash_log,[1])


if __name__ == '__main__':
    unittest.main(verbosity=2)
