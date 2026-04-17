# ==============================================================================
#  ATSIQUE CanSat — ORQUESTADOR NO BLOQUEANTE (SUPER LOOP)
# ==============================================================================

import os, gc, time, network, socket
import image
import ulab.numpy as np
import nncase_runtime as nn
from machine import UART, FPIOA
from media.sensor import *
from media.media import MediaManager
from libs.PipeLine import PipeLine
from libs.AIBase import AIBase
from libs.AI2D import Ai2d

# ==============================================================================
# ⚙️ CONFIGURACIÓN GLOBAL
# ==============================================================================
class Config:
    WIFI_SSID     = "K230_Telemetria"
    WIFI_PASS     = "password123"
    TCP_PORT      = 5000

    STM_UART_ID   = 1
    LORA_UART_ID  = 2
    UART_BAUD     = 115200

    STM_TX_PIN    = 3
    STM_RX_PIN    = 4
    LORA_TX_PIN   = 11
    LORA_RX_PIN   = 12

    IMG_RES       = 224
    JPEG_QUALITY  = 50
    ANAGLYPH_SHIFT = 12

    MAX_FOTOS = 5
    INTERVALO_FOTOS_MS = 60000  # 2 Minutos entre fotos
    INTERVALO_LORA_MS  = 1000    # 1 Segundo entre paquetes LoRa (Evita saturar el aire)

# ==============================================================================
# 🧠 IA Y VISIÓN (Funciones Auxiliares)
# ==============================================================================
def ALIGN_UP(x, align): return (x + align - 1) & ~(align - 1)

class DepthNetApp(AIBase):
    def __init__(self, kmodel_path, model_input_size=[224, 224], rgb888p_size=[640, 480], debug_mode=0):
        super().__init__(kmodel_path, model_input_size, rgb888p_size, debug_mode)
        self.rgb888p_size = [ALIGN_UP(rgb888p_size[0], 16), rgb888p_size[1]]
        self.ai2d = Ai2d(debug_mode)
        self.ai2d.set_ai2d_dtype(nn.ai2d_format.NCHW_FMT, nn.ai2d_format.NCHW_FMT, np.uint8, np.uint8)

    def config_preprocess(self):
        self.ai2d.resize(nn.interp_method.tf_bilinear, nn.interp_mode.half_pixel)
        self.ai2d.build([1, 3, self.rgb888p_size[1], self.rgb888p_size[0]],
                        [1, 3, self.model_input_size[1], self.model_input_size[0]])

    def postprocess(self, results):
        mapa_np = results[0]
        mapa_2d = mapa_np[0][0] if len(mapa_np.shape) == 4 else mapa_np.reshape((224, 224))
        min_v, max_v = np.min(mapa_2d), np.max(mapa_2d)
        return np.array((mapa_2d - min_v) * (255.0 / (max_v - min_v + 1e-5)), dtype=np.uint8)

def crear_anaglifo_np(img_cam_np, mapa_np, offset_x=208, offset_y=128, size=224, max_shift=12):
    out_img = image.Image(size, size, image.RGB565)
    for y in range(size):
        y_real = y + offset_y
        for x in range(size):
            shift = (int(mapa_np[y, x]) * max_shift) // 255
            x_r = min(max(x + offset_x - shift, 0), 639)
            x_c = min(max(x + offset_x + shift, 0), 639)
            r = int(img_cam_np[0, y_real, x_r])
            g = int(img_cam_np[1, y_real, x_c])
            b = int(img_cam_np[2, y_real, x_c])
            out_img.set_pixel(x, y, (r, g, b))
    return out_img

