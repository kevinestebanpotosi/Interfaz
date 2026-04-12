import time
import threading
import queue
from dataclasses import dataclass
from typing import Optional, Dict, Any, Callable

import serial
import base64
import struct
import os

# --- CONFIGURACIÓN DE PROTOCOLO ---
HEADERS = [
    "pkt_id", "ax_f", "ay_f", "az_f", "gx", "gy", "gz",
    "temperature", "pressure_hpa", "sensor_id", "lat", "lon",
    "roll", "pitch", "altitude", "gps_data", "gps_ready", "uwTick",
]

# --- FUNCIONES DE SOPORTE ---
def parse_rcv(line: str) -> Optional[str]:
    """Extrae el payload de +RCV=addr,len,data,rssi,snr"""
    if not line.startswith("+RCV="):
        return None
    try:
        inner = line[5:]
        parts = inner.split(",", 2)
        if len(parts) < 3: return None
        raw_data_rssi_snr = parts[2]
        tokens = raw_data_rssi_snr.rsplit(",", 2) 
        if len(tokens) < 3: return None
        return tokens[0] 
    except: return None

def parse_telemetry(payload: str) -> Optional[Dict[str, str]]:
    fields = payload.split(",")
    if len(fields) != len(HEADERS):
        return None
    return dict(zip(HEADERS, fields))

def _to_float(x: Optional[str]) -> Optional[float]:
    if x is None: return None
    try: return float(x)
    except: return None

def _to_int(x: Optional[str]) -> Optional[int]:
    if x is None: return None
    try: return int(float(x))
    except: return None

@dataclass(frozen=True)
class TelemetryEvent:
    kind: str  # "status" | "raw" | "telemetry" | "warn" | "error" | "image"
    message: str = ""
    raw: str = ""
    telemetry: Optional[Dict[str, Any]] = None
    ts: float = 0.0

