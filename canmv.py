# ==============================================================================
#  ATSIQUE CanSat — VUELO FINAL OPTIMIZADO
#  CanMV K230D Zero — Visión Artificial + Telemetría LoRa
#
#  Arquitectura del vuelo:
#    FASE 1 → Captura de imagen + inferencia de profundidad + anaglifo 3D
#    FASE 2 → Bucle principal: envío de telemetría CSV + imagen en chunks por LoRa
# ==============================================================================

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


# ==============================================================================
#  SECCIÓN A — PARÁMETROS CONFIGURABLES
#  Todos los valores que probablemente quieras ajustar están aquí arriba.
#  No es necesario tocar el resto del código para experimentos normales.
# ==============================================================================

# ── A1. Parámetros de imagen y calidad ────────────────────────────────────────

# Resolución de captura de la cámara (ancho x alto en píxeles)
# Valores típicos: [320,240] / [640,480] / [1280,720]
CAMERA_WIDTH  = 640
CAMERA_HEIGHT = 480

# Tamaño de entrada del modelo de profundidad (debe coincidir con el kmodel)
MODEL_INPUT_SIZE = [224, 224]

# Tamaño del anaglifo 3D generado (en píxeles, cuadrado)
# Reducir este valor acelera el procesamiento píxel-a-píxel considerablemente.
# Valores sugeridos: 56, 112, 224
ANAGLIFO_SIZE = 224

# Desplazamiento máximo del efecto 3D (en píxeles)
# Aumentar = mayor sensación de profundidad; disminuir = imagen más "plana"
ANAGLIFO_MAX_SHIFT = 60

# Calidad JPEG de compresión al transmitir (0–100)
# Menor valor = menor tamaño en bytes, peor nitidez visual
# Valores sugeridos: 20 (mínimo aceptable), 35 (equilibrio), 60 (buena calidad)
JPEG_QUALITY = 40

# ── A2. Parámetros de radio LoRa ───────────────────────────────────────────────

LORA_TX_PIN   = 11       # Pin TX conectado al módulo LoRa
LORA_RX_PIN   = 12       # Pin RX conectado al módulo LoRa
GROUND_ADDR   = 0        # Dirección LoRa de la estación en tierra
SATELLITE_ADDR = 1       # Dirección LoRa del satélite (este dispositivo)

# Spreading Factor de LoRa. Menor SF = mayor velocidad, menor alcance.
# SF7 es el más rápido; SF12 tiene mayor alcance pero ~40x más lento.
# Debe coincidir con la configuración de la estación en tierra.
LORA_SF = 7

# Tamaño máximo de payload por chunk de imagen (bytes, antes de base64)
# Con SF7 y baudrate 115200, 100 bytes es un buen balance.
MAX_PAYLOAD_BYTES = 100

# Número de veces que se retransmite la imagen completa (redundancia)
MAX_VUELTAS_IMAGEN = 3

# Reintentos máximos para el paquete de telemetría
MAX_RETRIES_TELEMETRIA = 2

# Timeout para recibir ACK de la estación tierra (ms)
ACK_TIMEOUT_MS = 2000

# ── A3. Parámetros de tiempo de arranque ──────────────────────────────────────

# Tiempo de espera tras conectar batería (permite estabilizar voltajes)
BOOT_DELAY_SEGUNDOS = 5


# ==============================================================================
#  SECCIÓN B — INICIALIZACIÓN DE HARDWARE
# ==============================================================================

print(f"🔌 Conectado a batería. Estabilizando ({BOOT_DELAY_SEGUNDOS}s)...")
time.sleep(BOOT_DELAY_SEGUNDOS)

# Asignar pines UART al módulo LoRa mediante la tabla FPIOA del K230
fpioa = FPIOA()
fpioa.set_function(LORA_TX_PIN, FPIOA.UART2_TXD)
fpioa.set_function(LORA_RX_PIN, FPIOA.UART2_RXD)

# Inicializar UART2 para comunicación con el módulo LoRa (RYLR998 o similar)
lora = UART(
    UART.UART2,
    baudrate=115200,
    bits=UART.EIGHTBITS,
    parity=UART.PARITY_NONE,
    stop=UART.STOPBITS_ONE,
    timeout=2000
)

