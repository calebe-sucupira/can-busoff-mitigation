#!/usr/bin/env python3
"""Auditoria independente, somente leitura, dos 100 ensaios publicados."""
import csv
import hashlib
import io
import json
import re
import statistics
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MAIN = list(range(153, 189)) + list(range(197, 221))
BUSOFF = list(range(304, 344))
MEMBERS = {
    "metadata.json", "qc.json", "control_events.jsonl",
    "node_a.csv", "node_b.csv", "pico.csv",
    "node_a.log", "node_b.log", "pico.log",
}


def demand(test, message):
    if not test:
        raise AssertionError(message)


def load_plan(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return {int(row["run_previsto"]): row for row in csv.DictReader(f)}


def stamped(log, event, substring=""):
    out = []
    for line in log.splitlines():
        stamp, sep, payload = line.partition("\t")
        if not sep or not stamp.isdigit() or not payload.startswith("DATA,"):
            continue
        fields = payload.split(",", 8)
        if len(fields) == 9 and fields[2] == event and substring in fields[8]:
            out.append(int(stamp))
    return out


def read_archive(path, members):
    demand(path.is_file(), f"ZIP ausente: {path}")
    with zipfile.ZipFile(path) as z:
        demand(z.testzip() is None, f"CRC invalido: {path}")
        names = set(z.namelist())
        demand(members <= names, f"Membros ausentes em {path}: {members - names}")
        return {name: z.read(name) for name in members}


def verify_60():
    count = Counter()
    groups = Counter()
    hashes = {}
    for run in MAIN:
        path = DATA / "zips" / f"run_{run}_injection.zip"
        raw = read_archive(path, {"metadata.json", "qc.json", "node_a.log"})
        meta = json.loads(raw["metadata.json"])
        qc = json.loads(raw["qc.json"])
        demand(meta["run"] == qc["run"] == run, f"ID divergente: {run}")
        condition = meta["condition"]
        demand(qc["condition"] == condition, f"Politica divergente: {run}")
        demand(qc.get("valid") is True, f"QC da caracterizacao nao aprovado: {run}")
        demand(qc.get("bus_off_detected") is not True, f"Bus-Off inesperado na caracterizacao: {run}")
        expected = 1 if condition == "ADAPTATIVO" else 0
        demand(meta["expected_throttling"] == expected, f"Modo inesperado: {run}")
        boot = set(re.findall(r"NODE_A:[^\n]*?throttling=([01])", raw["node_a.log"].decode("utf-8", "replace")))
        demand(boot == {str(expected)}, f"Boot nao confirma o modo: {run} ({boot})")
        phase = "ORIGINAL" if run <= 188 else "COMPLEMENTAR"
        digest = meta.get("node_a_binary_sha256")
        demand(bool(re.fullmatch(r"[0-9a-f]{64}", digest or "")), f"Hash ausente: {run}")
        key = (phase, condition)
        if key in hashes:
            demand(hashes[key] == digest, f"Hash variou em {key}: run {run}")
        hashes[key] = digest
        count[condition] += 1
        groups[key] += 1
    demand(count == Counter({"REFERENCIA": 30, "ADAPTATIVO": 30}), f"Distribuicao dos 60: {count}")
    demand(groups == Counter({("ORIGINAL", "REFERENCIA"): 18,
                               ("ORIGINAL", "ADAPTATIVO"): 18,
                               ("COMPLEMENTAR", "REFERENCIA"): 12,
                               ("COMPLEMENTAR", "ADAPTATIVO"): 12}), f"Fases: {groups}")
    return count, hashes


def verify_40():
    plan = load_plan(ROOT / "experiments/busoff/plano_campanha_phase20_40_runs.csv")
    demand(set(plan) == set(BUSOFF), "Plano nao contem exatamente 304-343")
    times, last_second = {}, {}
    conditions = Counter()
    hashes = {}
    for run in BUSOFF:
        root = DATA / "busoff_estudo_2026" / "raw" / f"run_{run}_injection"
        path = DATA / "busoff_estudo_2026" / "zips" / f"run_{run}_injection.zip"
        content = read_archive(path, MEMBERS)
        for name, raw in content.items():
            source = root / name
            demand(source.is_file(), f"Arquivo bruto ausente: {source}")
            demand(hashlib.sha256(source.read_bytes()).digest() ==
                   hashlib.sha256(raw).digest(), f"Conteudo ZIP diverge do bruto: {run}/{name}")
        meta = json.loads(content["metadata.json"])
        qc = json.loads(content["qc.json"])
        p = plan[run]
        mode = p["condicao"]
        flag = int(p["throttling_esperado"])
        demand(meta["run"] == qc["run"] == run, f"ID divergente: {run}")
        demand(qc["condition"] == meta["condition"] == mode, f"Modo divergente: {run}")
        demand(qc["expected_throttling"] == meta["expected_throttling"] == flag,
               f"Flag divergente: {run}")
        demand(qc.get("observation_status") == "BUS_OFF_OBSERVED_ABORTED",
               f"Desfecho inesperado: {run}")
        demand(qc.get("bus_off_detected") is True, f"QC nao confirma Bus-Off: {run}")
        for key in ("stop_command_sent", "stop_acknowledged", "pico_idle_confirmed"):
            demand(qc.get(key) is True, f"Parada sem confirmacao {key}: {run}")
        boot = set(re.findall(r"NODE_A:[^\n]*?throttling=([01])",
                              content["node_a.log"].decode("utf-8", "replace")))
        demand(boot == {str(flag)}, f"Boot nao confirma modo: {run} ({boot})")
        controls = [json.loads(x) for x in content["control_events.jsonl"].splitlines() if x.strip()]
        verified = [x for x in controls if x.get("event") == "NODE_A_MODE_VERIFIED"]
        demand(verified and all(x.get("throttling") == flag for x in verified),
               f"Falta confirmacao de modo da automacao: {run}")
        stops = [x for x in controls if x.get("event") == "STOP_RESULT"]
        demand(stops and all(stops[-1].get(key) is True for key in ("sent", "acknowledged", "idle")),
               f"STOP_RESULT invalido: {run}")
        log_a = content["node_a.log"].decode("utf-8", "replace")
        log_p = content["pico.log"].decode("utf-8", "replace")
        first = stamped(log_a, "STATE_CHANGE", "->BUS_OFF")
        first += stamped(log_a, "SAMPLE", ",BUS_OFF,")
        noise = stamped(log_p, "NOISE_START")
        abort = stamped(log_p, "TEST_ABORTED")
        demand(first and len(noise) == 1 and abort, f"Eventos criticos ausentes: {run}")
        start, busoff = noise[0], min(first)
        demand(start < busoff < abort[-1], f"Sequencia de eventos invalida: {run}")
        t_s = (busoff - start) / 1e9
        demand(0 < t_s < 40, f"Tempo de Bus-Off fora da injeção: {run}: {t_s}")
        txs = stamped(log_a, "TX_SUCCESS")
        before = sum(busoff - 1_000_000_000 <= t < busoff for t in txs)
        times.setdefault(mode, []).append(t_s)
        last_second.setdefault(mode, []).append(before)
        conditions[mode] += 1
        digest = meta.get("node_a_binary_sha256")
        demand(bool(re.fullmatch(r"[0-9a-f]{64}", digest or "")), f"Hash ausente: {run}")
        if mode in hashes:
            demand(hashes[mode] == digest, f"Binario variou em {mode}: {run}")
        hashes[mode] = digest
    demand(conditions == Counter({"REFERENCIA": 20, "ADAPTATIVO": 20}),
           f"Distribuicao dos 40: {conditions}")
    return times, last_second, hashes


def main():
    total, hashes60 = verify_60()
    t, tx, hashes40 = verify_40()
    print("INTEGRIDADE 60: APROVADA", dict(total))
    print("INTEGRIDADE 40: APROVADA; 40/40 Bus-Off, STOP, ACK e IDLE, ZIP=bruto")
    print("HASHES 60:", dict(sorted(hashes60.items())))
    print("HASHES 40:", dict(sorted(hashes40.items())))
    for cond in ("REFERENCIA", "ADAPTATIVO"):
        print(f"{cond}: media de tempo ate Bus-Off={statistics.mean(t[cond]):.4f} s; "
              f"TX_SUCCESS no segundo anterior={statistics.mean(tx[cond]):.4f}")
    print("OBS: para Bus-Off, qc.valid=false indica aborto por evento; nao reprova o ensaio.")


if __name__ == "__main__":
    main()
