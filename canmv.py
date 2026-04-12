# ============================================================
#  ATSIQUE CanSat — VUELO FINAL OPTIMIZADO (IA + Telemetría LoRa)
#  CanMV K230D Zero - ALTA VELOCIDAD
# ============================================================

import os, gc, time, math
import image, ustruct, ubinascii
import ulab.numpy as np
import nncase_runtime as nn
from machine import UART, FPIOA
from media.sensor import *
from media.media import MediaManager
from libs.PipeLine import PipeLine, ScopedTiming
from libs.AIBase import AIBase
from libs.AI2D import Ai2d

# ─── 1. ESTABILIZACIÓN Y CONFIGURACIÓN LORA ─────────────────────────────────
print("🔌 Conectado a batería. Estabilizando (5s)...")
time.sleep(5)

LORA_TX_PIN = 11
LORA_RX_PIN = 12
GROUND_ADDR = 0
MAX_RETRIES = 2
ACK_TIMEOUT = 2000 # Reducido a 1s para mayor agilidad

fpioa = FPIOA()
fpioa.set_function(LORA_TX_PIN, FPIOA.UART2_TXD)
fpioa.set_function(LORA_RX_PIN, FPIOA.UART2_RXD)
lora = UART(UART.UART2, baudrate=115200, bits=UART.EIGHTBITS, parity=UART.PARITY_NONE, stop=UART.STOPBITS_ONE, timeout=2000)

# OPTIMIZACIÓN: SF7 para mayor velocidad de transmisión en el aire
print("Configurando LoRa (SF7 + ADDR1)...")
lora.write(b'AT+ADDRESS=1\r\n')           # El satélite es la dirección 1
time.sleep(0.5)
lora.write(b'AT+PARAMETER=7,7,1,12\r\n')  # SF7 (el primer 7) coincidente con la PC
time.sleep(1)

# ─── 2. CLASES DE INTELIGENCIA ARTIFICIAL ───────────────────────────────────
def ALIGN_UP(x, align):
    return (x + align - 1) & ~(align - 1)

class DepthNetApp(AIBase):
    def __init__(self, kmodel_path, model_input_size=[224, 224], rgb888p_size=[640, 480], debug_mode=0):
        super().__init__(kmodel_path, model_input_size, rgb888p_size, debug_mode)
        self.kmodel_path = kmodel_path
        self.model_input_size = model_input_size
        self.rgb888p_size = [ALIGN_UP(rgb888p_size[0], 16), rgb888p_size[1]]
        self.debug_mode = debug_mode
        self.ai2d = Ai2d(debug_mode)
        self.ai2d.set_ai2d_dtype(nn.ai2d_format.NCHW_FMT, nn.ai2d_format.NCHW_FMT, np.uint8, np.uint8)

    def config_preprocess(self, input_image_size=None):
        with ScopedTiming("set preprocess config", self.debug_mode > 0):
            ai2d_input_size = input_image_size if input_image_size else self.rgb888p_size
            self.ai2d.resize(nn.interp_method.tf_bilinear, nn.interp_mode.half_pixel)
            self.ai2d.build([1, 3, ai2d_input_size[1], ai2d_input_size[0]],
                            [1, 3, self.model_input_size[1], self.model_input_size[0]])

    def postprocess(self, results):
        mapa_np = results[0]
        if len(mapa_np.shape) == 4: mapa_2d = mapa_np[0][0]
        else: mapa_2d = mapa_np.reshape((224, 224))
        min_v = np.min(mapa_2d)
        max_v = np.max(mapa_2d)
        mapa_norm = (mapa_2d - min_v) * (255.0 / (max_v - min_v + 1e-5))
        return np.array(mapa_norm, dtype=np.uint8)

