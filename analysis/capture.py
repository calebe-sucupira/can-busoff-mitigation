import argparse
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import serial


def next_run_directory(base, run_type):
    base.mkdir(parents=True, exist_ok=True)

    numbers = []

    for path in base.glob("run_*"):
        if path.is_dir():
            try:
                numbers.append(int(path.name.split("_")[1]))
            except (IndexError, ValueError):
                pass

    number = max(numbers, default=0) + 1

    run_dir = base / f"run_{number:03d}_{run_type}"
    run_dir.mkdir()

    return number, run_dir


def capture_device(
    name,
    port,
    baud,
    run_dir,
    stop_event,
    serial_devices,
    serial_lock
):
    log_path = run_dir / f"{name}.log"
    csv_path = run_dir / f"{name}.csv"

    try:
        ser = serial.Serial(
            port=port,
            baudrate=baud,
            timeout=0.2
        )
    except serial.SerialException as error:
        print(f"[{name}] Erro ao abrir {port}: {error}")
        return

    with serial_lock:
        serial_devices[name] = ser

    print(f"[{name}] Lendo {port}")

    with open(log_path, "w", buffering=1) as log_file, \
         open(csv_path, "w", buffering=1) as csv_file:

        csv_file.write(
            "timestamp_us,node,event,sequence,tec,rec,state,mode,detail\n"
        )

        while not stop_event.is_set():
            try:
                raw = ser.readline()

                if not raw:
                    continue

                line = raw.decode(
                    "utf-8",
                    errors="replace"
                ).strip()

                if not line:
                    continue

                host_time_ns = time.time_ns()

                log_file.write(
                    f"{host_time_ns}\t{line}\n"
                )

                if line.startswith("DATA,"):
                    csv_file.write(
                        line[5:] + "\n"
                    )

                print(f"[{name}] {line}")

            except serial.SerialException as error:
                print(f"[{name}] Erro serial: {error}")
                break

    with serial_lock:
        serial_devices.pop(name, None)

    ser.close()
    print(f"[{name}] Captura encerrada")


def command_loop(
    stop_event,
    serial_devices,
    serial_lock
):
    print()
    print("Comandos:")
    print("  s = iniciar perturbacao")
    print("  x = encerrar perturbacao")
    print("  q = encerrar captura")
    print()

    while not stop_event.is_set():
        try:
            command = input().strip().lower()
        except EOFError:
            return

        if command == "q":
            stop_event.set()
            return

        if command not in ("s", "x"):
            print("Comando invalido. Use s, x ou q.")
            continue

        with serial_lock:
            pico = serial_devices.get("pico")

        if pico is None:
            print("[pico] Porta serial ainda nao esta disponivel.")
            continue

        try:
            pico.write(command.encode("ascii"))
            pico.flush()

            if command == "s":
                print("[pico] Comando START enviado")
            else:
                print("[pico] Comando STOP enviado")

        except serial.SerialException as error:
            print(f"[pico] Erro ao enviar comando: {error}")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--type",
        choices=["reference", "injection"],
        required=True
    )

    parser.add_argument("--node-a")
    parser.add_argument("--node-b")
    parser.add_argument("--pico")
    parser.add_argument("--baud", type=int, default=115200)

    args = parser.parse_args()

    devices = {}

    if args.node_a:
        devices["node_a"] = args.node_a

    if args.node_b:
        devices["node_b"] = args.node_b

    if args.pico:
        devices["pico"] = args.pico

    if not devices:
        print("Informe pelo menos uma porta serial.")
        return

    run_number, run_dir = next_run_directory(
        Path("data/raw"),
        args.type
    )

    metadata = {
        "run": run_number,
        "type": args.type,
        "started_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "baud": args.baud,
        "devices": devices
    }

    with open(
        run_dir / "metadata.json",
        "w"
    ) as file:
        json.dump(
            metadata,
            file,
            indent=2
        )

    print(f"Ensaio: run_{run_number:03d}_{args.type}")
    print(f"Diretorio: {run_dir}")

    stop_event = threading.Event()
    serial_devices = {}
    serial_lock = threading.Lock()
    threads = []

    for name, port in devices.items():
        thread = threading.Thread(
            target=capture_device,
            args=(
                name,
                port,
                args.baud,
                run_dir,
                stop_event,
                serial_devices,
                serial_lock
            )
        )

        thread.start()
        threads.append(thread)

    if args.pico:
        command_thread = threading.Thread(
            target=command_loop,
            args=(
                stop_event,
                serial_devices,
                serial_lock
            ),
            daemon=True
        )

        command_thread.start()
    else:
        print("Ctrl+C para encerrar")

    try:
        while any(
            thread.is_alive()
            for thread in threads
        ):
            time.sleep(0.2)

    except KeyboardInterrupt:
        print("\nEncerrando...")
        stop_event.set()

    for thread in threads:
        thread.join()

    print(f"Dados salvos em {run_dir}")


if __name__ == "__main__":
    main()