# --- CLASE PRINCIPAL DEL RECEPTOR ---
class SerialTelemetryReceiver:
    def __init__(
        self,
        events: "queue.Queue[TelemetryEvent]",
        *,
        sat_addr: int = 1,
        send_ack: bool = True,
        serial_timeout_s: float = 1.0,
    ):
        self._events = events
        self._sat_addr = sat_addr
        self._send_ack = send_ack
        self._serial_timeout_s = serial_timeout_s

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._ser: Optional[serial.Serial] = None

        self._last_alt_m: Optional[float] = None
        self._last_tick_ms: Optional[int] = None
        
        self._img_packets: Dict[int, bytes] = {}
        self._img_total_expected: Optional[int] = None
        self._img_last_recv_ts = time.time()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, port: str, baudrate: int) -> None:
        if self.running: return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(port, baudrate), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            if self._ser is not None: self._ser.close()
        except: pass

    def _emit(self, ev: TelemetryEvent) -> None:
        try: self._events.put_nowait(ev)
        except: pass

    def _crc16(self, data: bytes) -> int:
        crc = 0xFFFF
        for b in data:
            crc ^= b
            for _ in range(8):
                crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
        return crc

    def _send_ack_cmd(self, pkt_id: str) -> None:
        if not self._send_ack or self._ser is None: return
        payload = f"ACK,{pkt_id}"
        cmd = f"AT+SEND={self._sat_addr},{len(payload)},{payload}\r\n"
        self._ser.write(cmd.encode())

    def _run(self, port: str, baudrate: int) -> None:
        self._emit(TelemetryEvent(kind="status", message=f"Conectando a {port}...", ts=time.time()))
        try:
            self._ser = serial.Serial(port, baudrate, timeout=self._serial_timeout_s)
            
            # 🔥 CONFIGURACIÓN DE RADIO (SF7 + ADDR 0)
            self._ser.write(b'AT+ADDRESS=0\r\n') 
            time.sleep(0.2)
            self._ser.write(b'AT+PARAMETER=7,7,1,12\r\n') 
            time.sleep(0.5)
            
            self._emit(TelemetryEvent(kind="status", message=f"✅ Estación Terrena SF7 Lista en {port}", ts=time.time()))
        except Exception as e:
            self._emit(TelemetryEvent(kind="error", message=f"❌ Falla serial: {e}", ts=time.time()))
            self._ser = None
            return

        self._img_last_recv_ts = time.time()

        while not self._stop.is_set():
            now = time.time()
            
            # --- BLINDAJE: Timeout de imagen (3s de silencio = Ensamblar lo que haya) ---
            if self._img_total_expected is not None and (now - self._img_last_recv_ts > 5.0):
                self._emit(TelemetryEvent(kind="warn", message="⚠️ Timeout de ráfaga. Finalizando imagen parcial.", ts=now))
                self._ensamblar_y_emitir_imagen(final=True)

            # --- LECTURA DEL PUERTO ---
            try:
                if self._ser.in_waiting > 0:
                    raw = self._ser.readline().decode("utf-8", "ignore").strip()
                    if not raw: continue
                    
                    self._img_last_recv_ts = time.time()
                    self._emit(TelemetryEvent(kind="raw", raw=raw, ts=time.time()))
                    
                    payload = parse_rcv(raw)
                    if payload: self._procesar_payload(payload)
            except Exception as e:
                self._emit(TelemetryEvent(kind="error", message=f"Error en lectura: {e}"))
                break

        if self._ser: self._ser.close()
        self._emit(TelemetryEvent(kind="status", message="Desconectado.", ts=time.time()))

    def _procesar_payload(self, payload: str):
        handled_image = False
        # Intentar decodificar como imagen (Base64)
        try:
            b_data = payload.encode("utf-8", "ignore")
            frame = base64.b64decode(b_data, validate=True)
            if frame and frame.startswith(b"\xAA\x55"):
                handled_image = True
                self._procesar_paquete_imagen(frame)
        except: pass

        # Si no es imagen, procesar como telemetría (CSV)
        if not handled_image:
            data = parse_telemetry(payload)
            if data:
                self._procesar_telemetria(data)

    def _procesar_paquete_imagen(self, frame: bytes):
        try:
            hdr = frame[2:7]
            pkt_num, total_pkts, dlen = struct.unpack(">HHB", hdr)
            crc_start = 7 + dlen
            payload_bytes = frame[7:7 + dlen]
            recv_crc = struct.unpack(">H", frame[crc_start:crc_start + 2])[0]
            
            if self._crc16(frame[:crc_start]) != recv_crc:
                return

            if pkt_num == 0: # METADATOS
                if self._img_total_expected is None:
                    self._img_total_expected = total_pkts - 1
                    self._img_packets.clear()
                    self._emit(TelemetryEvent(kind="status", message="📦 Recibiendo nueva captura..."))
            else: # FRAGMENTO
                if pkt_num not in self._img_packets:
                    self._img_packets[pkt_num] = payload_bytes
                    # 🔥 Previsualización incremental
                    self._ensamblar_y_emitir_imagen(final=False)
                
                if self._img_total_expected and len(self._img_packets) == self._img_total_expected:
                    self._ensamblar_y_emitir_imagen(final=True)
        except: pass

    def _procesar_telemetria(self, data: Dict[str, str]):
        alt_m = _to_float(data.get("altitude"))
        tick_ms = _to_int(data.get("uwTick"))
        
        if all(v is not None for v in [alt_m, tick_ms, self._last_alt_m, self._last_tick_ms]):
            dt_s = (tick_ms - self._last_tick_ms) / 1000.0
            if dt_s > 0:
                vel = (alt_m - self._last_alt_m) / dt_s
                data["vel_mps"] = f"{vel:.2f}"
        
        self._last_alt_m, self._last_tick_ms = alt_m, tick_ms
        self._emit(TelemetryEvent(kind="telemetry", telemetry=data, ts=time.time()))
        self._send_ack_cmd(data.get("pkt_id", "0"))

    def _ensamblar_y_emitir_imagen(self, final=False):
        if not self._img_total_expected: return
        
        # Construir buffer (rellenando huecos con 100 bytes de negro)
        image_data = b""
        for i in range(1, self._img_total_expected + 1):
            image_data += self._img_packets.get(i, b"\x00" * 100)
        
        # Definir mensaje de evento
        ev_msg = f"captura_{int(time.time())}.jpg" if final else "preview.jpg"
        
        # Enviar a la UI
        self._emit(TelemetryEvent(kind="image", message=ev_msg, telemetry={"image_bytes": image_data}, ts=time.time()))

        if final:
            try:
                with open(ev_msg, "wb") as f: f.write(image_data)
            except: pass
            # 🔥 Limpieza de memoria solo al finalizar
            self._img_packets.clear()
            self._img_total_expected = None