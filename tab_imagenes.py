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
        # Deque para últimas 3 imágenes
        from collections import deque
        self._recent = deque(maxlen=3)
        self._tk_imgs = [None, None, None]

        self._construir()

    def _construir(self):
        self.frame.columnconfigure(0, weight=1)
        self.frame.columnconfigure(1, weight=1)
        self.frame.rowconfigure(0, weight=1)

        # Tres slots: izquierda (cruda), centro (anaglifo/procesada), derecha (estéreo)
        frame_row = tk.Frame(self.frame, bg=BG_GLOBAL)
        frame_row.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=15, pady=15)

        self.canvas_left = tk.Canvas(frame_row, bg=BG_CONTENEDOR)
        self.canvas_center = tk.Canvas(frame_row, bg=BG_CONTENEDOR)
        self.canvas_right = tk.Canvas(frame_row, bg=BG_CONTENEDOR)

        self.canvas_left.pack(side="left", expand=True, fill="both", padx=5, pady=5)
        self.canvas_center.pack(side="left", expand=True, fill="both", padx=5, pady=5)
        self.canvas_right.pack(side="left", expand=True, fill="both", padx=5, pady=5)

        self._left_img_tk = None
        self._center_img_tk = None
        self._right_img_tk = None

    def show_image(self, image_bytes: bytes):
        # Guardar en deque y actualizar los 3 canvases (más reciente en la izquierda)
        try:
            from PIL import ImageFile
            ImageFile.LOAD_TRUNCATED_IMAGES = True
            self._recent.appendleft(image_bytes)
        except Exception as e:
            print(f"[UI ERROR] No se pudo almacenar imagen: {e}")
            return

        canvases = [self.canvas_left, self.canvas_center, self.canvas_right]
        tk_slots = ['_left_img_tk', '_center_img_tk', '_right_img_tk']

        for i, canvas in enumerate(canvases):
            canvas.delete("all")
            try:
                b = self._recent[i]
            except Exception:
                b = None
            if b is None:
                continue
            try:
                img = Image.open(io.BytesIO(b))
                img.load()
                w = canvas.winfo_width() or 300
                h = canvas.winfo_height() or 200
                if w < 10: w = 300
                if h < 10: h = 200
                img.thumbnail((w, h), Image.Resampling.LANCZOS)
                setattr(self, tk_slots[i], ImageTk.PhotoImage(img))
                canvas.create_image(w // 2, h // 2, image=getattr(self, tk_slots[i]), anchor="center")
            except Exception as e:
                print(f"[UI ERROR] No se pudo mostrar slot {i+1}: {e}")
                continue