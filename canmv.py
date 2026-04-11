# ============================================================
#  ATSIQUE CanSat — Telemetry TX via LoRa (CSV + ACK)
#  CanMV K230D Zero + RYLR998 on UART2
#  Fields: ax_f, ay_f, az_f, gx, gy, gz, temperature,
#          pressure_hpa, sensor_id, lat, lon, roll, pitch,
#          altitude, gps_data, gps_ready, uwTick
# ============================================================

import time, math
from machine import UART, FPIOA

# ── Config ───────────────────────────────────────────────────
LORA_TX_PIN  = 11
LORA_RX_PIN  = 12
GROUND_ADDR  = 2
MY_ADDR      = 1
TX_INTERVAL  = 2000     # ms between packets
ACK_TIMEOUT  = 3000     # ms to wait for ACK
MAX_RETRIES  = 3

# ── Init UART2 ───────────────────────────────────────────────
fp = FPIOA()
fp.set_function(LORA_TX_PIN, FPIOA.UART2_TXD)
fp.set_function(LORA_RX_PIN, FPIOA.UART2_RXD)
lora = UART(2, baudrate=115200)
time.sleep_ms(500)
print("[LORA] UART2 ready")

# ── Mock data generator ──────────────────────────────────────
pkt_id = 0

def get_mock_data():
    """
    Generate one telemetry packet. pkt_id is incremented HERE only once.
    Call this once per transmission cycle — NOT inside the retry loop.
    """
    global pkt_id
    pkt_id += 1                          # increment exactly once per packet
    t = time.ticks_ms() / 1000.0        # seconds since boot (always advancing)

    # Larger amplitudes + faster frequencies → visible change every packet
    ax_f         = round(-0.11 + 0.15 * math.sin(t * 2.1),  4)
    ay_f         = round( 0.03 + 0.12 * math.cos(t * 1.7),  4)
    az_f         = round( 9.81 + 0.30 * math.sin(t * 1.3),  4)
    gx           = round(-1.03 + 0.40 * math.sin(t * 1.9),  4)
    gy           = round( 2.79 + 0.35 * math.cos(t * 2.3),  4)
    gz           = round(-0.23 + 0.20 * math.sin(t * 1.5),  4)
    temperature  = round(30.60 + 1.50 * math.sin(t * 0.3),  2)
    pressure_hpa = round(900.8 - 0.05 * pkt_id,             2)   # steady descent
    sensor_id    = 112
    lat          = round(19.4326 + 0.0005 * math.sin(t * 0.4), 6)
    lon          = round(-99.1332 + 0.0005 * math.cos(t * 0.4), 6)
    roll         = round(-0.67 + 0.30 * math.sin(t * 1.1),  4)
    pitch        = round( 8.69 + 0.25 * math.cos(t * 0.9),  4)
    altitude     = round(980.9 - 1.5 * pkt_id,              2)   # descending ~1.5m/pkt
    gps_data     = 1
    gps_ready    = 1
    uwTick       = time.ticks_ms()

    csv = "{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}".format(
        pkt_id,
        ax_f, ay_f, az_f,
        gx, gy, gz,
        temperature,
        pressure_hpa,
        sensor_id,
        lat, lon,
        roll, pitch,
        altitude,
        gps_data, gps_ready,
        uwTick
    )
    return csv

# ── LoRa helpers ─────────────────────────────────────────────
def lora_readline(timeout_ms=500):
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    buf = b""
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        if lora.any():
            c = lora.read(1)
            if c == b"\n":
                return buf.decode("utf-8", "ignore").strip()
            buf += c
    return ""

def lora_send(payload):
    cmd = "AT+SEND={},{},{}\r\n".format(GROUND_ADDR, len(payload), payload)
    lora.write(cmd)

def wait_ok(timeout_ms=1500):
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        line = lora_readline(200)
        if "+OK" in line:
            return True
    return False

def wait_ack(expected_id, timeout_ms=ACK_TIMEOUT):
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        line = lora_readline(300)
        if "+RCV=" in line:
            parts = line.split(",", 4)
            if len(parts) >= 3 and "ACK,{}".format(expected_id) in parts[2]:
                return True
    return False

# ── Main loop ────────────────────────────────────────────────
print("[ATSIQUE] Telemetry TX started")

while True:
    # ── Generate packet ONCE per cycle (pkt_id increments here only) ──
    csv        = get_mock_data()
    frozen_id  = pkt_id          # snapshot — never changes during retries
    print("[TX] pkt={} | {}".format(frozen_id, csv))

    sent = False
    for attempt in range(MAX_RETRIES):
        lora_send(csv)           # always resend the SAME csv string

        if not wait_ok():
            print("[WARN] No +OK (attempt {}/{})".format(attempt + 1, MAX_RETRIES))
            time.sleep_ms(500)
            continue

        if wait_ack(frozen_id):
            print("[ACK] Packet {} confirmed ✅".format(frozen_id))
            sent = True
            break
        else:
            print("[WARN] No ACK for pkt {} (attempt {}/{})".format(
                frozen_id, attempt + 1, MAX_RETRIES))
            time.sleep_ms(600)

    if not sent:
        print("[ERR] Packet {} lost after {} retries ❌".format(frozen_id, MAX_RETRIES))

    time.sleep_ms(TX_INTERVAL)