# Configurar el módulo LoRa vía comandos AT
print(f"Configurando LoRa (SF{LORA_SF}, ADDR={SATELLITE_ADDR})...")
lora.write(f"AT+ADDRESS={SATELLITE_ADDR}\r\n".encode())
time.sleep(0.5)
# Formato: SF, Bandwidth index, Coding Rate, Preamble
# SF{LORA_SF}, BW=125kHz (7), CR=4/5 (1), Preamble=12
lora.write(f"AT+PARAMETER={LORA_SF},7,1,12\r\n".encode())
time.sleep(1)


# ==============================================================================
#  SECCIÓN C — CLASES DE INTELIGENCIA ARTIFICIAL
# ==============================================================================

def ALIGN_UP(x, align):
    """Alinea 'x' al múltiplo superior de 'align'. Requerido por el hardware K230."""
    return (x + align - 1) & ~(align - 1)


class DepthNetApp(AIBase):
    """
    Red neuronal de estimación de profundidad monocular.

    Toma un frame de cámara RGB888P y produce un mapa de profundidad
    normalizado como array 2D de uint8 (224x224).

    Hereda de AIBase que gestiona la carga del kmodel y la inferencia KPU.
    """

    def __init__(self,
                 kmodel_path,
                 model_input_size=MODEL_INPUT_SIZE,
                 rgb888p_size=[CAMERA_WIDTH, CAMERA_HEIGHT],
                 debug_mode=0):
        super().__init__(kmodel_path, model_input_size, rgb888p_size, debug_mode)
        self.kmodel_path     = kmodel_path
        self.model_input_size = model_input_size
        # El hardware K230 requiere que el ancho esté alineado a 16 bytes
        self.rgb888p_size    = [ALIGN_UP(rgb888p_size[0], 16), rgb888p_size[1]]
        self.debug_mode      = debug_mode

        # Ai2d gestiona el redimensionado en hardware (mucho más rápido que software)
        self.ai2d = Ai2d(debug_mode)
        self.ai2d.set_ai2d_dtype(
            nn.ai2d_format.NCHW_FMT,
            nn.ai2d_format.NCHW_FMT,
            np.uint8,
            np.uint8
        )

    def config_preprocess(self, input_image_size=None):
        """Configura el pipeline de preprocesado: resize bilinear al tamaño del modelo."""
        with ScopedTiming("set preprocess config", self.debug_mode > 0):
            ai2d_input_size = input_image_size if input_image_size else self.rgb888p_size
            self.ai2d.resize(nn.interp_method.tf_bilinear, nn.interp_mode.half_pixel)
            self.ai2d.build(
                [1, 3, ai2d_input_size[1], ai2d_input_size[0]],
                [1, 3, self.model_input_size[1], self.model_input_size[0]]
            )

    def postprocess(self, results):
        """
        Normaliza la salida cruda del modelo a rango [0, 255] uint8.
        La salida del modelo puede ser [1,1,H,W] o un tensor plano.
        """
        mapa_np = results[0]

        # Aplanar dimensiones batch/canal si es necesario
        if len(mapa_np.shape) == 4:
            mapa_2d = mapa_np[0][0]
        else:
            mapa_2d = mapa_np.reshape((224, 224))

        # Normalización min-max a [0, 255]
        min_v    = np.min(mapa_2d)
        max_v    = np.max(mapa_2d)
        mapa_norm = (mapa_2d - min_v) * (255.0 / (max_v - min_v + 1e-5))

        return np.array(mapa_norm, dtype=np.uint8)


# ==============================================================================
#  SECCIÓN D — PROCESAMIENTO DE IMAGEN (ANAGLIFO 3D)
# ==============================================================================

