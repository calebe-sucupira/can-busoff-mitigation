#!/usr/bin/env python3
"""Campanha complementar CAN PHASE20: um comando, varios runs, aborta em falha.

Usa o executor PHASE20 existente, sem alterar o firmware do Pico e sem
modificar componentes das placas. NAO mede corrente, temperatura ou tensoes.
Necessita supervisao presencial, parada fisica acessivel e aprovacao eletrica
independente para uma sequencia longa de injeções CAN_H-CAN_L.
"""
import argparse
import csv
import hashlib
import importlib.util
import json
import re
import shlex
import shutil
import subprocess
import sys
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

RUNNER_FILENAME = 'executar_campanha_CAN_phase20.py'
EXPECTED_RUNNER_SHA256 = '8daf143639fc01b35e6ce23645ef81c9fbaead6e5ccc9f1c0948ab2ad52ccdf1'
EXPECTED_PILOTS = {300: ('REFERENCIA', 0), 303: ('ADAPTATIVO', 1)}
PAUSE_MIN_S = 30  # Espera operacional, nao validacao termica.
PROJECT_DIRECTORY = '_compilacao_telemetria_busoff_2026-10-20'


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for buf in iter(lambda: f.read(1024 * 1024), b''):
            h.update(buf)
    return h.hexdigest()


def must(condition, explanation):
    if not condition:
        raise RuntimeError(explanation)


