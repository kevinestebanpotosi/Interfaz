import tkinter as tk
from tkinter import ttk
from ui_estilos import BG_GLOBAL, BG_CONTENEDOR, FG_PRINCIPAL

class TabMonitor:
    def __init__(self, parent, *, on_connect, on_disconnect):
        self.frame = tk.Frame(parent, bg=BG_GLOBAL)
        self.frame.pack(expand=True, fill="both")

        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._connected = False
        
        self._construir()

    def _construir(self):
        frame_conexion = ttk.Frame(self.frame)
        frame_conexion.pack(fill="x", pady=15, padx=20)

        ttk.Label(frame_conexion, text="Puerto:").pack(side="left", padx=5)
        self.combo_puerto = ttk.Combobox(
            frame_conexion,
            values=["/dev/cu.usbserial-0001", "/dev/cu.usbmodemXXXX", "/dev/cu.SLAB_USBtoUART", "/dev/ttyUSB0", "COM3"],
            width=22,
        )
        self.combo_puerto.pack(side="left", padx=5)
        if not self.combo_puerto.get():
            self.combo_puerto.set("/dev/cu.usbserial-0001")

        ttk.Label(frame_conexion, text="Baudios:").pack(side="left", padx=5)
        self.combo_baudios = ttk.Combobox(frame_conexion, values=["9600", "57600", "115200"], width=10)
        self.combo_baudios.pack(side="left", padx=5)
        if not self.combo_baudios.get():
            self.combo_baudios.set("115200")

        self.btn_conectar = ttk.Button(frame_conexion, text="Conectar UART", command=self._toggle_connection)
        self.btn_conectar.pack(side="left", padx=20)

        frame_terminal = ttk.LabelFrame(self.frame, text=" Terminal Serial ")
        frame_terminal.pack(expand=True, fill="both", padx=20, pady=(0, 20))

        self.texto_terminal = tk.Text(frame_terminal, bg=BG_CONTENEDOR, fg=FG_PRINCIPAL, font=("Consolas", 10), padx=10, pady=10)
        self.texto_terminal.pack(expand=True, fill="both", padx=5, pady=5)
        self.texto_terminal.configure(state="disabled")

        self._append_line("Ready. Select port/baud and connect.")

    def _toggle_connection(self):
        if not self._connected:
            port = self.combo_puerto.get().strip()
            baud = int(self.combo_baudios.get().strip() or "115200")
            self._append_line(f"[UI] Connecting to {port} @ {baud} ...")
            self._on_connect(port, baud)
            self._connected = True
            self.btn_conectar.configure(text="Desconectar")
        else:
            self._append_line("[UI] Disconnecting ...")
            self._on_disconnect()
            self._connected = False
            self.btn_conectar.configure(text="Conectar UART")

    def _append_line(self, line: str):
        self.texto_terminal.configure(state="normal")
        self.texto_terminal.insert("end", line + "\n")
        self.texto_terminal.see("end")
        self.texto_terminal.configure(state="disabled")

    def show_event(self, *, kind: str, message: str = "", raw: str = ""):
        if kind == "raw" and raw:
            self._append_line(f"[RAW] {raw}")
            return
        if message:
            tag = kind.upper()
            self._append_line(f"[{tag}] {message}")