def crear_anaglifo_np(img_cam_np, mapa_np,
                      size=ANAGLIFO_SIZE,
                      max_shift=ANAGLIFO_MAX_SHIFT):
    """
    Genera una imagen anaglifo 3D (rojo-cian) a partir del frame y el mapa de profundidad.

    El canal rojo (ojo izquierdo) se desplaza HACIA la izquierda según la profundidad.
    Los canales verde y azul (ojo derecho) se desplazan HACIA la derecha.

    Args:
        img_cam_np:  Array NCHW (3, H, W) con el frame RGB de la cámara.
        mapa_np:     Array 2D (224x224) con el mapa de profundidad normalizado [0,255].
        size:        Tamaño en píxeles del cuadro de salida (cuadrado).
        max_shift:   Desplazamiento máximo en píxeles para la ilusión de profundidad.

    Returns:
        Objeto image.Image (RGB565) listo para comprimir o mostrar.
    """
    out_img = image.Image(size, size, image.RGB565)

    # Calcular offset para recortar el centro del frame de cámara
    offset_y = (CAMERA_HEIGHT - size) // 2
    offset_x = (CAMERA_WIDTH  - size) // 2

    for y in range(size):
        y_real = y + offset_y
        for x in range(size):
            # La profundidad determina cuánto se desplazan los canales
            prof  = int(mapa_np[y, x])
            shift = (prof * max_shift) // 255

            # Coordenadas con desplazamiento opuesto por canal
            x_r = min(max(x + offset_x - shift, 0), CAMERA_WIDTH - 1)  # Canal R (izq)
            x_c = min(max(x + offset_x + shift, 0), CAMERA_WIDTH - 1)  # Canales G,B (der)

            r = int(img_cam_np[0, y_real, x_r])
            g = int(img_cam_np[1, y_real, x_c])
            b = int(img_cam_np[2, y_real, x_c])

            out_img.set_pixel(x, y, (r, g, b))

    return out_img


# ==============================================================================
#  SECCIÓN E — FASE 1: CAPTURA, INFERENCIA Y COMPRESIÓN
# ==============================================================================

print("\n[FASE 1] Iniciando cámara y red neuronal...")

pl = PipeLine(
    rgb888p_size=[CAMERA_WIDTH, CAMERA_HEIGHT],
    display_size=[CAMERA_WIDTH, CAMERA_HEIGHT]
)
pl.create(Sensor(width=CAMERA_WIDTH, height=CAMERA_HEIGHT))

depth_app = DepthNetApp("/sdcard/examples/kmodel/kpu_depth_model.kmodel")
depth_app.config_preprocess()

time.sleep(2)  # Dejar que el sensor de imagen se estabilice

try:
    print("📸 Capturando frame y ejecutando inferencia de profundidad...")
    img_np   = pl.get_frame()
    mapa_np  = depth_app.run(img_np)

    print(f"🕶️  Generando anaglifo 3D ({ANAGLIFO_SIZE}x{ANAGLIFO_SIZE} px)...")
    t_start  = time.ticks_ms()
    img_3d   = crear_anaglifo_np(img_np, mapa_np)
    t_end    = time.ticks_ms()
    print(f"   → Tiempo de renderizado: {time.ticks_diff(t_end, t_start)} ms")

    print(f"🗜️  Comprimiendo a JPEG (calidad={JPEG_QUALITY})...")
    img_comprimida = img_3d.compress(quality=JPEG_QUALITY)
    image_data     = bytes(img_comprimida)
    print(f"✅ Imagen lista. Tamaño: {len(image_data)} bytes")

except Exception as e:
    print(f"❌ Error en Fase 1: {e}")
    image_data = b''

# Liberar memoria de cámara y modelo antes de la fase de transmisión
pl.destroy()
depth_app.deinit()
del img_np, mapa_np
gc.collect()
print(f"   → Memoria liberada. Iniciando transmisión...")


# ==============================================================================
#  SECCIÓN F — FUNCIONES DE TELEMETRÍA Y RADIO
# ==============================================================================
#CONFIGURACIÓN UART PARA LA STM32
# ============================================================
pkt_id = 0
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

# Variable global para mantener los datos si la UART está vacía en un ciclo
last_valid_csv = "0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0"

