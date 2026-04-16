# ==============================================================================
#  ATSIQUE CanSat — ESTACIÓN EN TIERRA
#  Receptor de Telemetría + Imagen vía LoRa
#
#  Arquitectura:
#    SerialTelemetryReceiver corre en un hilo de fondo y deposita eventos
#    en una queue.Queue que la UI (o el script principal) consume.
#
#    Tipos de eventos emitidos:
#      "status"    → mensaje informativo del receptor
#      "raw"       → línea cruda recibida por UART (útil para debug)
#      "telemetry" → diccionario con los campos del CSV + vel_mps calculada
#      "image"     → imagen JPEG ensamblada (completa o parcial si hubo pérdida)
#      "warn"      → advertencia no fatal (CRC, chunk duplicado, etc.)
#      "error"     → error fatal que detuvo el hilo receptor
#      "stats"     → estadísticas de imagen al finalizar una transferencia
# ==============================================================================

import time
import threading
import queue
import base64
import struct
import os
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Set

import serial


# ==============================================================================
#  SECCIÓN A — PARÁMETROS CONFIGURABLES
#  ⚠️  Los parámetros marcados con [SYNC] DEBEN coincidir exactamente con los
#      valores en el código del satélite (vuelo_cansat.py), de lo contrario
#      el enlace no funcionará o los datos llegarán corruptos.
# ==============================================================================

# ── A1. Parámetros de radio LoRa  [SYNC con satélite] ─────────────────────────

# Dirección LoRa de esta estación en tierra
# Debe ser el valor de GROUND_ADDR en el satélite (default: 0)
GROUND_ADDR   = 0

# Dirección LoRa del satélite
# Debe ser el valor de SATELLITE_ADDR en el satélite (default: 1)
SATELLITE_ADDR = 1

# Spreading Factor. Valores: 7 (rápido, ~500m) … 12 (lento, ~5km)
# [SYNC] Debe ser igual que LORA_SF en el satélite
LORA_SF = 7

# Bandwidth index, Coding Rate, Preamble
# [SYNC] Deben coincidir con el segundo, tercer y cuarto parámetro de
#        AT+PARAMETER en el satélite: AT+PARAMETER={SF},{BW},{CR},{PREAMBLE}
LORA_BW       = 7   # 7 = 125 kHz  (opciones: 7=125k, 8=250k, 9=500k)
LORA_CR       = 1   # 1 = 4/5      (opciones: 1=4/5, 2=4/6, 3=4/7, 4=4/8)
LORA_PREAMBLE = 12  # símbolos de preámbulo (8–12 recomendado)

# ── A2. Parámetros de protocolo de imagen  [SYNC con satélite] ────────────────

# Tamaño máximo de payload por chunk, en bytes (antes de codificación base64)
# [SYNC] Debe ser igual que MAX_PAYLOAD_BYTES en el satélite
CHUNK_SIZE_BYTES = 100

# Número de vueltas de transmisión de la imagen que envía el satélite
# [SYNC] Debe ser igual que MAX_VUELTAS_IMAGEN en el satélite
# El receptor espera hasta este número de vueltas antes de dar la imagen por
# terminada, lo que permite recuperar chunks perdidos en la primera vuelta.
TOTAL_VUELTAS_ESPERADAS = 3

# Bytes mágicos de sincronía que marcan el inicio de un frame de imagen
# [SYNC] Deben coincidir con el valor en send_image_chunk() del satélite
FRAME_MAGIC = b"\xAA\x55"

# ── A3. Parámetros de telemetría  [SYNC con satélite] ─────────────────────────

