import tkinter as tk
from tkinter import ttk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from ui_estilos import BG_GLOBAL, BG_CONTENEDOR, FG_PRINCIPAL, COLOR_ACENTO

class TabAnalisis:
    def __init__(self, parent):
        self.frame = tk.Frame(parent, bg=BG_GLOBAL)
        self.frame.pack(expand=True, fill="both", padx=2, pady=2)
        
        self._construir()

    def _construir(self):
        # Panel Izquierdo: Datos Críticos e IMU
        frame_izq = tk.Frame(self.frame, bg=BG_CONTENEDOR, width=300)
        frame_izq.pack(side="left", fill="y", padx=10, pady=10)

        # 1. Telemetría Principal
        frame_telemetria = ttk.LabelFrame(frame_izq, text=" Telemetría Ambiental ")
        frame_telemetria.pack(fill="x", pady=(0, 10))

        self.var_presion = tk.StringVar(value="1013.25")
        self.var_temp = tk.StringVar(value="22.5")
        self.var_vel = tk.StringVar(value="0.0")

        self._crear_indicador(frame_telemetria, "Presión", self.var_presion, "hPa")
        self._crear_indicador(frame_telemetria, "Temperatura", self.var_temp, "°C")
        self._crear_indicador(frame_telemetria, "Velocidad", self.var_vel, "m/s")
        
        # 2. GPS
        frame_gps = ttk.LabelFrame(frame_izq, text=" Posicionamiento Global (GPS) ")
        frame_gps.pack(fill="x", pady=10)
        
        self.var_lat = tk.StringVar(value="0.000000")
        self.var_lon = tk.StringVar(value="0.000000")
        self.var_alt_gps = tk.StringVar(value="0.0")
        self.var_sats = tk.StringVar(value="0")

        self._crear_indicador(frame_gps, "Latitud", self.var_lat, "°")
        self._crear_indicador(frame_gps, "Longitud", self.var_lon, "°")
        self._crear_indicador(frame_gps, "Alt. GPS", self.var_alt_gps, "m")
        self._crear_indicador(frame_gps, "Satélites", self.var_sats, "")

        # 3. IMU
        frame_imu = ttk.LabelFrame(frame_izq, text=" Sensor Inercial (IMU) ")
        frame_imu.pack(fill="x", pady=10)

        self.var_ax, self.var_ay, self.var_az = tk.StringVar(value="0.0"), tk.StringVar(value="0.0"), tk.StringVar(value="9.8")
        self.var_gx, self.var_gy, self.var_gz = tk.StringVar(value="0.0"), tk.StringVar(value="0.0"), tk.StringVar(value="0.0")

        ttk.Label(frame_imu, text="Acelerómetro (m/s²)", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(5,0))
        self._crear_fila_xyz(frame_imu, self.var_ax, self.var_ay, self.var_az)
        ttk.Separator(frame_imu, orient="horizontal").pack(fill="x", pady=5, padx=10)
        ttk.Label(frame_imu, text="Giroscopio (°/s)", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(5,0))
        self._crear_fila_xyz(frame_imu, self.var_gx, self.var_gy, self.var_gz)

        # 4. Estado de Autogiro
        frame_estado = ttk.LabelFrame(frame_izq, text=" Sistema de Control ")
        frame_estado.pack(fill="x", pady=10)
        self.var_autogiro = tk.StringVar(value="EN ESPERA")
        ttk.Label(frame_estado, textvariable=self.var_autogiro, font=("Segoe UI", 12, "bold"), foreground=COLOR_ACENTO).pack(pady=10)

        # Panel Derecho: Gráficas
        frame_graficos = ttk.LabelFrame(self.frame, text=" Dinámica de Vuelo ")
        frame_graficos.pack(side="right", expand=True, fill="both", padx=10, pady=10)

        self.figura = Figure(figsize=(8, 8), dpi=100, facecolor=BG_CONTENEDOR)
        self.figura.subplots_adjust(hspace=0.5, wspace=0.3) 
        
        self.ax_alt = self.figura.add_subplot(321)
        self.ax_alt.set_title("Altitud", fontsize=10, color=FG_PRINCIPAL)
        
        self.ax_pres = self.figura.add_subplot(322)
        self.ax_pres.set_title("Presión Atmosférica", fontsize=10, color=FG_PRINCIPAL)
        
        self.ax_temp = self.figura.add_subplot(323)
        self.ax_temp.set_title("Temperatura", fontsize=10, color=FG_PRINCIPAL)
        
        self.ax_vel = self.figura.add_subplot(324)
        self.ax_vel.set_title("Velocidad de Descenso", fontsize=10, color=FG_PRINCIPAL)
        
        self.ax_acel = self.figura.add_subplot(325)
        self.ax_acel.set_title("Aceleración Z", fontsize=10, color=FG_PRINCIPAL)

        for ax in [self.ax_alt, self.ax_pres, self.ax_temp, self.ax_vel, self.ax_acel]:
            ax.grid(True, linestyle='--', alpha=0.6)
            ax.tick_params(labelsize=8, colors=FG_PRINCIPAL)
            ax.set_facecolor(BG_CONTENEDOR)
            for spine in ax.spines.values():
                spine.set_color(COLOR_ACENTO)

        self.canvas_grafico = FigureCanvasTkAgg(self.figura, master=frame_graficos)
        self.canvas_grafico.get_tk_widget().pack(expand=True, fill="both", padx=5, pady=5)

    def _crear_indicador(self, parent, titulo, variable, unidad):
        frame = tk.Frame(parent, bg=BG_CONTENEDOR)
        frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(frame, text=f"{titulo}:", width=12).pack(side="left")
        ttk.Label(frame, textvariable=variable, font=("Segoe UI", 11, "bold"), width=8).pack(side="left")
        ttk.Label(frame, text=unidad).pack(side="left", padx=2)

    def _crear_fila_xyz(self, parent, var_x, var_y, var_z):
        frame_xyz = tk.Frame(parent, bg=BG_CONTENEDOR)
        frame_xyz.pack(fill="x", padx=10, pady=5)
        
        ttk.Label(frame_xyz, text="X:", foreground="#e84118", font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Label(frame_xyz, textvariable=var_x, width=5).pack(side="left")
        
        ttk.Label(frame_xyz, text="Y:", foreground="#4cd137", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(5,0))
        ttk.Label(frame_xyz, textvariable=var_y, width=5).pack(side="left")
        
        ttk.Label(frame_xyz, text="Z:", foreground="#00a8ff", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(5,0))
        ttk.Label(frame_xyz, textvariable=var_z, width=5).pack(side="left")