def get_telemetry_data():
    """
    Lee la UART1, limpia el texto de la STM32 y devuelve el CSV de 18 campos.
    """
    global pkt_id, last_valid_csv

    # 1. Intentar leer una línea de la STM32
    if telemetria_stm.any():
        try:
            line = telemetria_stm.readline()
            if not line: return last_valid_csv

            # Decodificar y limpiar caracteres extraños
            raw_str = line.decode('utf-8').strip()

            # 2. PROCESAMIENTO DE LA CADENA (Parsing)
            # Asumiendo que la STM envía: | STATE: 1 |ACC: x y z |GYR: x y z ...
            # Reemplazamos las etiquetas y barras por espacios para separar solo números
            clean_str = raw_str.replace('|', ' ').replace(':', ' ')
            parts = clean_str.split()

            # Extraemos solo los valores numéricos de la cadena
            # (Este filtro ignora palabras como 'ACC', 'GYR', 'STATE', etc.)
            nums = []
            for p in parts:
                try:
                    # Intentamos convertir cada fragmento a número
                    val = float(p)
                    nums.append(val)
                except:
                    continue

            # 3. VERIFICACIÓN Y CONSTRUCCIÓN DEL PAQUETE FINAL
            # Necesitamos asegurar que tenemos los datos suficientes para los 18 campos.
            # Si la STM32 envió los datos esperados (aprox 15-16 valores):
            if len(nums) >= 15:
                pkt_id += 1

                # Mapeo de datos (Ajusta los índices según el orden de tu STM32)
                # nums[0]=estado1, nums[1..3]=acc, nums[4..6]=gyr, etc.
                ax, ay, az = nums[1], nums[2], nums[3]
                gx, gy, gz = nums[4], nums[5], nums[6]
                temp, pres, hum = nums[7], nums[8], nums[9]
                lat, lon = nums[10], nums[11]
                roll, pitch = nums[12], nums[13]
                alt = nums[14]
                e1, e2 = int(nums[0]), 1 # Estados

                t_ms = time.ticks_ms()

                # Construir el CSV de 18 campos exactos
                last_valid_csv = "{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}".format(
                    pkt_id, ax, ay, az, gx, gy, gz,
                    temp, pres, hum,
                    lat, lon, roll, pitch, alt,
                    e1, e2, t_ms
                )

        except Exception as e:
            print("⚠️ Error procesando UART STM32:", e)

    return last_valid_csv


# ── F2. Utilidades de protocolo LoRa ──────────────────────────────────────────

