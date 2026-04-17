import tkinter as tk
from tkinter import ttk
import queue

# Importar nuestros módulos separados
from ui_estilos import configurar_estilos, construir_cabecera, BG_GLOBAL
from tab_analisis import TabAnalisis
from tab_imagenes import TabImagenes
from tab_monitor import TabMonitor
from tab_config import TabConfig
from telemetry_receiver import SerialTelemetryReceiver, TelemetryEvent

class EstacionTerrenaCanSat:
    def __init__(self, root):
        self.root = root
        self.root.title("Control de Misión CanSat")
        self.root.geometry("1300x850")
        self.root.configure(bg=BG_GLOBAL)

        # Configuración visual
        configurar_estilos()
        construir_cabecera(self.root)

        # Sistema de pestañas
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(expand=True, fill="both", padx=20, pady=(0, 20))

        # Telemetría (serial → queue → UI)
        self._events: "queue.Queue[TelemetryEvent]" = queue.Queue(maxsize=2000)
        self._receiver = SerialTelemetryReceiver(self._events, sat_addr=1, send_ack=True)

        # Crear los objetos de cada pestaña
        self.tab_analisis = TabAnalisis(self.notebook)
        self.tab_imagenes = TabImagenes(self.notebook)
        self.tab_monitor = TabMonitor(
            self.notebook,
            on_connect=self._on_connect,
            on_disconnect=self._on_disconnect,
        )
        self.tab_config = TabConfig(self.notebook)

        # Añadir los frames (self.tab_analisis.frame) al notebook
        self.notebook.add(self.tab_analisis.frame, text="📊 Análisis y Dashboard")
        self.notebook.add(self.tab_imagenes.frame, text="📷 Visor Estereoscópico")
        self.notebook.add(self.tab_monitor.frame, text="🔌 Monitor Serial")
        self.notebook.add(self.tab_config.frame, text="⚙️ Configuración")

        self.root.after(50, self._drain_events)
        # Track images saved to disk (by wifi.py or telemetry_receiver) and display them
        self._seen_images = set()
        self.root.after(1000, self._scan_saved_images)

    def _on_connect(self, port: str, baudrate: int):
        self._receiver.start(port, baudrate)

    def _on_disconnect(self):
        self._receiver.stop()

    def _drain_events(self):
        # Drain a bounded number of events to keep UI responsive
        for _ in range(200):
            try:
                ev = self._events.get_nowait()
            except Exception:
                break

            if ev.kind in ("status", "warn", "error"):
                self.tab_monitor.show_event(kind=ev.kind, message=ev.message)
            elif ev.kind == "raw":
                self.tab_monitor.show_event(kind=ev.kind, raw=ev.raw)
            elif ev.kind == "telemetry" and ev.telemetry is not None:
                try:
                    self.tab_analisis.apply_telemetry(ev.telemetry)
                except Exception as e:
                    self.tab_monitor.show_event(kind="error", message=f"UI telemetry update failed: {e}")
            elif ev.kind == "image":
                # Image event: display in images tab
                try:
                    img_bytes = None
                    if ev.telemetry and isinstance(ev.telemetry, dict):
                        img_bytes = ev.telemetry.get("image_bytes")
                    if img_bytes is None and ev.message:
                        # fallback: read file saved by receiver
                        try:
                            with open(ev.message, "rb") as f:
                                img_bytes = f.read()
                        except Exception:
                            img_bytes = None
                    if img_bytes is not None:
                        try:
                            self.tab_imagenes.show_image(img_bytes)
                            self.tab_monitor.show_event(kind="status", message=f"Image displayed: {ev.message}")
                        except Exception as e:
                            self.tab_monitor.show_event(kind="warn", message=f"Image display failed: {e}")
                except Exception as e:
                    self.tab_monitor.show_event(kind="warn", message=f"Image event handling error: {e}")

        self.root.after(50, self._drain_events)

    def _scan_saved_images(self):
        """Scan filesystem for newly saved images and display them in the images tab.

        This catches files saved by `wifi.py` (anaglifo_captura_*.jpg) and by
        `telemetry_receiver.py` (captura_*.jpg in `capturas/`)."""
        import glob
        import os

        patterns = ["anaglifo_captura_*.jpg", os.path.join("capturas", "captura_*.jpg")]
        for pat in patterns:
            for path in sorted(glob.glob(pat), key=os.path.getmtime):
                if path in self._seen_images:
                    continue
                try:
                    with open(path, "rb") as f:
                        data = f.read()
                    self.tab_imagenes.show_image(data)
                    self._seen_images.add(path)
                    self.tab_monitor.show_event(kind="status", message=f"Loaded saved image: {path}")
                except Exception as e:
                    self.tab_monitor.show_event(kind="warn", message=f"Failed to load saved image {path}: {e}")

        # reschedule
        self.root.after(1000, self._scan_saved_images)

if __name__ == "__main__":
    root = tk.Tk()
    app = EstacionTerrenaCanSat(root)
    root.mainloop()