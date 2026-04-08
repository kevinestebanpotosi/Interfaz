import tkinter as tk
from tkinter import ttk

# Importar nuestros módulos separados
from ui_estilos import configurar_estilos, construir_cabecera, BG_GLOBAL
from tab_analisis import TabAnalisis
from tab_imagenes import TabImagenes
from tab_monitor import TabMonitor
from tab_config import TabConfig

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

        # Crear los objetos de cada pestaña
        self.tab_analisis = TabAnalisis(self.notebook)
        self.tab_imagenes = TabImagenes(self.notebook)
        self.tab_monitor = TabMonitor(self.notebook)
        self.tab_config = TabConfig(self.notebook)

        # Añadir los frames (self.tab_analisis.frame) al notebook
        self.notebook.add(self.tab_analisis.frame, text="📊 Análisis y Dashboard")
        self.notebook.add(self.tab_imagenes.frame, text="📷 Visor Estereoscópico")
        self.notebook.add(self.tab_monitor.frame, text="🔌 Monitor Serial")
        self.notebook.add(self.tab_config.frame, text="⚙️ Configuración")

if __name__ == "__main__":
    root = tk.Tk()
    app = EstacionTerrenaCanSat(root)
    root.mainloop()