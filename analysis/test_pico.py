import time
import serial

PORT = "/dev/ttyACM1"
BAUD = 115200
CYCLES = 5


def wait_event(ser, event, timeout=2.0):
    deadline = time.time() + timeout

    while time.time() < deadline:
        raw = ser.readline()

        if not raw:
            continue

        line = raw.decode(
            "utf-8",
            errors="replace"
        ).strip()

        print(f"PICO -> {line}")

        if event in line:
            return True

    return False


ser = serial.Serial()

ser.port = PORT
ser.baudrate = BAUD
ser.timeout = 0.2
ser.write_timeout = 1

ser.dtr = True
ser.rts = False

ser.open()
ser.reset_input_buffer()

print(f"Pico conectada em {PORT}")
print()

success = 0

for cycle in range(1, CYCLES + 1):
    print(f"=== CICLO {cycle}/{CYCLES} ===")

    ser.write(b"s")
    ser.flush()

    if not wait_event(ser, "NOISE_START"):
        print("FALHA: NOISE_START não recebido")
        break

    time.sleep(1)

    ser.write(b"x")
    ser.flush()

    if not wait_event(ser, "NOISE_END"):
        print("FALHA: NOISE_END não recebido")
        break

    success += 1
    print("OK")
    print()

    time.sleep(0.5)

ser.close()

print()
print(f"Resultado: {success}/{CYCLES} ciclos completos")