# Cabeceras del CSV en el orden exacto que los envía get_telemetry_data()
# [SYNC] Si cambias el formato CSV del satélite, actualiza esta lista.
TELEMETRY_HEADERS = [
    "pkt_id",       # Número de paquete (entero, incrementa siempre)
    "ax",           # Acelerómetro X (g)
    "ay",           # Acelerómetro Y (g)
    "az",           # Acelerómetro Z (g)
    "gx",           # Giroscopio X (°/s)
    "gy",           # Giroscopio Y (°/s)
    "gz",           # Giroscopio Z (°/s)
    "temperatura",  # Temperatura ambiente (°C)
    "presion_hpa",  # Presión barométrica (hPa)
    "humedad",      # Humedad relativa (%)
    "lat",          # Latitud GPS (°)
    "lon",          # Longitud GPS (°)
    "roll",         # Ángulo de alabeo (°)
    "pitch",        # Ángulo de cabeceo (°)
    "altitud",      # Altitud barométrica (m)
    "estado_paracaidas",  # 1=OK, 0=Error
    "estado_baterias",    # 1=OK, 0=Error
    "timestamp_ms", # Tiempo del sistema en el satélite (ms)
]

# ── A4. Parámetros de comportamiento del receptor ─────────────────────────────

# Si True, envía ACK al satélite por cada paquete de telemetría recibido
SEND_ACK = True

# Segundos sin recibir ningún chunk antes de abortar la imagen en curso
# y emitir lo que se tenga. Poner a 0 para desactivar el timeout.
IMAGEN_TIMEOUT_S = 60.0

# Intervalo mínimo entre previews de imagen parcial (segundos)
# Subir este valor si la UI se satura de actualizaciones parciales
PREVIEW_INTERVAL_S = 3.0

# Directorio donde se guardan las imágenes recibidas (relativo al script)
OUTPUT_DIR = "capturas"

# Si True, guarda también las imágenes parciales (con chunks faltantes)
GUARDAR_IMAGEN_PARCIAL = True


# ==============================================================================
#  SECCIÓN B — ESTRUCTURAS DE DATOS
# ==============================================================================

@dataclass(frozen=True)
class TelemetryEvent:
    """
    Unidad de comunicación entre el hilo receptor y la UI/script principal.

    Campos:
        kind      → tipo de evento (ver lista en encabezado del módulo)
        message   → texto legible (para status, warn, error, y nombre de archivo en image)
        raw       → línea UART original sin procesar
        telemetry → dict con campos de telemetría o {"image_bytes": bytes} para imágenes
        ts        → timestamp Unix del momento en que se generó el evento
    """
    kind:      str
    message:   str                    = ""
    raw:       str                    = ""
    telemetry: Optional[Dict[str, Any]] = None
    ts:        float                  = 0.0


@dataclass
class _ImageSession:
    """
    Estado interno de una sesión de recepción de imagen.
    Se reinicia con cada nuevo paquete de metadata (pkt_num == 0).
    """
    total_chunks:    int                  # Total de chunks esperados (sin contar el header)
    received:        Dict[int, bytes]     = field(default_factory=dict)   # chunk_num → bytes
    vueltas_vistas:  int                  = 0    # Cuántas vueltas completas se han observado
    last_chunk_ts:   float                = field(default_factory=time.time)
    ultimo_preview:  float                = 0.0  # timestamp del último preview emitido
    session_dir:      Optional[str]       = None  # carpeta donde se guardan los chunks en disco

    @property
    def chunks_faltantes(self) -> Set[int]:
        """Chunks del 1..total que aún no han llegado."""
        return set(range(1, self.total_chunks + 1)) - set(self.received.keys())

    @property
    def porcentaje(self) -> float:
        return 100.0 * len(self.received) / self.total_chunks if self.total_chunks else 0.0

    @property
    def completa(self) -> bool:
        return len(self.chunks_faltantes) == 0


# ==============================================================================
#  SECCIÓN C — FUNCIONES DE SOPORTE DE PROTOCOLO
# ==============================================================================

