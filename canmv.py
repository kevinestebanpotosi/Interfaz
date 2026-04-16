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
# NUEVO: CONFIGURACIÓN UART PARA LA STM32
# ============================================================
STM_RX_PIN = 4
STM_TX_PIN = 3
fpioa.set_function(STM_RX_PIN, FPIOA.UART1_RXD) # RX1 escucha al TX de STM32
fpioa.set_function(STM_TX_PIN, FPIOA.UART1_TXD)
telemetria_stm = None
try:
    telemetria_stm = UART(UART.UART1, baudrate=115200, bits=UART.EIGHTBITS, parity=UART.PARITY_NONE, stop=UART.STOPBITS_ONE)
    print("✅ UART1 inicializada (STM32 conectada en IO4).")
except Exception as e:
    print(f"❌ Error al inicializar UART de telemetría: {e}")

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
def crear_anaglifo_np(img_cam_np, mapa_np, size=224, max_shift=80):
    # En este ejemplo simplificado, asumimos que procesamos un cuadro central
    out_img = image.Image(size, size, image.RGB565)
    offset_y = (480 - size) // 2
    offset_x = (640 - size) // 2

    # Redimensionamos el mapa de profundidad para que coincida con el nuevo tamaño
    # (Para simplificar, tomamos un "paso" de 2 del mapa original de 224x224)
    #mapa_reducido = mapa_np[::2, ::2]

    for y in range(size):
        y_real = y + offset_y
        for x in range(size):
            # Usamos el mapa reducido
            prof = int(mapa_np[y, x])
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
    img_comprimida = img_3d.compress(quality=35)
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
# ─── 4. FUNCIONES DE TELEMETRÍA Y RADIO ─────────────────────────────────────

pkt_id = 0  # Necesitamos mantener el contador de paquetes

def obtener_telemetria_real():
    global pkt_id
    if telemetria_stm is None or not telemetria_stm.any():
        return None

    ultimo_mensaje = None

    # ⚠️ CLAVE: Drenar TODO el buffer para obtener el dato más FRESCO
    while telemetria_stm.any() > 0:
        try:
            linea = telemetria_stm.readline()
            if linea:
                decodificado = linea.decode('utf-8', 'ignore').strip()
                if "STATE" in decodificado or "ACC" in decodificado:
                    ultimo_mensaje = decodificado
        except:
            pass

    # Si no capturó nada válido, retorna None
    if not ultimo_mensaje:
        return None

    # --- PROCESO DE PARSEO SOBRE EL DATO MÁS RECIENTE ---
    state, ax, ay, az, gx, gy, gz, temp, pres, alt = "0","0","0","0","0","0","0","0","0","0"

    partes = ultimo_mensaje.split('|')
    for p in partes:
        p = p.strip()
        if p.startswith("STATE:"): state = p.split(':')[1].strip()
        elif p.startswith("ACC:"):
            v = p.replace("ACC:", "").strip().split()
            if len(v) >= 3: ax, ay, az = v[0], v[1], v[2]
        elif p.startswith("GYR:"):
            v = p.replace("GYR:", "").strip().split()
            if len(v) >= 3: gx, gy, gz = v[0], v[1], v[2]
        elif p.startswith("TEMP:"): temp = p.split(':')[1].strip()
        elif p.startswith("P:"): pres = p.split(':')[1].strip()
        elif p.startswith("ALT:"): alt = p.split(':')[1].strip()

    pkt_id += 1
    uwTick = time.ticks_ms()

    return f"{pkt_id},{ax},{ay},{az},{gx},{gy},{gz},{temp},{pres},{alt},{state},{uwTick}"
# ... (Continúa con crc16, lora_readline, etc) ...
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

# --- REEMPLAZA TU FUNCIÓN send_image_chunk POR ESTA VERSIÓN "FAST" ---
# --- 1. FUNCIÓN DE ENVÍO DE IMAGEN MEJORADA ---
def send_image_chunk(uart, pkt_num, total_pkts, payload: bytes):
    # Crear el frame binario
    header = ustruct.pack('>HHHB', 0xAA55, pkt_num, total_pkts, len(payload))
    frame = header + payload
    frame += ustruct.pack('>H', crc16(frame))

    # Convertir a Base64 y limpiar
    b64_frame = ubinascii.b2a_base64(frame).strip().decode()

    # Construir comando exacto
    cmd = f"AT+SEND={GROUND_ADDR},{len(b64_frame)},{b64_frame}\r\n"

    # Intentar enviar y esperar que el módulo acepte el comando
    for intento in range(2):
        uart.write(cmd)
        # Esperar respuesta del módulo LoRa (+OK)
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < 400: # Timeout de 400ms
            if uart.any():
                resp = uart.read().decode('utf-8', 'ignore')
                if "+OK" in resp:
                    time.sleep_ms(100) # Respiro para el hardware
                    return True
                if "+ERR" in resp:
                    break
        time.sleep_ms(200) # Esperar antes de reintentar si falló
    return False

# ─── 5. FASE DE TRANSMISIÓN (VERSIÓN ROBUSTA) ──────────────────────
# Reducimos a 60 bytes para asegurar que el comando AT sea corto y seguro
MAX_PAYLOAD = 60
chunks = [image_data[i:i+MAX_PAYLOAD] for i in range(0, len(image_data), MAX_PAYLOAD)]
total_chunks = len(chunks)
meta = ustruct.pack('>I', len(image_data))

vuelta_actual = 1
MAX_VUELTAS = 2
chunk_idx = -1
imagen_completada = False

# Telemetría cada 3 paquetes de imagen
RATIO_TELEMETRIA = 3
contador_prioridad = 0

ultimo_dato_sensores = f"0,0,0,0,0,0,0,0,0,0,0,{time.ticks_ms()}"

print(f"\n🚀 [VUELO] Imagen en {total_chunks} fragmentos de {MAX_PAYLOAD} bytes.")

while True:
    # 1. Capturar Telemetría STM32
    dato_nuevo = obtener_telemetria_real()
    if dato_nuevo is not None:
        ultimo_dato_sensores = dato_nuevo

    # 2. Lógica de Envío Intercalado
    if contador_prioridad < RATIO_TELEMETRIA:
        # --- CANAL DE DATOS ---
        csv_data = ultimo_dato_sensores
        lora.write(f"AT+SEND={GROUND_ADDR},{len(csv_data)},{csv_data}\r\n")

        # Un print corto para saber que vive
        print(".", end="")
        contador_prioridad += 1
        time.sleep_ms(60) # Tiempo entre paquetes de telemetría

    else:
        # --- CANAL DE IMAGEN ---
        if not imagen_completada and len(image_data) > 0:
            if chunk_idx == -1:
                print(f"\n[IMG] Enviando Meta (V{vuelta_actual})...", end="")
                if send_image_chunk(lora, 0, total_chunks + 1, meta):
                    chunk_idx += 1
            else:
                if send_image_chunk(lora, chunk_idx + 1, total_chunks + 1, chunks[chunk_idx]):
                    print(f"[{chunk_idx+1}]", end="")
                    chunk_idx += 1
                else:
                    print("!", end="") # ¡ significa que el LoRa rechazó el paquete (busy)

                if chunk_idx >= total_chunks:
                    print(f"\n✅ Vuelta {vuelta_actual} finalizada.")
                    vuelta_actual += 1
                    chunk_idx = -1
                    if vuelta_actual > MAX_VUELTAS:
                        imagen_completada = True
                        print("🏁 TRANSMISIÓN DE IMAGEN CERRADA.")

        # Reiniciar contador para volver a mandar telemetría
        contador_prioridad = 0