def crc16(data):  # data: bytes -> int
    """CRC-16/ARC para verificación de integridad de paquetes de imagen."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def lora_readline(timeout_ms=300):
    """Lee una línea de la UART del módulo LoRa con timeout."""
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    buf = b""
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        if lora.any():
            c = lora.read(1)
            if c == b"\n":
                return buf.decode("utf-8", "ignore").strip()
            buf += c
        time.sleep_ms(2)
    return ""


def wait_ok(timeout_ms=500):
    """Espera la respuesta '+OK' del módulo LoRa tras un AT+SEND."""
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        line = lora_readline(100)
        if "+OK"  in line: return True
        if "+ERR" in line: return False
    return False


def wait_ack(expected_id, timeout_ms=ACK_TIMEOUT_MS):
    """
    Espera el ACK de la estación tierra para el paquete 'expected_id'.

    El ACK esperado tiene el formato: '+RCV=...,ACK,{expected_id},...'
    """
    deadline     = time.ticks_add(time.ticks_ms(), timeout_ms)
    expected_str = f"ACK,{expected_id}"
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        line = lora_readline(200)
        if "+RCV=" in line and expected_str in line:
            return True
    return False


def send_image_chunk(uart, pkt_num, total_pkts, payload):  # payload: bytes
    """
    Empaqueta y envía un chunk de imagen por LoRa.

    Estructura del frame (antes de base64):
        [0xAA55] [pkt_num: u16] [total_pkts: u16] [payload_len: u8]
        [payload: bytes]
        [crc16: u16]

    El frame completo se codifica en base64 para compatibilidad con AT+SEND.
    Se reintenta hasta 3 veces si no se recibe '+OK'.
    """
    header    = ustruct.pack('>HHHB', 0xAA55, pkt_num, total_pkts, len(payload))
    frame     = header + payload
    frame    += ustruct.pack('>H', crc16(frame))
    b64_frame = ubinascii.b2a_base64(frame).strip()

    cmd = (b"AT+SEND=" + str(GROUND_ADDR).encode() + b"," +
           str(len(b64_frame)).encode() + b"," + b64_frame + b"\r\n")

    for intento in range(3):
        uart.write(cmd)
        resp  = ""
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < 1000:
            if uart.any():
                resp += uart.read().decode('utf-8', 'ignore')
                if "\n" in resp:
                    break
        if "+OK" in resp:
            break
        else:
            time.sleep_ms(300)

    # Pausa entre chunks para no saturar el canal de radio
    time.sleep_ms(200)


# ==============================================================================
#  SECCIÓN G — FASE 2: BUCLE PRINCIPAL DE VUELO
# ==============================================================================

# Preparar los chunks de imagen para la transmisión
chunks        = [image_data[i:i + MAX_PAYLOAD_BYTES] for i in range(0, len(image_data), MAX_PAYLOAD_BYTES)]
total_chunks  = len(chunks)
meta_header   = ustruct.pack('>I', len(image_data))  # Paquete 0: tamaño total de la imagen

# Estado de la transmisión de imagen
vuelta_actual    = 1
chunk_idx        = -1   # -1 = próximo paso es enviar el header de metadata
imagen_enviada   = False

print(f"\n🚀 [FASE 2] Iniciando bucle de vuelo (SF{LORA_SF}, {total_chunks} chunks de imagen)...")
print(f"   Imagen: {len(image_data)} bytes → {total_chunks} chunks de {MAX_PAYLOAD_BYTES} bytes")

while True:

    # ── G1. TELEMETRÍA ─────────────────────────────────────────────────────────
    csv_data  = get_telemetry_data()
    frozen_id = pkt_id  # Guardar ID antes de cualquier posible cambio concurrente
    altitud_actual = round(980.9 - 1.5 * pkt_id, 1)
    print(f"\n[TEL] pkt={frozen_id} | Alt={altitud_actual}m")

    enviado_ok = False
    for intento in range(MAX_RETRIES_TELEMETRIA):
        cmd = f"AT+SEND={GROUND_ADDR},{len(csv_data)},{csv_data}\r\n"
        lora.write(cmd)
        if not wait_ok(500):
            time.sleep_ms(300)
            continue
        if wait_ack(frozen_id):
            print("  [ACK] ✅")
            enviado_ok = True
            break

    if not enviado_ok:
        print("  [WARN] Sin ACK — transmisión a ciegas ❌")

    time.sleep_ms(1000)  # Pausa entre telemetría e imagen

    # ── G2. IMAGEN (chunk por ciclo) ───────────────────────────────────────────
    if not imagen_enviada and len(image_data) > 0:

        if chunk_idx == -1:
            # Paquete especial 0: informa a tierra el tamaño total de la imagen
            print(f"[IMG] Enviando header de metadata ({len(image_data)} bytes totales)")
            send_image_chunk(lora, 0, total_chunks + 1, meta_header)
            chunk_idx = 0

        else:
            chunk = chunks[chunk_idx]
            print(f"[IMG] Chunk {chunk_idx + 1}/{total_chunks} — Vuelta {vuelta_actual}/{MAX_VUELTAS_IMAGEN}")
            send_image_chunk(lora, chunk_idx + 1, total_chunks + 1, chunk)

            # Redundancia extra para el primer chunk (más crítico para decodificación)
            if chunk_idx == 0 and vuelta_actual == 1:
                print("  [REDUNDANCIA] Reenviando chunk 1 x2 por seguridad")
                send_image_chunk(lora, chunk_idx + 1, total_chunks + 1, chunk)
                send_image_chunk(lora, chunk_idx + 1, total_chunks + 1, chunk)

            chunk_idx += 1

            # Al terminar todos los chunks, verificar si se completaron las vueltas
            if chunk_idx >= total_chunks:
                vuelta_actual += 1
                chunk_idx = -1  # Reiniciar para enviar header en la próxima vuelta

                if vuelta_actual > MAX_VUELTAS_IMAGEN:
                    imagen_enviada = True
                    print("\n✅ Imagen transmitida completamente. Continuando solo con telemetría...")

    time.sleep_ms(300)  # Pequeña pausa al final del ciclo