def parse_rcv(line: str) -> Optional[str]:
    """
    Extrae el payload de una línea con formato LoRa:
        +RCV=<addr>,<len>,<data>,<rssi>,<snr>

    Returns:
        El campo <data> como string, o None si la línea no tiene el formato esperado.
    """
    if not line.startswith("+RCV="):
        return None
    try:
        inner = line[5:]
        # addr y len están antes de la primera coma doble; data termina antes de ,rssi,snr
        parts = inner.split(",", 2)
        if len(parts) < 3:
            return None
        # Quitar ,rssi,snr del final (los últimos dos tokens separados por coma)
        tokens = parts[2].rsplit(",", 2)
        if len(tokens) < 3:
            return None
        return tokens[0]
    except Exception:
        return None


def parse_telemetry(payload: str) -> Optional[Dict[str, str]]:
    """
    Parsea un payload CSV de telemetría.

    Valida que el número de campos coincida exactamente con TELEMETRY_HEADERS
    antes de retornar el diccionario, para evitar falsos positivos.
    """
    fields = payload.split(",")
    if len(fields) != len(TELEMETRY_HEADERS):
        return None
    return dict(zip(TELEMETRY_HEADERS, fields))


def es_probable_imagen(payload: str) -> bool:
    """
    Heurística para evitar intentar decodificar base64 en payloads CSV o
    respuestas AT del módulo LoRa.

    Un payload de telemetría tiene exactamente len(TELEMETRY_HEADERS)-1 comas.
    Un payload base64 tiene muy pocas comas (o ninguna) y solo caracteres
    del alfabeto base64: A-Z, a-z, 0-9, +, /, =

    Casos que se excluyen explícitamente:
      - Respuestas AT del módulo LoRa: +OK, +ERR, +READY, AT+...
      - Strings demasiado cortos para ser un frame de imagen válido
        (el frame mínimo serializado tiene 9 bytes → 12 chars en base64)
    """
    s = payload.strip()

    # Excluir respuestas AT y comandos AT explícitamente
    if s.startswith("+OK") or s.startswith("+ERR") or s.startswith("+READY"):
        return False
    if s.startswith("AT+") or s.startswith("AT "):
        return False

    # Demasiado corto para ser un frame válido (magic+header+crc = 9 bytes → 12 chars b64)
    if len(s) < 12:
        return False

    expected_commas = len(TELEMETRY_HEADERS) - 1
    actual_commas   = s.count(",")

    # Si tiene el número exacto de comas de telemetría, NO es imagen
    if actual_commas == expected_commas:
        return False

    # Si tiene muchas comas pero no el número correcto, es un CSV malformado
    if actual_commas > 5:
        return False

    # Verificar que solo contiene caracteres base64 válidos
    import re
    if not re.fullmatch(r"[A-Za-z0-9+/=\r\n]+", s):
        return False

    # Verificar que la longitud es compatible con base64 válido
    # (longitud debe ser múltiplo de 4, o rellenable con = hasta serlo)
    b64_clean = s.replace("\r", "").replace("\n", "")
    padding_needed = (4 - len(b64_clean) % 4) % 4
    if padding_needed > 2:
        # Base64 con 3 chars de padding nunca es válido
        return False

    return True


def _to_float(x: Optional[str]) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except (ValueError, TypeError):
        return None


def _to_int(x: Optional[str]) -> Optional[int]:
    if x is None:
        return None
    try:
        return int(float(x))
    except (ValueError, TypeError):
        return None


def crc16(data: bytes) -> int:
    """
    CRC-16/ARC.
    [SYNC] El polinomio (0xA001) debe ser idéntico al usado en el satélite.
    """
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def jpeg_valido(data: bytes) -> bool:
    """Verifica que los bytes comiencen y terminen con las marcas SOI/EOI de JPEG."""
    return (len(data) > 4
            and data[:2] == b"\xff\xd8"   # SOI — Start Of Image
            and data[-2:] == b"\xff\xd9") # EOI — End Of Image


# ==============================================================================
#  SECCIÓN D — RECEPTOR PRINCIPAL
# ==============================================================================

