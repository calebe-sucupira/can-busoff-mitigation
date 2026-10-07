import argparse
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import serial


def next_run_directory(base_dir, run_type):
    existing_runs = []

    for path in base_dir.glob("run_*"):
        if not path.is_dir():
            continue

        try:
            number = int(path.name.split("_")[1])
            existing_runs.append(number)
        except (IndexError, ValueError):
            pass

    run_number = max(existing_runs, default=0) + 1
    run_dir = base_dir / f"run_{run_number:03d}_{run_type}"
    run_dir.mkdir(parents=True, exist_ok=False)

    return run_number, run_dir


def open_serial(port, baud, is_pico=False):
    ser = serial.Serial()

    ser.port = port
    ser.baudrate = baud
    ser.timeout = 0.1
    ser.write_timeout = 1

    ser.dtr = bool(is_pico)
    ser.rts = False

    ser.open()

    ser.dtr = bool(is_pico)
    ser.rts = False

    return ser


def capture_device(name, port, baud, run_dir, stop_event, serial_devices):
    raw_path = run_dir / f"{name}.log"
    csv_path = run_dir / f"{name}.csv"

    try:
        ser = open_serial(port, baud, is_pico=(name == "pico"))
        serial_devices[name] = ser

        print(f"[{name}] conectado em {port}")

        with (
            raw_path.open("w", encoding="utf-8", buffering=1) as raw_file,
            csv_path.open("w", encoding="utf-8", buffering=1) as csv_file,
        ):
            csv_file.write(
                "timestamp_us,node,event,sequence,tec,rec,state,mode,detail\n"
            )

            while not stop_event.is_set():
                try:
                    raw = ser.readline()

                    if not raw:
                        continue

                    host_timestamp_ns = time.time_ns()

                    line = raw.decode(
                        "utf-8",
                        errors="replace"
                    ).rstrip("\r\n")

                    raw_file.write(
                        f"{host_timestamp_ns}\t{line}\n"
                    )

                    show_in_terminal = name == "pico"

                    if not line.startswith("DATA,"):
                        show_in_terminal = True

                    if line.startswith("DATA,"):
                        fields = line.split(",", 8)

                        if len(fields) == 9 and name != "pico":
                            _, _, event, _, tec, rec, state, _, detail = fields

                            if event in {"ERROR", "STATE_CHANGE", "TX_FAILED"}:
                                show_in_terminal = True

                            elif event == "SAMPLE" and (
                                tec != "0"
                                or rec != "0"
                                or state != "ACTIVE"
                                or (
                                    detail.startswith("bus_errors=")
                                    and detail != "bus_errors=0"
                                )
                            ):
                                show_in_terminal = True

                    if show_in_terminal:
                        print(f"[{name}] {line}")

                    if line.startswith("DATA,"):
                        fields = line.split(",", 8)

                        if len(fields) == 9:
                            (
                                _,
                                timestamp_us,
                                event,
                                sequence,
                                tec,
                                rec,
                                state,
                                mode,
                                detail,
                            ) = fields

                            csv_file.write(
                                f"{timestamp_us},"
                                f"{name},"
                                f"{event},"
                                f"{sequence},"
                                f"{tec},"
                                f"{rec},"
                                f"{state},"
                                f"{mode},"
                                f"{detail}\n"
                            )

                except serial.SerialException as exc:
                    if not stop_event.is_set():
                        print(f"[{name}] erro serial: {exc}")

                    break

    except serial.SerialException as exc:
        print(f"[{name}] não foi possível abrir {port}: {exc}")
        stop_event.set()

    finally:
        ser = serial_devices.pop(name, None)

        if ser is not None and ser.is_open:
            try:
                ser.close()
            except serial.SerialException:
                pass

        print(f"[{name}] encerrado")


def pico_command_loop(pico_serial, stop_event):
    print()
    print("Comandos do Pico:")
    print("  s = START")
    print("  x = STOP")
    print("  q = encerrar captura")
    print()

    while not stop_event.is_set():
        try:
            command = input("> ").strip().lower()

        except (EOFError, KeyboardInterrupt):
            stop_event.set()
            break

        if command == "s":
            try:
                pico_serial.write(b"s")
                pico_serial.flush()
                print("[pico] START enviado")

            except (
                serial.SerialException,
                serial.SerialTimeoutException
            ) as exc:
                print(f"[pico] falha ao enviar START: {exc}")
                stop_event.set()
                break

        elif command == "x":
            try:
                pico_serial.write(b"x")
                pico_serial.flush()
                print("[pico] STOP enviado")

            except (
                serial.SerialException,
                serial.SerialTimeoutException
            ) as exc:
                print(f"[pico] falha ao enviar STOP: {exc}")
                stop_event.set()
                break

        elif command == "q":
            stop_event.set()
            break

        elif command:
            print("Comando inválido. Use s, x ou q.")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--type",
        choices=["reference", "injection"],
        required=True
    )

    parser.add_argument(
        "--node-a",
        required=True
    )

    parser.add_argument(
        "--node-b",
        required=True
    )

    parser.add_argument(
        "--pico",
        default=None
    )

    parser.add_argument(
        "--baud",
        type=int,
        default=115200
    )

    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    raw_data_dir = project_root / "data" / "raw"

    raw_data_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    run_number, run_dir = next_run_directory(
        raw_data_dir,
        args.type
    )

    devices = {
        "node_a": args.node_a,
        "node_b": args.node_b,
    }

    if args.pico:
        devices["pico"] = args.pico

    metadata = {
        "run": run_number,
        "type": args.type,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "baud": args.baud,
        "devices": devices,
    }

    metadata_path = run_dir / "metadata.json"

    with metadata_path.open(
        "w",
        encoding="utf-8"
    ) as metadata_file:

        json.dump(
            metadata,
            metadata_file,
            indent=2
        )

    stop_event = threading.Event()
    serial_devices = {}
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
            ),
            daemon=True,
        )

        thread.start()
        threads.append(thread)

    try:
        if args.pico:
            timeout = time.time() + 5

            while (
                "pico" not in serial_devices
                and not stop_event.is_set()
                and time.time() < timeout
            ):
                time.sleep(0.05)

            if "pico" in serial_devices:
                pico_command_loop(
                    serial_devices["pico"],
                    stop_event
                )

            else:
                print("[pico] porta não disponível")
                stop_event.set()

        else:
            while not stop_event.is_set():
                time.sleep(0.2)

    except KeyboardInterrupt:
        print()
        print("Encerrando captura...")
        stop_event.set()

    finally:
        stop_event.set()

        for thread in threads:
            thread.join(timeout=2)

        for ser in list(serial_devices.values()):
            if ser.is_open:
                try:
                    ser.close()
                except serial.SerialException:
                    pass

    print(f"Dados salvos em: {run_dir}")


if __name__ == "__main__":
    main()