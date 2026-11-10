#!/usr/bin/env python3
"""Retoma compilacao da telemetria em copias isoladas apos falha de verificacao da macro.

Usa target_compile_definitions para ligar ENABLE_THROTTLING diretamente ao
componente main. Nao altera projeto original, nao grava ESP32 e nao acessa USB.
"""

import hashlib
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ORIGINAL_SHA256 = "2f6d44f9d70a1c2a100f26879e70fb294ea0dc67f2d06e64eab51e7ef0b8725c"
TRACE_SHA256 = "b2cab8bd45be0c72a8d3098c191a96a0c054fe641f3488c1c280ae0b9296155e"
MODES = (("referencia", "0"), ("adaptativo", "1"))


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def get_flags(project):
    path = project / "build" / "compile_commands.json"
    check(path.is_file(), f"Arquivo de compilacao nao encontrado: {path}")
    commands = json.loads(path.read_text(encoding="utf-8"))
    matches = [e for e in commands if Path(e.get("file", "")).as_posix().endswith("/main/main.c")]
    check(len(matches) == 1, f"Esperava uma entrada para main/main.c, encontrei {len(matches)}")
    entry = matches[0]
    args = entry.get("arguments") or shlex.split(entry["command"])
    return [a for a in args if a.startswith("-DENABLE_THROTTLING=")]


def one_bin(project):
    candidates = [p for p in (project / "build").glob("*.bin") if p.is_file()]
    check(len(candidates) == 1, f"Esperava um .bin do aplicativo; encontrados: {candidates}")
    return candidates[0]


def run_idf(idf, project, mode, operation, logfile):
    command = [idf, "-B", "build", operation]
    print(f"[{mode}] Executando: {' '.join(shlex.quote(x) for x in command)}", flush=True)
    with logfile.open("a", encoding="utf-8") as f:
        f.write("\n=== " + " ".join(command) + " ===\n")
        f.flush()
        result = subprocess.run(command, cwd=project, stdout=f, stderr=subprocess.STDOUT)
    if result.returncode:
        tail = logfile.read_text(encoding="utf-8", errors="replace").splitlines()[-35:]
        print("\n".join(tail), file=sys.stderr)
        raise RuntimeError(f"ESP-IDF falhou em {mode} ({operation}). Consulte {logfile}")


def main():
    repo = Path(__file__).resolve().parents[2]
    original = repo / "firmware" / "node-a" / "main" / "main.c"
    stage = repo.parent / "_compilacao_telemetria_busoff_2026-10-20"
    idf = shutil.which("idf.py")
    check(idf is not None, "idf.py nao encontrado. Inicialize o ESP-IDF (export.sh) no terminal.")
    check(stage.is_dir(), f"Copias isoladas nao encontradas: {stage}. Nao vou recriar nem apagar pastas.")
    check(original.is_file() and sha256(original) == ORIGINAL_SHA256,
          "O main.c original difere do auditado. Nao vou modificar nada.")

    projects = {}
    for mode, macro in MODES:
        project = stage / mode / "firmware" / "node-a"
        main_c = project / "main" / "main.c"
        cmake = project / "main" / "CMakeLists.txt"
        check(main_c.is_file() and sha256(main_c) == TRACE_SHA256,
              f"O main.c de {mode} nao corresponde a variante aprovada.")
        check(cmake.is_file(), f"CMakeLists do componente main nao encontrado: {cmake}")
        projects[mode] = project

    # Antes de tocar nas copias, conferir que elas nao foram misturadas.
    for path in ("main/main.c", "main/throttle_policy.h"):
        check(sha256(projects["referencia"] / path) == sha256(projects["adaptativo"] / path),
              f"Codigo distinto entre modos: {path}")

    for mode, macro in MODES:
        cmake = projects[mode] / "main" / "CMakeLists.txt"
        content = cmake.read_text(encoding="utf-8")
        target = f"target_compile_definitions(${{COMPONENT_LIB}} PRIVATE ENABLE_THROTTLING={macro})"
        other = f"target_compile_definitions(${{COMPONENT_LIB}} PRIVATE ENABLE_THROTTLING={'1' if macro == '0' else '0'})"
        check(other not in content, f"Macro oposta ja definida no CMake de {mode}")
        if target not in content:
            check("ENABLE_THROTTLING" not in content,
                  f"ENABLE_THROTTLING ja aparece no CMake de {mode}; revise manualmente.")
            check("idf_component_register" in content,
                  f"Componente nao tem idf_component_register: {cmake}")
            cmake.write_text(content.rstrip() + "\n\n" + target + "\n", encoding="utf-8")
            print(f"[{mode}] Definicao anexada ao CMake da COPIA: ENABLE_THROTTLING={macro}", flush=True)
        else:
            print(f"[{mode}] Definicao correta ja presente; retomando compilacao.", flush=True)

    summary = {"original_main_sha256": ORIGINAL_SHA256,
               "trace_main_sha256": TRACE_SHA256,
               "method": "target_compile_definitions no componente main de copias isoladas",
               "builds": {}}

    for mode, macro in MODES:
        project = projects[mode]
        log = stage / mode / "build_esp_idf_cmake_fix.log"
        run_idf(idf, project, mode, "reconfigure", log)
        run_idf(idf, project, mode, "build", log)
        flags = get_flags(project)
        expected = f"-DENABLE_THROTTLING={macro}"
        check(flags == [expected],
              f"Macro nao comprovada para {mode}: {flags!r}. Consulte {project / 'build/compile_commands.json'}")
        output = one_bin(project)
        summary["builds"][mode] = {
            "macro_verified": expected,
            "source_main_sha256": sha256(project / "main" / "main.c"),
            "throttle_policy_sha256": sha256(project / "main" / "throttle_policy.h"),
            "sdkconfig_sha256": sha256(project / "sdkconfig") if (project / "sdkconfig").is_file() else None,
            "app_bin": str(output),
            "app_bin_sha256": sha256(output),
            "log_file": str(log),
        }
        print(f"COMPILACAO OK: {mode}; macro={expected}; bin={output.name}", flush=True)

    ref, adapt = (summary["builds"][mode] for mode, _ in MODES)
    for field in ("source_main_sha256", "throttle_policy_sha256", "sdkconfig_sha256"):
        check(ref[field] == adapt[field], f"Divergencia inesperada entre os modos: {field}")
    check(ref["app_bin_sha256"] != adapt["app_bin_sha256"],
          "Binarios IDENTICOS. Nao usar antes de investigar configuracao e compilacao!")
    manifest = stage / "manifesto_compilacao_corrigida.json"
    manifest.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\nCONCLUIDO: referencia e adaptativo com macros distintas verificadas.")
    print(f"Manifesto: {manifest}")
    print("Nenhum firmware foi gravado; nenhum comando foi enviado ao Pico.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, json.JSONDecodeError, KeyError) as error:
        print(f"ERRO: {error}", file=sys.stderr)
        sys.exit(1)
