import tkinter as tk
from tkinter import ttk
from ui_estilos import BG_GLOBAL, BG_CONTENEDOR, FG_PRINCIPAL
from PIL import Image, ImageTk, ImageFile
import io

# ¡CRÍTICO PARA TELEMETRÍA DE RADIO!
# Obliga a la librería a mostrar la imagen incluso si se perdieron paquetes en el aire.
ImageFile.LOAD_TRUNCATED_IMAGES = True

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
        self.canvas_left = tk.Canvas(frame_img_izq, bg=BG_CONTENEDOR)
        self.canvas_left.pack(expand=True, fill="both", padx=5, pady=5)


        frame_img_der = ttk.LabelFrame(self.frame, text=" Procesado Estereoscópico 3D ")
        frame_img_der.grid(row=0, column=1, sticky="nsew", padx=15, pady=15)
        self.canvas_right = tk.Canvas(frame_img_der, bg=BG_CONTENEDOR)
        self.canvas_right.pack(expand=True, fill="both", padx=5, pady=5)

        self._left_img_tk = None
        self._right_img_tk = None

    def show_image(self, image_bytes: bytes):
        try:
            img = Image.open(io.BytesIO(image_bytes))
            # Forzar la decodificación inmediata para atrapar errores antes de procesar
            img.load()
        except Exception as e:
            print(f"[UI ERROR] No se pudo procesar la imagen: {e}")
            return

        # --- LIENZO IZQUIERDO ---
        w = self.canvas_left.winfo_width()
        h = self.canvas_left.winfo_height()
        
        # Blindaje: Si la pestaña no está visible, winfo_width devuelve 1. 
        # Se fuerza un tamaño estándar para evitar generar una imagen invisible de 1x1 píxel.
        if w < 10: w = 400
        if h < 10: h = 300

        img_l = img.copy()
        img_l.thumbnail((w, h), Image.Resampling.LANCZOS)
        self._left_img_tk = ImageTk.PhotoImage(img_l)
        self.canvas_left.delete("all")
        self.canvas_left.create_image(w // 2, h // 2, image=self._left_img_tk, anchor="center")

        # --- LIENZO DERECHO ---
        wr = self.canvas_right.winfo_width()
        hr = self.canvas_right.winfo_height()
        
        if wr < 10: wr = 400
        if hr < 10: hr = 300

        img_r = img.copy()
        img_r.thumbnail((wr, hr), Image.Resampling.LANCZOS)
        self._right_img_tk = ImageTk.PhotoImage(img_r)
        self.canvas_right.delete("all")
        self.canvas_right.create_image(wr // 2, hr // 2, image=self._right_img_tk, anchor="center")