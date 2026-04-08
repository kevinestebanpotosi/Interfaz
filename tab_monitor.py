import tkinter as tk
from tkinter import ttk
from ui_estilos import BG_GLOBAL, BG_CONTENEDOR, FG_PRINCIPAL, COLOR_ACENTO

class TabMonitor:
    def __init__(self, parent):
        self.frame = tk.Frame(parent, bg=BG_GLOBAL)
        self.frame.pack(expand=True, fill="both")
        
        self._construir()

    def _construir(self):
        frame_conexion = ttk.Frame(self.frame)
        frame_conexion.pack(fill="x", pady=15, padx=20)

        ttk.Label(frame_conexion, text="Puerto:").pack(side="left", padx=5)
        self.combo_puerto = ttk.Combobox(frame_conexion, values=["COM1", "COM3", "COM4", "/dev/ttyUSB0"], width=15)
        self.combo_puerto.pack(side="left", padx=5)

        ttk.Label(frame_conexion, text="Baudios:").pack(side="left", padx=5)
        self.combo_baudios = ttk.Combobox(frame_conexion, values=["9600", "57600", "115200"], width=10)
        self.combo_baudios.pack(side="left", padx=5)

        self.btn_conectar = ttk.Button(frame_conexion, text="Conectar UART")
        self.btn_conectar.pack(side="left", padx=20)

        frame_terminal = ttk.LabelFrame(self.frame, text=" Terminal Serial ")
        frame_terminal.pack(expand=True, fill="both", padx=20, pady=(0, 20))

        self.texto_terminal = tk.Text(frame_terminal, bg=BG_CONTENEDOR, fg=FG_PRINCIPAL, font=("Consolas", 10), padx=10, pady=10)
        self.texto_terminal.pack(expand=True, fill="both", padx=5, pady=5)