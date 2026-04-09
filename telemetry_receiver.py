import time
import threading
import queue
from dataclasses import dataclass
from typing import Optional, Dict, Any, Callable

import serial


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
    "uwTick",
]


def parse_rcv(line: str) -> Optional[str]:
    """Extract payload from +RCV=addr,len,data,... (strip trailing RSSI,SNR)."""
    if not line.startswith("+RCV="):
        return None
    inner = line[5:]
    parts = inner.split(",", 4)
    if len(parts) < 3:
        return None
    raw = ",".join(parts[2:])
    tokens = raw.rsplit(",", 2)  # strip trailing RSSI,SNR
    return tokens[0]


def parse_telemetry(payload: str) -> Optional[Dict[str, str]]:
    """Parse CSV payload into dict (string values)."""
    fields = payload.split(",")
    if len(fields) != len(HEADERS):
        return None
    return dict(zip(HEADERS, fields))


def _to_float(x: Optional[str]) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def _to_int(x: Optional[str]) -> Optional[int]:
    if x is None:
        return None
    try:
        return int(float(x))
    except Exception:
        return None


@dataclass(frozen=True)
class TelemetryEvent:
    kind: str  # "status" | "raw" | "telemetry" | "warn" | "error"
    message: str = ""
    raw: str = ""
    telemetry: Optional[Dict[str, str]] = None
    ts: float = 0.0


class SerialTelemetryReceiver:
    """
    Background serial reader that emits TelemetryEvent into a Queue.
    Safe for Tkinter: UI thread should poll the queue via root.after(...).
    """

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

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, port: str, baudrate: int) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(port, baudrate),
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            if self._ser is not None:
                self._ser.close()
        except Exception:
            pass

    def _emit(self, ev: TelemetryEvent) -> None:
        try:
            self._events.put_nowait(ev)
        except Exception:
            # If UI isn't draining fast enough, drop events rather than blocking serial thread.
            pass

    def _send_ack(self, pkt_id: str) -> None:
        if not self._send_ack or self._ser is None:
            return
        payload = f"ACK,{pkt_id}"
        cmd = f"AT+SEND={self._sat_addr},{len(payload)},{payload}\r\n"
        self._ser.write(cmd.encode())
        time.sleep(0.05)

    def _run(self, port: str, baudrate: int) -> None:
        self._emit(TelemetryEvent(kind="status", message=f"Connecting to {port} @ {baudrate}...", ts=time.time()))
        try:
            self._ser = serial.Serial(port, baudrate, timeout=self._serial_timeout_s)
            time.sleep(0.5)
            self._emit(TelemetryEvent(kind="status", message=f"✅ Connected to {port}", ts=time.time()))
        except Exception as e:
            self._emit(TelemetryEvent(kind="error", message=f"❌ Serial open failed: {e}", ts=time.time()))
            self._ser = None
            return

        while not self._stop.is_set():
            try:
                raw = self._ser.readline().decode("utf-8", "ignore").strip()  # type: ignore[union-attr]
            except Exception as e:
                self._emit(TelemetryEvent(kind="error", message=f"❌ Serial read failed: {e}", ts=time.time()))
                break

            if not raw:
                continue

            self._emit(TelemetryEvent(kind="raw", raw=raw, ts=time.time()))

            payload = parse_rcv(raw)
            if payload is None:
                continue

            data = parse_telemetry(payload)
            if data is None:
                self._emit(TelemetryEvent(kind="warn", message=f"Unexpected payload: {payload}", ts=time.time()))
                continue

            # Derive velocity if possible (altitude / uwTick)
            alt_m = _to_float(data.get("altitude"))
            tick_ms = _to_int(data.get("uwTick"))
            if alt_m is not None and tick_ms is not None and self._last_alt_m is not None and self._last_tick_ms is not None:
                dt_s = (tick_ms - self._last_tick_ms) / 1000.0
                if dt_s > 0:
                    vel = (alt_m - self._last_alt_m) / dt_s
                    data["vel_mps"] = f"{vel:.3f}"
            self._last_alt_m = alt_m if alt_m is not None else self._last_alt_m
            self._last_tick_ms = tick_ms if tick_ms is not None else self._last_tick_ms

            self._emit(TelemetryEvent(kind="telemetry", telemetry=data, ts=time.time()))

            try:
                self._send_ack(data.get("pkt_id", ""))
            except Exception as e:
                self._emit(TelemetryEvent(kind="warn", message=f"ACK failed: {e}", ts=time.time()))

        try:
            if self._ser is not None:
                self._ser.close()
        except Exception:
            pass
        self._emit(TelemetryEvent(kind="status", message="Disconnected.", ts=time.time()))