class SerialTelemetryReceiver:
    """
    Receptor de telemetría e imagen CanSat por LoRa sobre puerto serie.

    Uso básico:
        events = queue.Queue()
        rx = SerialTelemetryReceiver(events)
        rx.start("/dev/ttyUSB0", 115200)

        while True:
            ev = events.get()
            if ev.kind == "telemetry":
                print(ev.telemetry)
            elif ev.kind == "image":
                with open(ev.message, "wb") as f:
                    f.write(ev.telemetry["image_bytes"])
    """

    def __init__(
        self,
        events: "queue.Queue[TelemetryEvent]",
        *,
        sat_addr:         int   = SATELLITE_ADDR,
        send_ack:         bool  = SEND_ACK,
        serial_timeout_s: float = 1.0,
    ):
        self._events          = events
        self._send_ack        = send_ack
        self._satellite_addr  = sat_addr
        self._serial_timeout  = serial_timeout_s

        self._thread: Optional[threading.Thread] = None
        self._stop   = threading.Event()
        self._lock   = threading.Lock()  # Protege _session y _last_*
        self._ser:    Optional[serial.Serial] = None

        # Estado de telemetría (para calcular velocidad vertical)
        self._last_alt_m:   Optional[float] = None
        self._last_tick_ms: Optional[int]   = None

        # Sesión de imagen en curso (None si no hay imagen esperada)
        self._session: Optional[_ImageSession] = None

        os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ── Interfaz pública ───────────────────────────────────────────────────────

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, port: str, baudrate: int) -> None:
        """Inicia el hilo receptor. No hace nada si ya está corriendo."""
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, args=(port, baudrate), daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Detiene el hilo receptor de forma ordenada."""
        self._stop.set()
        try:
            if self._ser is not None:
                self._ser.close()
        except Exception:
            pass

    # ── Hilo principal ─────────────────────────────────────────────────────────

    def _emit(self, ev: TelemetryEvent) -> None:
        try:
            self._events.put_nowait(ev)
        except queue.Full:
            pass  # Si la cola está llena, descartar el evento antes que bloquear

    def _run(self, port: str, baudrate: int) -> None:
        self._emit(TelemetryEvent(kind="status", message=f"Conectando a {port} @ {baudrate}bps...", ts=time.time()))
        try:
            self._ser = serial.Serial(port, baudrate, timeout=self._serial_timeout)
            # Configurar el módulo LoRa de la estación tierra
            self._ser.write(f"AT+ADDRESS={GROUND_ADDR}\r\n".encode())
            time.sleep(0.3)
            self._ser.write(f"AT+PARAMETER={LORA_SF},{LORA_BW},{LORA_CR},{LORA_PREAMBLE}\r\n".encode())
            time.sleep(0.5)
            self._emit(TelemetryEvent(
                kind="status",
                message=f"✅ Estación tierra lista — SF{LORA_SF} BW{LORA_BW} CR4/{LORA_CR+4} Preamble{LORA_PREAMBLE}",
                ts=time.time()
            ))
        except Exception as e:
            self._emit(TelemetryEvent(kind="error", message=f"❌ No se pudo abrir {port}: {e}", ts=time.time()))
            return

        while not self._stop.is_set():
            try:
                self._verificar_timeout_imagen()

                if self._ser.in_waiting > 0:
                    raw = self._ser.readline().decode("utf-8", "ignore").strip()
                    if not raw:
                        continue
                    self._emit(TelemetryEvent(kind="raw", raw=raw, ts=time.time()))
                    self._procesar_linea(raw)

            except serial.SerialException as e:
                self._emit(TelemetryEvent(kind="error", message=f"❌ Error serial: {e}", ts=time.time()))
                break
            except Exception as e:
                self._emit(TelemetryEvent(kind="warn", message=f"⚠️ Error en bucle: {e}", ts=time.time()))

    # ── Despacho de líneas recibidas ───────────────────────────────────────────

    def _procesar_linea(self, raw: str) -> None:
        """
        Determina si la línea es un frame de imagen o telemetría CSV y la despacha.

        Orden de decisión:
          1. Extraer payload de la envoltura LoRa (+RCV=...) si existe.
          2. Si el payload parece base64 → intentar decodificar como imagen.
          3. Si tiene el número correcto de comas → parsear como telemetría.
          4. Si no encaja en ninguno → emitir warn con el raw para diagnóstico.
        """
        payload = parse_rcv(raw) or raw

        if es_probable_imagen(payload):
            self._intentar_procesar_imagen(payload)
        else:
            data = parse_telemetry(payload)
            if data:
                self._procesar_telemetria(data)
            else:
                # Puede ser +OK, +ERR u otra respuesta AT — no es un error real
                if not payload.startswith("+") and not payload.startswith("AT"):
                    self._emit(TelemetryEvent(
                        kind="warn",
                        message=f"Línea no reconocida: {payload[:80]}",
                        ts=time.time()
                    ))

    # ── Procesado de imagen ────────────────────────────────────────────────────

    def _intentar_procesar_imagen(self, payload: str) -> None:
        """Decodifica base64, valida CRC y despacha el chunk al ensamblador."""
        try:
            clean = payload.strip().replace(" ", "").replace("\n", "").replace("\r", "")
            # Añadir padding si falta (algunos módulos LoRa truncan el '=' final)
            padding = (4 - len(clean) % 4) % 4
            if padding:
                clean += "=" * padding
            frame = base64.b64decode(clean)
        except Exception as e:
            self._emit(TelemetryEvent(kind="warn", message=f"Base64 inválido: {e} — payload: {payload[:40]!r}", ts=time.time()))
            return

        if not frame.startswith(FRAME_MAGIC):
            # Datos binarios válidos pero sin marca de sincronía: ignorar silenciosamente
            return

        try:
            # Estructura del header: [Magic:2][pkt_num:2][total_pkts:2][dlen:1]
            pkt_num, total_pkts, dlen = struct.unpack(">HHB", frame[2:7])
            payload_bytes = frame[7: 7 + dlen]
            crc_offset    = 7 + dlen
            recv_crc      = struct.unpack(">H", frame[crc_offset: crc_offset + 2])[0]
        except struct.error as e:
            self._emit(TelemetryEvent(kind="warn", message=f"Header de imagen truncado: {e}", ts=time.time()))
            return

        if crc16(frame[:crc_offset]) != recv_crc:
            self._emit(TelemetryEvent(
                kind="warn",
                message=f"CRC incorrecto en chunk {pkt_num} — descartado",
                ts=time.time()
            ))
            return

        self._procesar_chunk_validado(pkt_num, total_pkts, payload_bytes)

    def _procesar_chunk_validado(self, pkt_num: int, total_pkts: int, payload: bytes) -> None:
        """Gestiona la sesión de imagen y almacena el chunk recibido."""
        with self._lock:
            n_chunks = total_pkts - 1  # total_pkts incluye el paquete 0 de metadata

            if pkt_num == 0:
                # ── Paquete de metadata (inicio de vuelta) ──────────────────────
                if self._session is not None and self._session.total_chunks == n_chunks:
                    # Segunda (o posterior) vuelta de la misma imagen:
                    # NO crear sesión nueva — mantener la existente para acumular
                    # los chunks que faltaron en la vuelta anterior.
                    self._session.vueltas_vistas += 1
                    faltantes_antes = len(self._session.chunks_faltantes)
                    print(f"🔄 Vuelta {self._session.vueltas_vistas + 1} detectada "
                          f"({faltantes_antes} chunks faltantes, esperando recuperarlos)")
                else:
                    # Sesión nueva o imagen diferente
                    if self._session is not None and not self._session.completa:
                        faltaban = len(self._session.chunks_faltantes)
                        self._emit(TelemetryEvent(
                            kind="warn",
                            message=f"Nueva imagen recibida con sesión anterior incompleta "
                                    f"({faltaban} chunks perdidos). Ensamblando lo disponible.",
                            ts=time.time()
                        ))
                        # Ensamblar la sesión anterior antes de descartarla
                        self._ensamblar_y_emitir(final=True)

                    session_dir = os.path.join(OUTPUT_DIR, f"session_{int(time.time())}")
                    os.makedirs(session_dir, exist_ok=True)
                    self._session = _ImageSession(total_chunks=n_chunks, session_dir=session_dir)
                    print(f"📦 Nueva sesión de imagen: {n_chunks} chunks esperados — "
                          f"carpeta: {session_dir}")
                return

            # ── Chunk de datos ────────────────────────────────────────────────
            if self._session is None:
                self._emit(TelemetryEvent(
                    kind="warn",
                    message=f"Chunk {pkt_num} recibido sin sesión activa (paquete 0 perdido). "
                            f"Creando sesión implícita con {n_chunks} chunks.",
                    ts=time.time()
                ))
                session_dir = os.path.join(OUTPUT_DIR, f"session_{int(time.time())}")
                os.makedirs(session_dir, exist_ok=True)
                self._session = _ImageSession(total_chunks=n_chunks, session_dir=session_dir)

            session = self._session
            session.last_chunk_ts = time.time()

            # Solo almacenar si no lo teníamos aún (no sobreescribir con duplicados)
            es_nuevo = pkt_num not in session.received
            if es_nuevo:
                session.received[pkt_num] = payload
                # Guardar chunk en disco inmediatamente
                try:
                    if session.session_dir:
                        chunk_path = os.path.join(session.session_dir, f"chunk_{pkt_num:04d}.bin")
                        with open(chunk_path, "wb") as cf:
                            cf.write(payload)
                except Exception as e:
                    self._emit(TelemetryEvent(
                        kind="warn",
                        message=f"No se pudo guardar chunk {pkt_num} en disco: {e}",
                        ts=time.time()
                    ))
                faltantes_ahora = len(session.chunks_faltantes)
                print(f"📥 Chunk {pkt_num}/{session.total_chunks} — "
                      f"{session.porcentaje:.0f}% ({faltantes_ahora} faltantes)")
            # Los duplicados son silenciosos

            # Si está completa, ensamblar y cerrar sesión
            if session.completa:
                print(f"✅ Imagen completa ({session.total_chunks}/{session.total_chunks} chunks)")
                self._ensamblar_y_emitir(final=True)
                self._session = None
                return

            # Si ya pasamos por todas las vueltas esperadas y aún faltan chunks,
            # ensamblar con lo disponible al detectar fin de transmisión por timeout
            if (session.vueltas_vistas >= TOTAL_VUELTAS_ESPERADAS - 1
                    and pkt_num == session.total_chunks):
                faltantes = session.chunks_faltantes
                if faltantes:
                    print(f"⚠️  Última vuelta completada con {len(faltantes)} chunks perdidos: "
                          f"{sorted(faltantes)}. Ensamblando imagen parcial...")
                    self._ensamblar_y_emitir(final=True)
                    self._session = None

    def _ensamblar_y_emitir(self, final: bool) -> None:
        """
        Ensambla los chunks recibidos en un buffer JPEG y emite el evento.

        Estrategia para chunks faltantes:
          - Omitir chunks faltantes en todos los casos.
          - Rellenar con ceros SOLO el último chunk si es el único faltante
            y el JPEG tiene cabecera válida (para no cortar el stream bruscamente).
          - Rellenar con datos del chunk previo introduce basura binaria que
            corrompe el JPEG; mejor omitir y dejar que el decodificador tolere
            el truncado (PIL/Pillow lo acepta en modo 'truncated').
        """
        session = self._session
        if session is None or not session.received:
            return

        faltantes    = session.chunks_faltantes
        n_recibidos  = len(session.received)

        # Ensamblar solo los chunks que realmente llegaron, en orden
        buffer = bytearray()
        for i in range(1, session.total_chunks + 1):
            chunk = None
            # Preferir disco (más fiable que RAM para sesiones largas)
            if session.session_dir:
                path = os.path.join(session.session_dir, f"chunk_{i:04d}.bin")
                if os.path.exists(path):
                    try:
                        with open(path, "rb") as cf:
                            chunk = cf.read()
                    except Exception:
                        chunk = None

            if chunk is None and i in session.received:
                chunk = session.received[i]

            if chunk is not None:
                buffer.extend(chunk)
            # Si falta: omitir — no rellenar con basura

        image_data = bytes(buffer)

        # Validar cabecera JPEG mínima
        if len(image_data) < 4 or image_data[:2] != b"\xff\xd8":
            self._emit(TelemetryEvent(
                kind="warn",
                message=(f"Buffer ensamblado no empieza con SOI JPEG "
                         f"(chunk 1 perdido o corrupto). "
                         f"Recibidos: {n_recibidos}/{session.total_chunks}"),
                ts=time.time()
            ))
            if final:
                return

        # Añadir marcador EOI si el JPEG está truncado (falta el último chunk)
        # Esto permite que PIL abra la imagen aunque esté incompleta
        if image_data and image_data[:2] == b"\xff\xd8" and image_data[-2:] != b"\xff\xd9":
            image_data = image_data + b"\xff\xd9"

        # Construir nombre de archivo
        sufijo = ("completa" if final and not faltantes
                  else f"parcial_{n_recibidos}de{session.total_chunks}")
        nombre_archivo = os.path.join(OUTPUT_DIR,
                                      f"captura_{int(time.time())}_{sufijo}.jpg")

        # Emitir evento de imagen
        self._emit(TelemetryEvent(
            kind="image",
            message=nombre_archivo,
            telemetry={
                "image_bytes":       image_data,
                "chunks_recibidos":  n_recibidos,
                "chunks_total":      session.total_chunks,
                "chunks_faltantes":  sorted(faltantes),
                "completa":          len(faltantes) == 0,
            },
            ts=time.time()
        ))

        # Guardar en disco
        if final or GUARDAR_IMAGEN_PARCIAL:
            try:
                with open(nombre_archivo, "wb") as f:
                    f.write(image_data)

                self._emit(TelemetryEvent(
                    kind="stats",
                    message=(
                        f"{'✅' if not faltantes else '⚠️'} Imagen guardada: {nombre_archivo} | "
                        f"{n_recibidos}/{session.total_chunks} chunks "
                        f"({session.porcentaje:.1f}%) | "
                        f"{'COMPLETA' if not faltantes else f'{len(faltantes)} perdidos: {sorted(faltantes)[:10]}'}"
                    ),
                    ts=time.time()
                ))
            except OSError as e:
                self._emit(TelemetryEvent(
                    kind="warn",
                    message=f"No se pudo guardar {nombre_archivo}: {e}",
                    ts=time.time()
                ))

    def _verificar_timeout_imagen(self) -> None:
        """
        Comprueba si la sesión de imagen lleva demasiado tiempo sin recibir chunks.
        Si supera IMAGEN_TIMEOUT_S, emite lo que haya y cierra la sesión.
        """
        if IMAGEN_TIMEOUT_S <= 0:
            return
        with self._lock:
            if self._session is None:
                return
            elapsed = time.time() - self._session.last_chunk_ts
            if elapsed >= IMAGEN_TIMEOUT_S:
                n = len(self._session.received)
                self._emit(TelemetryEvent(
                    kind="warn",
                    message=f"Timeout de imagen ({elapsed:.0f}s sin chunks). Ensamblando {n}/{self._session.total_chunks} chunks disponibles.",
                    ts=time.time()
                ))
                self._ensamblar_y_emitir(final=True)
                self._session = None

    # ── Procesado de telemetría ────────────────────────────────────────────────

    def _procesar_telemetria(self, data: Dict[str, str]) -> None:
        """
        Enriquece los datos de telemetría con velocidad vertical calculada
        y emite el evento. También envía ACK al satélite.
        """
        alt_m    = _to_float(data.get("altitud"))
        tick_ms  = _to_int(data.get("timestamp_ms"))

        with self._lock:
            if all(v is not None for v in [alt_m, tick_ms, self._last_alt_m, self._last_tick_ms]):
                dt_s = (tick_ms - self._last_tick_ms) / 1000.0
                if dt_s > 0:
                    vel = (alt_m - self._last_alt_m) / dt_s
                    data["vel_mps"] = f"{vel:.2f}"
            self._last_alt_m  = alt_m
            self._last_tick_ms = tick_ms

        self._emit(TelemetryEvent(kind="telemetry", telemetry=dict(data), ts=time.time()))
        self._enviar_ack(data.get("pkt_id", "0"))

    def _enviar_ack(self, pkt_id: str) -> None:
        """
        Envía confirmación al satélite: AT+SEND={SATELLITE_ADDR},len,ACK,{pkt_id}
        Solo funciona si SEND_ACK=True y el puerto serial está abierto.
        """
        if not self._send_ack or self._ser is None:
            return
        try:
            payload = f"ACK,{pkt_id}"
            cmd     = f"AT+SEND={self._satellite_addr},{len(payload)},{payload}\r\n"
            self._ser.write(cmd.encode())
        except Exception as e:
            self._emit(TelemetryEvent(kind="warn", message=f"No se pudo enviar ACK: {e}", ts=time.time()))


# ==============================================================================
#  SECCIÓN E — SCRIPT DE PRUEBA (ejecutar directamente para verificar)
# ==============================================================================

if __name__ == "__main__":
    import sys

    port     = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
    baudrate = int(sys.argv[2]) if len(sys.argv) > 2 else 115200

    print(f"=== Estación Tierra CanSat ===")
    print(f"Puerto: {port} @ {baudrate}bps")
    print(f"SF{LORA_SF} | BW={LORA_BW} | CR=4/{LORA_CR+4} | Preamble={LORA_PREAMBLE}")
    print(f"Imágenes → {os.path.abspath(OUTPUT_DIR)}")
    print("Ctrl+C para detener\n")

    events = queue.Queue()
    rx     = SerialTelemetryReceiver(events)
    rx.start(port, baudrate)

    try:
        while True:
            try:
                ev = events.get(timeout=1.0)
            except queue.Empty:
                continue

            if ev.kind == "status":
                print(f"[STATUS] {ev.message}")

            elif ev.kind == "raw":
                print(f"[RAW]    {ev.raw}")

            elif ev.kind == "telemetry":
                t = ev.telemetry
                alt  = t.get("altitud", "?")
                temp = t.get("temperatura", "?")
                vel  = t.get("vel_mps", "—")
                pkt  = t.get("pkt_id", "?")
                print(f"[TEL]    pkt={pkt:>4} | Alt={alt}m | Temp={temp}°C | Vel={vel}m/s")

            elif ev.kind == "image":
                meta = ev.telemetry or {}
                ok   = meta.get("completa", False)
                pct  = 100.0 * meta.get("chunks_recibidos", 0) / max(meta.get("chunks_total", 1), 1)
                print(f"[IMG]    {'✅' if ok else '⚠️'} {ev.message} ({pct:.0f}% recibido)")

            elif ev.kind == "stats":
                print(f"[STATS]  {ev.message}")

            elif ev.kind == "warn":
                print(f"[WARN]   {ev.message}")

            elif ev.kind == "error":
                print(f"[ERROR]  {ev.message}")
                break

    except KeyboardInterrupt:
        print("\nDeteniendo receptor...")
        rx.stop()