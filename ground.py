# ============================================================
#  ATSIQUE CanSat — Ground Station Telemetry Receiver
#  Receives CSV telemetry, sends ACK, saves to .csv file
# ============================================================

import serial, time, os, csv

# ── Config ───────────────────────────────────────────────────
PORT      = "COM7"   # ← change to your port
BAUDRATE  = 115200
SAT_ADDR  = 1
SAVE_FILE = "telemetry.csv"

HEADERS = [
    "pkt_id",
    "ax_f", "ay_f", "az_f",
    "gx", "gy", "gz",
    "temperature",
    "pressure_hpa",
    "sensor_id",
    "lat", "lon",
    "roll", "pitch",
    "altitude",
    "gps_data", "gps_ready",
    "uwTick"
]

# ── Init CSV file ─────────────────────────────────────────────
write_header = not os.path.exists(SAVE_FILE)
csv_file = open(SAVE_FILE, "a", newline="")
writer   = csv.writer(csv_file)
if write_header:
    writer.writerow(HEADERS)
    csv_file.flush()
print("[BASE] Saving to: {}".format(SAVE_FILE))

# ── Serial ────────────────────────────────────────────────────
try:
    ser = serial.Serial(PORT, BAUDRATE, timeout=1)
    time.sleep(1)
    print("[BASE] ✅ Connected to {}".format(PORT))
except Exception as e:
    print(f"[ERR] No se pudo abrir el puerto {PORT}: {e}")
    exit()

# ── Helpers ───────────────────────────────────────────────────
def parse_rcv(line: str):
    """Extracción ROBUSTA para evitar cortes por las comas del CSV"""
    if not line.startswith("+RCV="):
        return None
    inner = line[5:]
    
    parts = inner.split(",", 2)
    if len(parts) < 3:
        return None
        
    raw_data_rssi_snr = parts[2]
    tokens = raw_data_rssi_snr.rsplit(",", 2) 
    if len(tokens) < 3:
        return None
        
    return tokens[0] 

def send_ack(pkt_id):
    payload = "ACK,{}".format(pkt_id)
    cmd = "AT+SEND={},{},{}\r\n".format(SAT_ADDR, len(payload), payload)
    ser.write(cmd.encode())
    time.sleep(0.3)
    print("[ACK] Sent ACK for pkt {}".format(pkt_id))

def parse_telemetry(payload):
    """Parse CSV payload into dict."""
    fields = payload.split(",")
    if len(fields) != len(HEADERS):
        return None
    return dict(zip(HEADERS, fields))

# ── Main loop ─────────────────────────────────────────────────
print("[BASE] Waiting for telemetry...\n")

while True:
    raw = ser.readline().decode("utf-8", "ignore").strip()
    if not raw:
        continue

    print("[RAW] {}".format(raw))

    payload = parse_rcv(raw)
    if payload is None:
        continue

    # 🔴 Seguro Anti-Imágenes 🔴
    if "," not in payload:
        print("[IMG] 🖼️  Fragmento de imagen detectado. Ignorando en la consola CSV...")
        continue

    data = parse_telemetry(payload)
    if data is None:
        print("[WARN] Unexpected format: {}".format(payload))
        continue

    # Print nicely
    print("─" * 50)
    print("📦 Packet #{}".format(data["pkt_id"]))
    print("  Accel  : ax={} ay={} az={}".format(data["ax_f"], data["ay_f"], data["az_f"]))
    print("  Gyro   : gx={} gy={} gz={}".format(data["gx"], data["gy"], data["gz"]))
    print("  Temp   : {}°C  |  Pressure: {} hPa".format(data["temperature"], data["pressure_hpa"]))
    print("  GPS    : lat={} lon={}  ready={}".format(data["lat"], data["lon"], data["gps_ready"]))
    print("  Att    : roll={}  pitch={}".format(data["roll"], data["pitch"]))
    print("  Alt    : {} m".format(data["altitude"]))
    print("  uwTick : {}".format(data["uwTick"]))
    print("─" * 50)

    # Save to CSV
    writer.writerow([data[h] for h in HEADERS])
    csv_file.flush()
    print("[CSV] Row saved ✅")

    # Send ACK
    send_ack(data["pkt_id"])