import tkinter as tk
from tkinter import ttk
from ui_estilos import BG_GLOBAL

class TabConfig:
    def __init__(self, parent):
        self.frame = tk.Frame(parent, bg=BG_GLOBAL)
        self.frame.pack(expand=True, fill="both")
        
        self._construir()

    def _construir(self):
        frame_opciones = ttk.LabelFrame(self.frame, text=" Parámetros del Sistema ", padding=20)
        frame_opciones.pack(fill="x", padx=20, pady=20)
        
        ttk.Label(frame_opciones, text="Frecuencia de Muestreo (ms):").grid(row=0, column=0, sticky="w", pady=10)
        ttk.Spinbox(frame_opciones, from_=50, to=2000, increment=50, width=10).grid(row=0, column=1, padx=10)