import tkinter as tk
from tkinter import ttk
from ui_estilos import BG_GLOBAL, BG_CONTENEDOR, FG_PRINCIPAL

class TabImagenes:
    def __init__(self, parent):
        self.frame = tk.Frame(parent, bg=BG_GLOBAL)
        self.frame.pack(expand=True, fill="both")
        
        self._construir()

    def _construir(self):
        self.frame.columnconfigure(0, weight=1)
        self.frame.columnconfigure(1, weight=1)
        self.frame.rowconfigure(0, weight=1)

        frame_img_izq = ttk.LabelFrame(self.frame, text=" Cámara Abordo (Cruda) ")
        frame_img_izq.grid(row=0, column=0, sticky="nsew", padx=15, pady=15)
        tk.Canvas(frame_img_izq, bg=BG_CONTENEDOR).pack(expand=True, fill="both", padx=5, pady=5)

        frame_img_der = ttk.LabelFrame(self.frame, text=" Procesado Estereoscópico 3D ")
        frame_img_der.grid(row=0, column=1, sticky="nsew", padx=15, pady=15)
        tk.Canvas(frame_img_der, bg=BG_CONTENEDOR).pack(expand=True, fill="both", padx=5, pady=5)