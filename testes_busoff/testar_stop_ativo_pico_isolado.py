#!/usr/bin/env python3
"""Verifica a parada logica do Pico v1.5 durante pulsos, com CAN_H/CAN_L isolados.

Nao verifica tensoes, correntes nem seguranca eletrica. Nao acessa os ESP32.
"""
import argparse
import sys
import time

try:
    import serial
except ImportError:
    raise SystemExit("Falta pyserial no ambiente Python (python3 -m pip install pyserial).")

TEST_RUN = "990001"
PROFILE = "BAIXO"
LIMITS = ("40000", "60000")
SEED = "6d2b79f5"
INJECTION_SECONDS = 5


def parse_event(line):
    fields = line.strip().split(",", 8)
    if len(fields) != 9 or fields[0] != "DATA":
        return None
    detail = {}
    for piece in fields[8].split(";"):
        if "=" in piece:
            key, value = piece.split("=", 1)
            detail[key] = value
    return {"event": fields[2], "detail": detail, "raw": line.strip()}


def wait_event(port, wanted, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = port.readline()
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace").strip()
        record = parse_event(line)
        if record is None:
            continue
        if record["event"] in ("CONFIG_ERROR",):
            raise RuntimeError(f"Pico recusou configuracao: {line}")
        if record["event"] in wanted:
            print(line, flush=True)
            return record
    raise TimeoutError("Sem evento esperado: " + "/".join(sorted(wanted)))


def send(port, command):
    port.write(command)
    port.flush()


def test(port):
    started = False
    confirmed = False

    try:
        time.sleep(2)
        port.reset_input_buffer()

        send(port, b"?")
        status = wait_event(port, {"STATUS"}, 5)
        if status["detail"].get("firmware") != "pico-param-v1.5":
            raise RuntimeError("Firmware do Pico diferente de pico-param-v1.5")
        if status["detail"].get("state") != "IDLE":
            raise RuntimeError("Pico nao esta em IDLE. Nao iniciar teste.")

        config = (
            f"CFG,{TEST_RUN},{PROFILE},{LIMITS[0]},{LIMITS[1]},"
            f"{SEED},{INJECTION_SECONDS}\n"
        )
        send(port, config.encode("ascii"))
        cfg = wait_event(port, {"CONFIG_OK"}, 5)
        d = cfg["detail"]
        for key, expected in (
            ("run_id", TEST_RUN),
            ("profile", PROFILE),
            ("interval_min_us", LIMITS[0]),
            ("interval_max_us", LIMITS[1]),
        ):
            if d.get(key) != expected:
                raise RuntimeError(f"CFG divergente em {key}: {d.get(key)}")

        print("Iniciando teste: 5 s de baseline e ~0,5 s de pulsos BAIXO.")
        started = True
        send(port, b"s")
        first = wait_event(port, {"TEST_START"}, 5)
        if first["detail"].get("run_id") != TEST_RUN:
            raise RuntimeError("TEST_START com run_id inesperado")
        noise = wait_event(port, {"NOISE_START"}, 8)
        if noise["detail"].get("run_id") != TEST_RUN:
            raise RuntimeError("NOISE_START com run_id inesperado")

        time.sleep(0.5)
        print("Enviando x enquanto a injeção esta ativa.")
        send(port, b"x")
        stopped = wait_event(port, {"TEST_ABORTED"}, 5)
        if stopped["detail"].get("run_id") != TEST_RUN:
            raise RuntimeError("TEST_ABORTED com run_id inesperado")

        send(port, b"?")
        final = wait_event(port, {"STATUS"}, 5)
        if final["detail"].get("state") != "IDLE":
            raise RuntimeError("STATUS final nao confirmou IDLE")

        n = int(stopped["detail"].get("pulses", "-1"))
        if n <= 0:
            raise RuntimeError("Pico nao confirmou pulsos antes de parar")
        confirmed = True
        print(f"APROVADO: {n} pulsos logicos registrados, TEST_ABORTED e STATUS IDLE.")
        print("Limite: isto NAO comprova desligamento eletrico nem resposta a Bus-Off real.")
        return 0

    except (KeyboardInterrupt, Exception) as exc:
        print(f"TESTE NAO APROVADO: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    finally:
        # O STOP e repetido se o teste nao terminou com confirmacao.
        if started and not confirmed:
            try:
                send(port, b"x")
                stopped = wait_event(port, {"TEST_ABORTED"}, 3)
                send(port, b"?")
                status = wait_event(port, {"STATUS"}, 3)
                if status["detail"].get("state") != "IDLE":
                    print("ALERTA: STOP nao foi confirmado com IDLE.", file=sys.stderr)
            except Exception as exc:
                print("ALERTA: parada nao confirmada! Desenergize o Pico "
                      "antes de reconectar CAN_H/CAN_L. " + str(exc),
                      file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/ttyACM1")
    parser.add_argument("--confirm-can-disconnected", action="store_true")
    args = parser.parse_args()

    if not args.confirm_can_disconnected:
        parser.error("Remova CAN_H e CAN_L do injetor, isole as pontas e "
                     "passe --confirm-can-disconnected.")
    print("Teste SOMENTE com CAN_H/CAN_L do injetor desconectados e isolados.")
    print("Nao use se algum fio ainda estiver ligado ao barramento.")
    try:
        with serial.Serial(args.port, 115200, timeout=0.2, write_timeout=1,
                           dsrdtr=False, rtscts=False) as pico:
            pico.dtr = True
            pico.rts = False
            return test(pico)
    except (serial.SerialException, OSError) as exc:
        print("Falha ao abrir a porta serial: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