def load_runner(source, trusted=True):
    must(source.is_file(), f'Executor original nao encontrado: {source}')
    digest = sha256(source)
    if trusted:
        must(digest == EXPECTED_RUNNER_SHA256,
             f'O executor PHASE20 mudou (sha256={digest}). Pare e audite; nao automatizar um codigo desconhecido.')
    spec = importlib.util.spec_from_file_location('executor_phase20_integral_base', source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_lines(raw):
    for line in raw.decode('utf-8', errors='replace').splitlines():
        t, sep, msg = line.partition('\t')
        if sep and t.isdigit() and msg.startswith('DATA,'):
            parts = msg.split(',', 8)
            if len(parts) == 9:
                yield int(t), parts[2], parts[6], parts[8]


def verify_run_zip(zip_path, plan, result):
    must(zip_path.is_file(), f'ZIP nao foi salvo: {zip_path}')
    with zipfile.ZipFile(zip_path) as z:
        must(z.testzip() is None, f'ZIP corrompido: {zip_path}')
        for n in ('qc.json', 'metadata.json', 'node_a.log', 'node_b.log', 'pico.log', 'control_events.jsonl'):
            must(n in z.namelist(), f'{zip_path}: falta {n}')
        qc = json.loads(z.read('qc.json'))
        metadata = json.loads(z.read('metadata.json'))
        node_a_events = list(read_lines(z.read('node_a.log')))
        pico_events = list(read_lines(z.read('pico.log')))
    must(qc['run'] == plan.run == metadata['run'], f'Run divergente em {zip_path}')
    must(qc['condition'] == plan.condition == metadata['condition'], f'Politica divergente em {zip_path}')
    must(metadata['expected_throttling'] == plan.throttling,
         f'Modo inesperado em {zip_path}')
    must(qc['observation_status'] == result['observation_status'], f'QC em disco nao bate com memoria ({plan.run})')
    must(not any('Erro serial' in str(w) or 'Parada logica nao confirmada' in str(w)
                 for w in qc.get('warnings', [])), f'Falha operacional no QC Run {plan.run}')
    pico_idle = [x for x in pico_events if x[1] == 'STATUS' and 'state=IDLE' in x[3]
                 and f'run_id={plan.run}' in x[3]]
    noise = [e for e in pico_events if e[1] == 'NOISE_START' and f'run_id={plan.run}' in e[3]]
    must(len(noise) == 1, f'Run {plan.run}: falta NOISE_START unico na captura do Pico')

    # Bus-Off e um desfecho cientifico; nao e falha operacional se foi corretamente contido.
    if qc['observation_status'] == 'BUS_OFF_OBSERVED_ABORTED':
        for flag in ('bus_off_detected', 'stop_command_sent', 'stop_acknowledged', 'pico_idle_confirmed'):
            must(qc.get(flag) is True, f'Bus-Off Run {plan.run} sem confirmacao: {flag}')
        must(bool(pico_idle), f'Pico nao confirmou STATUS IDLE no log do Run {plan.run}')
        aborts = [e for e in pico_events if e[1] == 'TEST_ABORTED' and f'run_id={plan.run}' in e[3]]
        must(bool(aborts), f'Pico sem TEST_ABORTED para Run {plan.run}')
        enters = [(t, d) for t, ev, state, d in node_a_events
                  if ev == 'STATE_CHANGE' and d.endswith('->BUS_OFF')]
        must(len(enters) == 1, f'Run {plan.run}: entradas BUS_OFF={len(enters)}; parar e investigar')
        entrance_ns = enters[0][0]
        must(entrance_ns >= noise[0][0],
             f'Run {plan.run}: BUS_OFF ocorreu antes de NOISE_START')
        abort_ns = aborts[-1][0]
        must(entrance_ns <= abort_ns,
             f'Run {plan.run}: BUS_OFF aparece depois da parada do Pico')
        recovers = [(t, d) for t, ev, state, d in node_a_events
                    if ev == 'STATE_CHANGE' and d == 'BUS_OFF->ACTIVE' and t > entrance_ns]
        must(bool(recovers), f'Run {plan.run}: nao houve comprovacao BUS_OFF->ACTIVE')
        recovery_ns = recovers[-1][0]
        after_samples = [(t, state, d) for t, ev, state, d in node_a_events
                         if ev == 'SAMPLE' and state == 'ACTIVE' and t >= recovery_ns + 500_000_000]
        after_tx = [t for t, ev, state, d in node_a_events
                    if ev == 'TX_SUCCESS' and t >= recovery_ns + 500_000_000]
        must(len(after_samples) >= 2 and len(after_tx) >= 10,
             f'Run {plan.run}: recuperacao funcional insuficiente (samples={len(after_samples)}, TX={len(after_tx)})')
        # O Pico pode comecar novo teste apenas se voltou a IDLE, e o No A voltou a transmitir.
        return {'status': 'BUS_OFF', 'bus_off': True, 'recovery_proved': True,
                'recovered_tx_success': len(after_tx), 'run': plan.run}

    if qc['observation_status'] == 'FULL_DURATION_VERIFIED':
        must(qc.get('valid') is True, f'Run {plan.run}: valid=false apesar da duracao completa')
        enters = [e for e in node_a_events
                  if e[1] == 'STATE_CHANGE' and e[3].endswith('->BUS_OFF')]
        must(not enters, f'Run {plan.run}: BUS_OFF aparece nos logs, mas nao no QC')
        ends = [e for e in pico_events if e[1] == 'TEST_END' and f'run_id={plan.run}' in e[3]]
        noise_ends = [e for e in pico_events if e[1] == 'NOISE_END' and f'run_id={plan.run}' in e[3]]
        must(bool(ends) and bool(noise_ends), f'Run {plan.run}: Pico sem NOISE_END/TEST_END')
        last_samples = [e for e in node_a_events if e[1] == 'SAMPLE'][-3:]
        must(len(last_samples) >= 2 and all(e[2] == 'ACTIVE' for e in last_samples),
             f'Run {plan.run}: No A nao demonstrou recuperacao estavel em ACTIVE')
        must(any(e[1] == 'TX_SUCCESS' for e in node_a_events),
             f'Run {plan.run}: sem TX_SUCCESS')
        return {'status': 'FULL_DURATION', 'bus_off': False, 'run': plan.run}
    raise RuntimeError(f'Run {plan.run}: estado inesperado {qc["observation_status"]}; nao continuar')


def load_and_validate_plan(runner, path):
    plans = runner.load_plan(path)
    ids = [p.run for p in plans]
    must(ids == list(range(304, 344)), f'Os 40 novos IDs deveriam ser 304..343, encontrado {ids}')
    n = Counter(p.condition for p in plans)
    must(n == {'ADAPTATIVO': 20, 'REFERENCIA': 20}, f'Esperava 20 por politica: {n}')
    must(all(p.profile == 'PHASE20' and p.duration == 40 for p in plans),
         'Plano divergente do perfil PHASE20 de 40 segundos')
    must(all(p.seed == 0x6D2B79F5 for p in plans), 'Semente do piloto nao preservada')
    must(plans[0].condition == 'ADAPTATIVO', 'Primeiro bloco deve ser ADAPTATIVO')
    blocks = []
    for p in plans:
        if not blocks or blocks[-1][0] != p.block:
            blocks.append([p.block, p.condition, 0])
        must(blocks[-1][1] == p.condition, f'Bloco {p.block} misturou politicas')
        blocks[-1][2] += 1
    must([b[2] for b in blocks] == [5,5,5,5,5,5,5,5], f'Tamanhos dos blocos: {blocks}')
    return plans, blocks


def verify_binary_workspace(stage):
    manifest = stage / 'manifesto_compilacao_corrigida.json'
    must(manifest.is_file(), f'Manifesto de compilacao nao encontrado: {manifest}')
    data = json.loads(manifest.read_text(encoding='utf-8'))
    targets = {}
    for name, flag in (('referencia', '0'), ('adaptativo', '1')):
        details = data['builds'][name]
        project = stage / name / 'firmware' / 'node-a'
        actual_binary = (project / 'build' / Path(details['app_bin']).name).resolve()
        must(actual_binary.is_file(), f'Binario nao existe: {actual_binary}')
        must(sha256(actual_binary) == details['app_bin_sha256'],
             f'Binario {name} mudou desde o manifesto')
        must(details['macro_verified'] == f'-DENABLE_THROTTLING={flag}',
             f'Macro {name} incorreta no manifesto')
        targets[name.upper()] = (project, actual_binary)
    must(sha256(targets['REFERENCIA'][1]) != sha256(targets['ADAPTATIVO'][1]),
         'Binarios das duas politicas identicos')
    return targets


def flash(project, port, idf_bin):
    cmd = [str(idf_bin), '-B', 'build', '-p', port, 'flash']
    print('  FLASH: ' + ' '.join(shlex.quote(x) for x in cmd), flush=True)
    completed = subprocess.run(cmd, cwd=project, check=False)
    must(completed.returncode == 0, f'Falha ao gravar Node A: exit={completed.returncode}. NENHUMA INJECAO PERMITIDA.')


def journal(path, **data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8', buffering=1) as f:
        f.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(), **data}, ensure_ascii=False)+'\n')


