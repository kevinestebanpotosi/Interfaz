import os
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import tkinter.font as tkFont # Para manejar tipografías avanzadas

# --- PALETA DE COLORES DARK TECH ---
# Usaremos variables globales para que sea fácil cambiar el tema luego si quieres
BG_GLOBAL = "#000000"     # Fondo de la ventana (Negro puro)
BG_CONTENEDOR = "#0e0e0e" # Fondo de tarjetas, tabs y frames (Muy oscuro)
FG_PRINCIPAL = "#e6e6e6"  # Texto principal (Blanco suave)
FG_SECUNDARIO = "#9a9a9a" # Texto secundario (Gris medio)
COLOR_ACENTO = "#ffd54a"  # Acento dorado cálido para contraste sobre negro
COLOR_BORDE = "#1f1f1f"   # Color sutil para bordes y separadores

def configurar_estilos():
    style = ttk.Style()
    style.theme_use("clam") 
    
    # Definir tipografías modernas
    fuente_normal = ("Segoe UI", 10)
    fuente_titulos = ("Segoe UI", 11, "bold")
    
    # --- CONFIGURACIÓN GLOBAL ---
    style.configure(".", font=fuente_normal, background=BG_GLOBAL, foreground=FG_PRINCIPAL)
    style.configure("TLabel", background=BG_GLOBAL, foreground=FG_PRINCIPAL)
    style.configure("TFrame", background=BG_GLOBAL)
    
    # --- ESTILO PARA CONTENEDORES (LabelFrames) ---
    style.configure("TLabelframe", background=BG_CONTENEDOR, borderwidth=1, bordercolor=COLOR_BORDE)
    style.configure("TLabelframe.Label", 
                    font=fuente_titulos, 
                    background=BG_CONTENEDOR, 
                    foreground=COLOR_ACENTO) # Títulos de recuadros en Cian
    
    # --- ESTILO PARA PESTAÑAS (Notebook) ---
    style.configure("TNotebook", background=BG_GLOBAL, borderwidth=0)
    style.configure("TNotebook.Tab", 
                    font=fuente_normal, 
                    padding=[20, 8], 
                    background=COLOR_BORDE, # Fondo pestaña inactiva
                    foreground=FG_PRINCIPAL, # Texto pestaña inactiva
                    borderwidth=0)
    
    # Colores cuando la pestaña está seleccionada
    style.map("TNotebook.Tab", 
              background=[("selected", BG_CONTENEDOR)], 
              foreground=[("selected", COLOR_ACENTO)])

    # --- ESTILO PARA BOTONES (Ej. en TabMonitor) ---
    style.configure("TButton", 
                    font=fuente_titulos, 
                    background=COLOR_BORDE, 
                    foreground=FG_PRINCIPAL, 
                    borderwidth=0)
    style.map("TButton", 
              background=[("active", COLOR_ACENTO)], 
              foreground=[("active", "#000000")]) # Texto negro al presionar

    # --- ESTILO PARA COMBOS (Selectores en TabMonitor) ---
    style.configure("TCombobox", fieldbackground=BG_GLOBAL, background=COLOR_BORDE, foreground=FG_PRINCIPAL)

def construir_cabecera(parent):
    # Fondo de cabecera gris oscuro
    frame_header = tk.Frame(parent, bg=BG_CONTENEDOR, height=140)
    frame_header.pack(fill="x", padx=20, pady=20)
    frame_header.pack_propagate(False)

    # --- 1. LOGO DEL EQUIPO (Izquierda) ---
    lbl_logo_eq = tk.Label(frame_header, bg=BG_CONTENEDOR)
    lbl_logo_eq.pack(side="left", padx=25)
    
    try:
        candidatos_eq = ["Logo_Equipo.png", "logo_EQUIPO.png", "logo_equipo.png"]
        archivo_eq = next((f for f in candidatos_eq if os.path.exists(f)), None)
        if archivo_eq:
            img_eq = Image.open(archivo_eq)
            img_eq = img_eq.resize((90, 90), Image.Resampling.LANCZOS)
            img_tk_eq = ImageTk.PhotoImage(img_eq)
            lbl_logo_eq.config(image=img_tk_eq)
            lbl_logo_eq.image = img_tk_eq
        else:
            raise FileNotFoundError
    except FileNotFoundError:
        lbl_logo_eq.config(text="Logo Equipo", font=("Arial", 9), bg=COLOR_BORDE, fg=FG_PRINCIPAL, width=12, height=6)

    # --- 2. TEXTOS (Centro) ---
    frame_titulos = tk.Frame(frame_header, bg=BG_CONTENEDOR)
    frame_titulos.pack(side="left", expand=True, fill="both")
    
    # Nombre del Equipo/Proyecto - Título Grande y Cian
    tk.Label(frame_titulos, 
             text="ATISQUE", 
             font=("Segoe UI Light", 24), # "Light" le da un toque muy elegante
             bg=BG_CONTENEDOR, 
             fg=COLOR_ACENTO).pack(pady=(15, 0))
    
    # Subtítulo Gris
    tk.Label(frame_titulos, 
             text="Misión CanSat - Control de Misión y Telemetría", 
             font=("Segoe UI", 11), 
             bg=BG_CONTENEDOR, 
             fg=FG_SECUNDARIO).pack()

    # --- APARTADO PARA INTEGRANTES (Nuevo) ---
    # Usaremos una tipografía diferente (Monospace o Italic sutil)
    fuente_nombres = tkFont.Font(family="Consolas", size=9)
    
    # ¡AQUÍ ESCRIBES LOS NOMBRES DE TU EQUIPO! Separados por coma o punto.
    nombres_integrantes = "Integrantes: JAVIER. RUIZ · DAYANA. GALINDO · JOSE. RUIZ · RONNOVI Rigel · KEVIN. POTOSI · ELKIN. RODRIGUEZ · KEVIN.RIVERA"
    
    tk.Label(frame_titulos, 
             text=nombres_integrantes, 
             font=fuente_nombres, 
             bg=BG_CONTENEDOR, 
             fg=FG_SECUNDARIO, # Gris sutil para no distraer
             pady=10).pack()


    # --- 3. LOGO DE LA INSTITUCIÓN (Derecha) ---
    lbl_logo_inst = tk.Label(frame_header, bg=BG_CONTENEDOR)
    lbl_logo_inst.pack(side="right", padx=25)

    try:
        candidatos_inst = [
            r"D:\Interfaz\Logo_UNICAUCA.jpg"
        ]
        archivo_inst = next((f for f in candidatos_inst if os.path.exists(f)), None)
        if archivo_inst:
            img_inst = Image.open(archivo_inst)
            img_inst = img_inst.resize((90, 90), Image.Resampling.LANCZOS)
            img_tk_inst = ImageTk.PhotoImage(img_inst)
            lbl_logo_inst.config(image=img_tk_inst)
            lbl_logo_inst.image = img_tk_inst
        else:
            raise FileNotFoundError
    except FileNotFoundError:
        lbl_logo_inst.config(text="Logo UNICAUCA", font=("Arial", 9), bg=COLOR_BORDE, fg=FG_PRINCIPAL, width=12, height=6)