def tomar_foto_3d(num_foto, pl, depth_app):
    print(f"\n[SISTEMA] 📸 Iniciando Toma Fotográfica {num_foto}/3...")

    # "Limpiamos" el buffer de la cámara descartando 3 frames viejos
    for _ in range(3):
        basura = pl.get_frame()
        del basura

    # Tomamos la foto fresca
    img_np = pl.get_frame()
    mapa_np = depth_app.run(img_np) # AQUÍ TRABAJA LA IA
    img_3d = crear_anaglifo_np(img_np, mapa_np, size=Config.IMG_RES, max_shift=Config.ANAGLYPH_SHIFT)

    img_comprimida = img_3d.compress(quality=Config.JPEG_QUALITY)
    image_data = bytes(img_comprimida)

    del img_np, mapa_np, img_3d, img_comprimida
    gc.collect() # <-- VITAL: Evita Memory Leaks
    print(f"[SISTEMA] ✅ Foto {num_foto} generada y RAM liberada.")
    return image_data
# ==============================================================================
# 🚀 MAIN - ORQUESTADOR PRINCIPAL
# ==============================================================================
def main():
    print("\n=== ATSIQUE CANSAT OS - INICIANDO SECUENCIA ===")

    # --- 0. INICIALIZACIÓN DE CÁMARA E IA (SE HACE SOLO UNA VEZ) ---
    print("\n[SISTEMA] Levantando Hardware de Visión Permanente...")
    pl = PipeLine(rgb888p_size=[640, 480], display_size=[640, 480])
    cam = Sensor(width=640, height=480)
    pl.create(cam)
    cam.run()

    depth_app = DepthNetApp("/sdcard/examples/kmodel/kpu_depth_model.kmodel")
    depth_app.config_preprocess()
    time.sleep(2) # Calentamiento del sensor

    # --- 1. PRIMERA FOTO (PRE-VUELO) ---
    fotos_tomadas = 1
    # Le pasamos las variables del hardware visual a la función
    image_data = tomar_foto_3d(fotos_tomadas, pl, depth_app)
    imagen_lista_para_pc = True

    # --- 2. INICIALIZACIÓN DE RADIOS ---
    print("\n[SISTEMA] Levantando Radios...")
    print("\n[SISTEMA] Levantando Radios...")
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    try: ap.config(ssid=Config.WIFI_SSID, key=Config.WIFI_PASS)
    except: pass
    time.sleep(2)

    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    servidor.bind((ap.ifconfig()[0], Config.TCP_PORT))
    servidor.listen(1)
    servidor.setblocking(False) # <-- MAGIA 1: Sockets no bloqueantes

    try:
        fpioa = FPIOA()
        fpioa.set_function(Config.STM_TX_PIN, FPIOA.UART1_TXD)
        fpioa.set_function(Config.STM_RX_PIN, FPIOA.UART1_RXD)
        fpioa.set_function(Config.LORA_TX_PIN, FPIOA.UART2_TXD)
        fpioa.set_function(Config.LORA_RX_PIN, FPIOA.UART2_RXD)

        stm  = UART(Config.STM_UART_ID,  baudrate=Config.UART_BAUD, bits=UART.EIGHTBITS, parity=UART.PARITY_NONE, stop=UART.STOPBITS_ONE)
        lora = UART(Config.LORA_UART_ID, baudrate=Config.UART_BAUD, bits=UART.EIGHTBITS, parity=UART.PARITY_NONE, stop=UART.STOPBITS_ONE, timeout=10) # <-- MAGIA 2: Timeout bajo
    except Exception as e:
        print(f"❌ Error UART: {e}")
        return

    time.sleep(0.3)
    lora.write(b"AT+ADDRESS=1\r\n")
    time.sleep(0.3)
    lora.write(b"AT+PARAMETER=7,7,1,12\r\n")

    # --- 3. ESTADOS DEL ORQUESTADOR ---
    print("\n🚀 [ORQUESTADOR] VUELO INICIADO - Bucle Principal Activo")

    seq = 0
    ultima_trama_csv = "$CS,0,0,0,0,0,0,0,0"  # Memoria compartida de la telemetría

    ultimo_tiempo_foto = time.ticks_ms()
    ultimo_tiempo_lora = time.ticks_ms()

    # ==========================================================================
    # 🔄 SUPER LOOP (AQUÍ OCURRE LA MAGIA DEL MULTITASKING)
    # ==========================================================================
    while True:
        try:
            # -----------------------------------------------------------
            # TAREA 1: ESCUCHAR STM32 (Alimentar la memoria)
            # -----------------------------------------------------------
            if stm.any() > 0:
                datos_crudos = stm.read()
                if datos_crudos:
                    try:
                        lineas = datos_crudos.decode('utf-8', 'ignore').strip().split('\n')
                        for linea in lineas:
                            mensaje = linea.strip()
                            if "STATE" in mensaje and "TEMP" in mensaje and "ALT" in mensaje:
                                #print(f"📥 [STM] {mensaje}") # Descomentar para ver TODO lo que entra

                                campos = {}
                                for parte in mensaje.split("|"):
                                    parte = parte.strip()
                                    if ":" in parte:
                                        clave, _, valor = parte.partition(":")
                                        campos[clave.strip()] = valor.strip()

                                gps_val = campos.get('GPS','?')[:40]
                                # ACÁ ACTUALIZAMOS LA VARIABLE GLOBAL (Sin transmitir aún)
                                ultima_trama_csv = f"$CS,{seq},{campos.get('STATE','?')},{campos.get('TEMP','?')},{campos.get('P','?')},{campos.get('ALT','?')},{campos.get('ACC','?')},{campos.get('GYR','?')},{gps_val}"
                    except Exception:
                        pass

            # -----------------------------------------------------------
            # TAREA 2: TRANSMITIR POR LORA (Cronometrado a 1Hz)
            # -----------------------------------------------------------
            if time.ticks_diff(time.ticks_ms(), ultimo_tiempo_lora) > Config.INTERVALO_LORA_MS:
                seq += 1
                payload = ultima_trama_csv.encode()
                if len(payload) > 250: payload = payload[:250]

                print(f"📡 [LORA TX] {ultima_trama_csv}")
                lora.write(b"AT+SEND=0," + str(len(payload)).encode() + b"," + payload + b"\r\n")

                ultimo_tiempo_lora = time.ticks_ms() # Resetear cronómetro LoRa

            # -----------------------------------------------------------
            # TAREA 3: TOMAR FOTOS (Cronometrado a 2 Minutos)
            # -----------------------------------------------------------
            if fotos_tomadas < Config.MAX_FOTOS:
                if time.ticks_diff(time.ticks_ms(), ultimo_tiempo_foto) > Config.INTERVALO_FOTOS_MS:
                    fotos_tomadas += 1
                    image_data = tomar_foto_3d(fotos_tomadas, pl, depth_app) # Esto pausará el bucle unos 3 segundos
                    imagen_lista_para_pc = True
                    ultimo_tiempo_foto = time.ticks_ms() # Resetear cronómetro Fotos

            # -----------------------------------------------------------
            # TAREA 4: ATENDER PC VÍA WI-FI (Completamente No Bloqueante)
            # -----------------------------------------------------------
            try:
                conn, addr = servidor.accept() # Intenta aceptar
                if imagen_lista_para_pc:
                    print(f"🌐 [WIFI] PC Conectado. Enviando Foto {fotos_tomadas}...")
                    conn.settimeout(3.0)
                    conn.send(image_data)
                    conn.close()
                    imagen_lista_para_pc = False # Ya se la entregó, cerramos grifo
                    print("[WIFI] ✅ Descarga Completada.")
                else:
                    conn.close() # Cierra la puerta amablemente para no bloquearse
            except OSError:
                # El error EWOULDBLOCK (11) es normal, significa "Nadie se está conectando". Lo ignoramos.
                pass

            # -----------------------------------------------------------
            # RESPIRAR (Yield al Sistema Operativo RT-Smart)
            # -----------------------------------------------------------
            time.sleep_ms(15)

        except Exception as e:
            print(f"⚠️ Alerta Orquestador: {e}")
            time.sleep_ms(50)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSISTEMA DETENIDO.")
        try: MediaManager.deinit()
        except: pass