# OPTIMIZACIÓN: Procesamos a menor resolución (112x112) para que el bucle `for` vuele.
def crear_anaglifo_np(img_cam_np, mapa_np, size=112, max_shift=8):
    # En este ejemplo simplificado, asumimos que procesamos un cuadro central
    out_img = image.Image(size, size, image.RGB565)
    offset_y = (480 - size) // 2
    offset_x = (640 - size) // 2

    # Redimensionamos el mapa de profundidad para que coincida con el nuevo tamaño
    # (Para simplificar, tomamos un "paso" de 2 del mapa original de 224x224)
    mapa_reducido = mapa_np[::2, ::2]

    for y in range(size):
        y_real = y + offset_y
        for x in range(size):
            # Usamos el mapa reducido
            prof = int(mapa_reducido[y, x])
            shift = (prof * max_shift) // 255
            x_r = min(max(x + offset_x - shift, 0), 639)
            x_c = min(max(x + offset_x + shift, 0), 639)
            r = int(img_cam_np[0, y_real, x_r])
            g = int(img_cam_np[1, y_real, x_c])
            b = int(img_cam_np[2, y_real, x_c])
            out_img.set_pixel(x, y, (r, g, b))
    return out_img

# ─── 3. FASE DE CAPTURA Y PROCESAMIENTO ─────────────────────────────────────
print("\n[FASE 1] Iniciando Cámara y Red Neuronal...")
pl = PipeLine(rgb888p_size=[640, 480], display_size=[640, 480])
pl.create(Sensor(width=640, height=480))

depth_app = DepthNetApp("/sdcard/examples/kmodel/kpu_depth_model.kmodel")
depth_app.config_preprocess()

time.sleep(2)

try:
    print("📸 Tomando foto y calculando profundidad...")
    img_np = pl.get_frame()
    mapa_np = depth_app.run(img_np)

    print("🕶️ Creando efecto Anaglifo 3D (Optimizado a 112x112)...")
    t_start = time.ticks_ms()
    img_3d = crear_anaglifo_np(img_np, mapa_np)
    t_end = time.ticks_ms()
    print(f"   (Tiempo de procesamiento píxel a píxel: {time.ticks_diff(t_end, t_start)}ms)")

    print("🗜️ Comprimiendo imagen JPEG...")
    img_comprimida = img_3d.compress(quality=20)
    image_data = bytes(img_comprimida)
    print(f"✅ ¡Carga Útil lista! Tamaño ultraligero: {len(image_data)} bytes")

except Exception as e:
    print(f"❌ Error en captura: {e}")
    image_data = b''

# Liberar memoria agresivamente
pl.destroy()
depth_app.deinit()
del img_np, mapa_np
gc.collect()

# ─── 4. FUNCIONES DE TELEMETRÍA Y RADIO ─────────────────────────────────────
pkt_id = 0
def get_mock_data():
    global pkt_id
    pkt_id += 1
    t = time.ticks_ms() / 1000.0
    ax_f = round(-0.11 + 0.15 * math.sin(t * 2.1), 2)
    ay_f = round( 0.03 + 0.12 * math.cos(t * 1.7), 2)
    az_f = round( 9.81 + 0.30 * math.sin(t * 1.3), 2)
    gx = round(-1.03 + 0.40 * math.sin(t * 1.9), 2)
    gy = round( 2.79 + 0.35 * math.cos(t * 2.3), 2)
    gz = round(-0.23 + 0.20 * math.sin(t * 1.5), 2)
    temperature = round(30.60 + 1.50 * math.sin(t * 0.3), 1)
    pressure_hpa = round(900.8 - 0.05 * pkt_id, 1)
    lat = round(19.4326 + 0.0005 * math.sin(t * 0.4), 5)
    lon = round(-99.1332 + 0.0005 * math.cos(t * 0.4), 5)
    roll = round(-0.67 + 0.30 * math.sin(t * 1.1), 2)
    pitch = round( 8.69 + 0.25 * math.cos(t * 0.9), 2)
    altitude = round(980.9 - 1.5 * pkt_id, 1)
    uwTick = time.ticks_ms()
    # Cadena optimizada: Reducción de decimales y eliminación de variables inútiles
    return f"{pkt_id},{ax_f},{ay_f},{az_f},{gx},{gy},{gz},{temperature},{pressure_hpa},112,{lat},{lon},{roll},{pitch},{altitude},1,1,{uwTick}"

