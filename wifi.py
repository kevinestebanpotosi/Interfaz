import socket
import time
import serial
import threading
from datetime import datetime

# ==========================================
# CONFIGURACIÓN DE LA ESTACIÓN TERRENA
# ==========================================
# --- Wi-Fi ---
HOST = "192.168.169.1" 
PORT = 5000

# --- LoRa (Serial) ---
LORA_PORT = "COM7"
LORA_BAUD = 115200

# ==========================================
# TAREA 1: ESCUCHAR LORA (Telemetría)
# ==========================================
def escuchar_lora():
    print(f"📡 [LORA] Intentando abrir el puerto {LORA_PORT}...")
    try:
        # Abrimos el puerto serial
        with serial.Serial(LORA_PORT, LORA_BAUD, timeout=1) as ser:
            print(f"✅ [LORA] ¡Conectado al receptor en {LORA_PORT}! Escuchando...")
            
            while True:
                # Si hay datos esperando en el puerto USB
                if ser.in_waiting > 0:
                    try:
                        # Leemos la línea, la decodificamos y le quitamos espacios extra
                        linea = ser.readline().decode('utf-8', 'ignore').strip()
                        
                        if linea:
                            # Le ponemos la hora exacta de la PC
                            hora_actual = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                            print(f"🛰️ [{hora_actual} LORA] {linea}")
                            
                            # Guardamos la telemetría en un archivo CSV para analizarla después del vuelo
                            with open("telemetria_vuelo.csv", "a") as f:
                                f.write(f"{hora_actual},{linea}\n")
                    except Exception as e:
                        print(f"⚠️ [LORA] Error leyendo línea: {e}")
                        
    except Exception as e:
        print(f"❌ [LORA] FATAL: No se pudo abrir {LORA_PORT}. ¿Está conectado el módulo? Error: {e}")


# ==========================================
# ==========================================
# TAREA 2: ESCUCHAR WIFI (Descarga de Fotos)
# ==========================================
def escuchar_wifi():
    captura_id = 0
    print(f"🌐 [WIFI] Buscando conexión con el CanSat en {HOST}:{PORT}...")
    
    while True:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10.0) 
                s.connect((HOST, PORT))
                
                img_data = bytearray()
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        break # Se terminó de enviar
                    img_data.extend(chunk)
                
                # Si recibimos datos, guardamos la imagen
                if len(img_data) > 0:
                    captura_id += 1
                    filename = f"anaglifo_captura_{captura_id}.jpg"
                    
                    with open(filename, "wb") as f:
                        f.write(img_data)
                    
                    print(f"📸 [WIFI] ¡Éxito! Foto {captura_id} guardada como '{filename}' ({len(img_data)} bytes)\n")
                    
                    # 👇 FIX IMPORTANTE: Le damos un respiro al satélite antes de volver a preguntar
                    time.sleep(5) 
                else:
                    # La conexión se hizo, pero el satélite no mandó foto (porque ya mandó la última)
                    time.sleep(2)

        # Manejamos errores si el satélite aún no crea la red
        except (ConnectionRefusedError, TimeoutError, socket.timeout):
            time.sleep(2)
            
        except Exception as e:
            print(f"❌ [WIFI] Error inesperado durante la descarga: {e}")
            time.sleep(2)

# ==========================================
# EJECUCIÓN PRINCIPAL (ORQUESTADOR)
# ==========================================
if __name__ == "__main__":
    print("=== ESTACIÓN TERRENA ATSIQUE INICIADA ===")
    
    # 1. Creamos un archivo CSV limpio con los encabezados si no existe
    with open("telemetria_vuelo.csv", "a") as f:
        f.write("HORA_PC,DATOS_LORA\n")
    
    # 2. Iniciamos el proceso de LoRa en un "Hilo" (Thread) secundario que corre en el fondo
    hilo_lora = threading.Thread(target=escuchar_lora, daemon=True)
    hilo_lora.start()
    
    # 3. Usamos el proceso principal para escuchar el Wi-Fi continuamente
    try:
        escuchar_wifi()
    except KeyboardInterrupt:
        print("\n🏁 Misión abortada manualmente por el usuario. Cerrando estación terrena.")