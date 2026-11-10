#!/usr/bin/env python3
"""Compila a variante de telemetria em workspaces isolados, sem gravar ESP32.

Execute na arvore original com ESP-IDF inicializado. Teste --prepare-only para
verificar a preparacao sem compilar (nao requer ESP-IDF).
"""

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ORIGINAL_SHA256 = "2f6d44f9d70a1c2a100f26879e70fb294ea0dc67f2d06e64eab51e7ef0b8725c"
TRACE_SHA256 = "b2cab8bd45be0c72a8d3098c191a96a0c054fe641f3488c1c280ae0b9296155e"


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fail(message):
    raise RuntimeError(message)


def get_build_flags(project):
    commands_path = project / "build" / "compile_commands.json"
    if not commands_path.is_file():
        fail(f"Sem compile_commands.json: {commands_path}")
    commands = json.loads(commands_path.read_text(encoding="utf-8"))
    matches = [entry for entry in commands if Path(entry.get("file", "")).as_posix().endswith("/main/main.c")]
    if len(matches) != 1:
        fail(f"Esperava uma compilacao de main/main.c, encontrei {len(matches)}")
    entry = matches[0]
    args = entry.get("arguments") or shlex.split(entry["command"])
    flags = [arg for arg in args if arg.startswith("-DENABLE_THROTTLING=")]
    return flags


def collect_binary(project):
    root = project / "build"
    outputs = [p for p in root.glob("*.bin") if p.is_file()]
    if len(outputs) != 1:
        fail(f"Esperava um app .bin na raiz de {root}; encontrados: {[p.name for p in outputs]}")
    return outputs[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true", help="Apenas prepara duas copias, sem executar idf.py")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[2]
    source_project = repo / "firmware" / "node-a"
    original = source_project / "main" / "main.c"
    telemetry_dir = Path(__file__).resolve().parent
    patch = telemetry_dir / "node_a_busoff_trace.patch"
    proposed = telemetry_dir / "main_busoff_trace.c"
    stage = repo.parent / "_compilacao_telemetria_busoff_2026-10-20"

    print(f"Repositorio: {repo}", flush=True)
    for path in (original, patch, proposed, source_project / "CMakeLists.txt", source_project / "main" / "CMakeLists.txt"):
        if not path.is_file():
            fail(f"Arquivo necessario nao encontrado: {path}")
    if sha256(original) != ORIGINAL_SHA256:
        fail("main.c atual difere da versao auditada. NAO sobrescreva. "
             f"SHA atual: {sha256(original)}. Envie esse valor para revisao.")
    if sha256(proposed) != TRACE_SHA256:
        fail("Arquivo de telemetria nao confere com a variante auditada.")
    if stage.exists():
        fail(f"Diretorio de compilacao ja existe: {stage}. Nao sobrescrevi nada.")

    idf = shutil.which("idf.py")
    if not args.prepare_only and not idf:
        fail("idf.py nao esta no PATH. Inicialize o ESP-IDF (export.sh) e execute novamente.")

    for mode, macro in (("referencia", "0"), ("adaptativo", "1")):
        staging_root = stage / mode
        project = staging_root / "firmware" / "node-a"
        project.parent.mkdir(parents=True)
        shutil.copytree(
            source_project,
            project,
            ignore=shutil.ignore_patterns("build", "build_*", "build-*", ".git", "__pycache__", ".venv"),
        )
        checked = subprocess.run(
            ["patch", "-p1", "-i", str(patch)], cwd=staging_root,
            capture_output=True, text=True,
        )
        if checked.returncode != 0:
            fail(f"Nao foi possivel aplicar patch no clone {mode}:\n{checked.stdout}{checked.stderr}")
        if sha256(project / "main" / "main.c") != TRACE_SHA256:
            fail(f"Fonte modificado nao confere com o proposto: {mode}")
        print(f"Preparado {mode}: fonte verificado, ENABLE_THROTTLING={macro} no build", flush=True)

    ref_project = stage / "referencia" / "firmware" / "node-a"
    adapt_project = stage / "adaptativo" / "firmware" / "node-a"
    for name in ("main/main.c", "main/throttle_policy.h", "sdkconfig"):
        left, right = ref_project / name, adapt_project / name
        if left.exists() != right.exists() or (left.exists() and sha256(left) != sha256(right)):
            fail(f"Divergencia entre copias antes da compilacao: {name}")
    if args.prepare_only:
        print(f"PREPARACAO APROVADA (SEM COMPILAR): {stage}", flush=True)
        return 0

    summary = {"esp_idf_command": idf, "original_main_sha256": ORIGINAL_SHA256,
               "trace_main_sha256": TRACE_SHA256, "builds": {}}
    for mode, macro in (("referencia", "0"), ("adaptativo", "1")):
        project = stage / mode / "firmware" / "node-a"
        command = [idf, "-B", "build", f"-DCMAKE_C_FLAGS=-DENABLE_THROTTLING={macro}", "build"]
        log_file = stage / mode / "build_esp_idf.log"
        print(f"\nCompilando {mode} (pode demorar): {' '.join(shlex.quote(x) for x in command)}", flush=True)
        with log_file.open("w", encoding="utf-8") as log:
            completed = subprocess.run(command, cwd=project, stdout=log, stderr=subprocess.STDOUT)
        if completed.returncode:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            print("\n".join(lines[-30:]), file=sys.stderr)
            fail(f"Compilacao {mode} falhou; log completo: {log_file}")
        flags = get_build_flags(project)
        if flags != [f"-DENABLE_THROTTLING={macro}"]:
            fail(f"Macro nao comprovada para {mode}; flags no main.c: {flags}. "
                 f"Verifique {project / 'build' / 'compile_commands.json'}")
        app_bin = collect_binary(project)
        summary["builds"][mode] = {
            "macro_verified": flags[0],
            "source_main_sha256": sha256(project / "main" / "main.c"),
            "throttle_policy_sha256": sha256(project / "main" / "throttle_policy.h"),
            "sdkconfig_sha256": sha256(project / "sdkconfig") if (project / "sdkconfig").exists() else None,
            "app_bin": str(app_bin), "app_bin_sha256": sha256(app_bin),
            "log_file": str(log_file),
        }
        print(f"COMPILACAO OK: {mode}; macro={flags[0]}; bin={app_bin.name}", flush=True)

    builds = summary["builds"]
    for field in ("source_main_sha256", "throttle_policy_sha256", "sdkconfig_sha256"):
        if builds["referencia"][field] != builds["adaptativo"][field]:
            fail(f"Diferenca inesperada nos builds: {field}")
    if builds["referencia"]["app_bin_sha256"] == builds["adaptativo"]["app_bin_sha256"]:
        fail("Os dois binarios sao identicos. Nao usar antes de auditar macros!")

    manifest = stage / "manifesto_compilacao.json"
    manifest.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nCONCLUIDO: dois binarios distintos, fonte e sdkconfig iguais, macros verificadas.\nManifesto: {manifest}")
    print("Nenhum firmware foi gravado. CAN_H e CAN_L devem permanecer desconectados do injetor.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, json.JSONDecodeError) as error:
        print(f"ERRO: {error}", file=sys.stderr)
        sys.exit(1)