def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8): crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc

def lora_readline(timeout_ms=300):
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    buf = b""
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        if lora.any():
            c = lora.read(1)
            if c == b"\n": return buf.decode("utf-8", "ignore").strip()
            buf += c
        time.sleep_ms(2)
    return ""

def wait_ok(timeout_ms=500):
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        line = lora_readline(100)
        if "+OK" in line: return True
        if "+ERR" in line: return False
    return False

def wait_ack(expected_id, timeout_ms=ACK_TIMEOUT):
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    expected_str = f"ACK,{expected_id}"
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        line = lora_readline(200)
        if "+RCV=" in line and expected_str in line: return True
    return False

def send_image_chunk(uart, pkt_num, total_pkts, payload: bytes):
    header = ustruct.pack('>HHHB', 0xAA55, pkt_num, total_pkts, len(payload))
    frame = header + payload
    frame += ustruct.pack('>H', crc16(frame))
    b64_frame = ubinascii.b2a_base64(frame).strip()
    cmd = b"AT+SEND=" + str(GROUND_ADDR).encode() + b"," + str(len(b64_frame)).encode() + b"," + b64_frame + b"\r\n"

    for _ in range(3):
        uart.write(cmd)
        resp = ""
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < 1000:
            if uart.any():
                resp += uart.read().decode('utf-8', 'ignore')
                if "\n" in resp: break
        if "+OK" in resp:
            break
        else:
            time.sleep_ms(300)

    # Respiro de radio ajustado para la nueva velocidad
    time.sleep_ms(200)

# ─── 5. FASE DE TRANSMISIÓN ─────────────────────────────────────────────────
MAX_PAYLOAD = 100 # Subimos levemente el payload dado que la velocidad es mayor
chunks = [image_data[i:i+MAX_PAYLOAD] for i in range(0, len(image_data), MAX_PAYLOAD)]
total_chunks = len(chunks)
meta = ustruct.pack('>I', len(image_data))

vuelta_actual = 1
MAX_VUELTAS = 2
chunk_idx = -1
imagen_completada = False

print("\n🚀 [FASE 2] VUELO OPTIMIZADO (Modo SF7)...")

while True:
    csv_data = get_mock_data()
    frozen_id = pkt_id
    print(f"\n[TEL TX] pkt={frozen_id} | Alt: {round(980.9 - 1.5 * pkt_id, 1)}m")

    sent_telemetry = False
    for attempt in range(MAX_RETRIES):
        cmd = f"AT+SEND={GROUND_ADDR},{len(csv_data)},{csv_data}\r\n"
        lora.write(cmd)
        if not wait_ok(500):
            time.sleep_ms(300)
            continue
        if wait_ack(frozen_id):
            print("  [ACK] Confirmada ✅")
            sent_telemetry = True
            break

    if not sent_telemetry:
        print("  [ERR] A ciegas ❌")

    time.sleep_ms(1000)

    # --- B. ENVIAR IMAGEN ---
    if not imagen_completada and len(image_data) > 0:
        if chunk_idx == -1:
            send_image_chunk(lora, 0, total_chunks + 1, meta)
            chunk_idx += 1
        else:
            chunk = chunks[chunk_idx]
            print(f"[IMG TX] Pkt {chunk_idx + 1}/{total_chunks} (V{vuelta_actual})")
            send_image_chunk(lora, chunk_idx + 1, total_chunks + 1, chunk)

            if chunk_idx == 0 and vuelta_actual == 1:
                send_image_chunk(lora, chunk_idx + 1, total_chunks + 1, chunk)
                send_image_chunk(lora, chunk_idx + 1, total_chunks + 1, chunk)

            chunk_idx += 1
            if chunk_idx >= total_chunks:
                vuelta_actual += 1
                chunk_idx = -1
                if vuelta_actual > MAX_VUELTAS:
                    imagen_completada = True
                    print("\n✅ Imagen Enviada. Manteniendo Telemetría...")

    time.sleep_ms(300)