def verify_pilots(output):
    for run, (condition, flag) in EXPECTED_PILOTS.items():
        path = output / 'zips' / f'run_{run}_injection.zip'
        must(path.is_file(), f'Falta o piloto Run {run}: {path}')
        with zipfile.ZipFile(path) as z:
            must(z.testzip() is None, f'ZIP do piloto {run} corrompido')
            qc = json.loads(z.read('qc.json'))
            meta = json.loads(z.read('metadata.json'))
        must(qc.get('run') == run and qc.get('condition') == condition,
             f'Identificacao inesperada no piloto {run}')
        must(meta.get('expected_throttling') == flag,
             f'Politica divergente no piloto {run}')
        must(qc.get('observation_status') == 'BUS_OFF_OBSERVED_ABORTED' and
             qc.get('stop_acknowledged') is True and qc.get('pico_idle_confirmed') is True,
             f'Run {run} sem desfecho ou STOP/IDLE coerentes')
    return True


def ready_results(zip_path, runner, plan):
    with zipfile.ZipFile(zip_path) as z:
        qc = json.loads(z.read('qc.json'))
    return verify_run_zip(zip_path, plan, qc)


def campaign(plans, runner, output, targets, options, journal_path, flash_func=flash, run_func=None, sleep=time.sleep):
    if run_func is None:
        run_func = runner.run_one
    count = Counter()
    outcomes = []
    current_mode = None
    # Ja gravado com ADAPTATIVO no turno anterior. run_one verifica o boot de toda forma.
    initial_mode = 'ADAPTATIVO' if options.skip_first_flash else None
    for pos, plan in enumerate(plans):
        zip_path = output / 'zips' / f'run_{plan.run}_injection.zip'
        raw_path = output / 'raw' / f'run_{plan.run:03d}_injection'
        if zip_path.exists() or raw_path.exists():
            if not options.resume:
                raise RuntimeError(f'Ja ha arquivos para o Run {plan.run}. Use --resume para pular ZIPs aprovados.')
            must(zip_path.exists(), f'Run {plan.run}: pasta parcial sem ZIP; revise antes de retomar')
            checked = ready_results(zip_path, runner, plan)
            journal(journal_path, event='SKIPPED_VERIFIED', run=plan.run, checked=checked)
            print(f'[Run {plan.run}] Ja coletado e verificado; pulando.', flush=True)
            count[checked['status']] += 1
            outcomes.append(checked)
            continue
        if current_mode != plan.condition:
            if current_mode is None and initial_mode == plan.condition and pos == 0 and not options.resume:
                print('  Primeira politica: ADAPTATIVO ja gravado (sera checado no boot antes da injeção).', flush=True)
                journal(journal_path, event='FLASH_SKIPPED_FIRST', condition=plan.condition)
            else:
                project, binary = targets[plan.condition]
                journal(journal_path, event='FLASH_BEGIN', condition=plan.condition, project=str(project))
                flash_func(project, options.node_a, options.idf_bin)
                # idf.py pode reconstruir antes de gravar; nao aceitar artefato alterado.
                must(sha256(binary) == options.approved_binary_sha256[plan.condition],
                     f'Binario de {plan.condition} mudou durante flash; parar para auditoria')
                journal(journal_path, event='FLASH_OK', condition=plan.condition, binary_sha256=sha256(binary))
            current_mode = plan.condition
        print(f'\nRun {plan.run}: {plan.condition}, {pos+1}/{len(plans)}', flush=True)
        journal(journal_path, event='RUN_BEGIN', run=plan.run, condition=plan.condition)
        run_args = SimpleNamespace(output=output, node_a=options.node_a, node_b=options.node_b,
                                   pico=options.pico, baud=options.baud,
                                   node_a_binary=targets[plan.condition][1])
        result = run_func(plan, run_args)
        checked = verify_run_zip(zip_path, plan, result)
        outcomes.append(checked)
        count[checked['status']] += 1
        journal(journal_path, event='RUN_VERIFIED', run=plan.run, condition=plan.condition,
                checked=checked)
        print(f'  OK: {checked["status"]}; dados preservados; Run seguinte autorizado LOGICAMENTE.', flush=True)
        if pos < len(plans)-1:
            print(f'  Pausa operacional {options.between:.0f}s (NAO comprova seguranca eletrica).', flush=True)
            sleep(options.between)
    journal(journal_path, event='CAMPAIGN_COMPLETED', totals=dict(count))
    return outcomes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[2]
    parser.add_argument('--plan', type=Path, default=Path(__file__).with_name('plano_campanha_phase20_40_runs.csv'))
    parser.add_argument('--output', type=Path, default=root / 'data' / 'busoff_estudo_2026')
    parser.add_argument('--node-a', default='/dev/ttyUSB0')
    parser.add_argument('--node-b', default='/dev/ttyACM0')
    parser.add_argument('--pico', default='/dev/ttyACM1')
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--idf-bin', default=shutil.which('idf.py') or str(Path.home()/'esp/esp-idf/tools/idf.py'))
    parser.add_argument('--between', type=float, default=60.0,
                        help='Pausa entre ensaios. Minimo permitido 30s; nao garante resfriamento.')
    parser.add_argument('--skip-first-flash', action='store_true', default=True,
                        help='Assume ADAPTATIVO ja gravado e valida o modo no boot.')
    parser.add_argument('--flash-first', dest='skip_first_flash', action='store_false')
    parser.add_argument('--resume', action='store_true', help='Pula somente ZIPs existentes e rigorosamente verificados.')
    parser.add_argument('--dry-run', action='store_true', help='Exibe o plano, sem acessar hardware.')
    parser.add_argument('--execute', action='store_true', help='Executa fisicamente. EXIGE supervisao presencial.')
    a = parser.parse_args(argv)
    j = None
    try:
        runner = load_runner(Path(__file__).with_name(RUNNER_FILENAME))
        plans, blocks = load_and_validate_plan(runner, a.plan)
        print('CAMPANHA PHASE20: 40 NOVOS ensaios (20 ADAPTATIVO + 20 REFERENCIA);',
              'pilotos 300/303 analisados SEPARADAMENTE (fora da amostra).', flush=True)
        print('Blocos:', ', '.join(f'{mode}:{size}' for _, mode, size in blocks))
        print('Importante: durante BUS_OFF o script encerra o run, mas so segue apos STOP, IDLE,',
              'recuperacao em ACTIVE, transmissões retomadas e log consistente.')
        print('O perfil PHASE20 nao usa a seed para alterar a temporizacao; os ensaios',
              'sao repeticoes, NAO pares de fase sincronizada.')
        if a.dry_run or not a.execute:
            print('DRY-RUN APROVADO: nenhum dispositivo acessado e nenhum dado experimental escrito.')
            return 0
        must(a.between >= PAUSE_MIN_S, f'Pausa deve ser >= {PAUSE_MIN_S}s.')
        must(Path(a.idf_bin).is_file() or shutil.which(a.idf_bin),
             f'idf.py nao encontrado em {a.idf_bin}; configure ESP-IDF.')
        must(runner.serial is not None, 'pyserial nao instalado no ambiente ativo')
        stage = root.parent / PROJECT_DIRECTORY
        targets = verify_binary_workspace(stage)
        a.approved_binary_sha256 = {k: sha256(v[1]) for k, v in targets.items()}
        # Evita escrita do executor em diretorios inesperados ao receber relativo.
        output = a.output.expanduser().resolve()
        verify_pilots(output)
        for p in plans:
            dest = output / 'zips' / f'run_{p.run}_injection.zip'
            raw = output / 'raw' / f'run_{p.run:03d}_injection'
            if not a.resume:
                must(not dest.exists() and not raw.exists(),
                     f'Run {p.run} ja existe: {dest} ou {raw}; sem sobrescrita.')
        j = output / 'campanha_integral_phase20_journal.jsonl'
        journal(j, event='CAMPAIGN_START', plan_sha256=sha256(a.plan), between_s=a.between,
                expected_total=40, initial_mode='ADAPTATIVO', supervised=True)
        print('\nAVISO: este software NAO mede corrente, temperatura ou integridade do transistor.', flush=True)
        print('Não execute sem avaliacao eletrica independente e supervisao continua;',
              'mantenha acesso ao desligamento fisico.', flush=True)
        campaign(plans, runner, output, targets, a, j)
        print('\nCAMPANHA CONCLUIDA: 40 ZIPs NOVOS, fora os pilotos 300 e 303. Agora analisar as politicas.', flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        if j is not None:
            try:
                journal(j, event='CAMPAIGN_ABORTED', error_type=type(exc).__name__, reason=str(exc))
            except Exception:
                pass
        print(f'\nCAMPANHA INTERROMPIDA: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
