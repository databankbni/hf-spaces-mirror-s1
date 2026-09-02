"""Interfaz gráfica Tkinter para el análisis IDF.

Permite al usuario ingresar coordenadas (lat/lon) y parámetros opcionales,
ejecutar el pipeline completo en un hilo de fondo y generar un informe PDF
que se abre automáticamente con el visor predeterminado de Windows.

Pensado para ser empaquetado como aplicación Windows con PyInstaller +
Inno Setup. La carpeta de salida por defecto es `Documentos/IDF-Pasarela`.
"""

from __future__ import annotations

import os
import platform
import queue
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import (
    BooleanVar,
    DoubleVar,
    IntVar,
    StringVar,
    Tk,
    filedialog,
    messagebox,
    scrolledtext,
)
from tkinter import ttk

from .obras import TIPOS_OBRA
from .idf_models import RESOLUCIONES_DATOS
from .pipeline import ejecutar_pipeline
from .proyecto import DatosProyecto, APP_NOMBRE, APP_VERSION as _APP_VERSION


APP_NAME = APP_NOMBRE
APP_VERSION = _APP_VERSION


def _abrir_externamente(ruta: Path) -> None:
    """Abre el archivo con el visor predeterminado del SO."""
    s = platform.system()
    try:
        if s == "Windows":
            os.startfile(str(ruta))  # type: ignore[attr-defined]
        elif s == "Darwin":
            subprocess.Popen(["open", str(ruta)])
        else:
            subprocess.Popen(["xdg-open", str(ruta)])
    except Exception:
        pass


def _carpeta_documentos() -> Path:
    """Devuelve la carpeta Documentos del usuario."""
    if platform.system() == "Windows":
        # USERPROFILE\Documents — solución sin depender de Win32 APIs
        return Path(os.path.expanduser("~")) / "Documents" / "IDF-Pasarela"
    return Path(os.path.expanduser("~")) / "IDF-Pasarela"


class IDFApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title(f"{APP_NAME} — v{APP_VERSION}")
        self.root.geometry("660x780")
        self.root.minsize(580, 700)

        self.var_proyecto = StringVar(value="")
        self.var_ingeniero = StringVar(value="")
        self.var_ubicacion = StringVar(value="")
        self._obras = {o.nombre: o.clave for o in TIPOS_OBRA}
        self.var_obra = StringVar(value=TIPOS_OBRA[0].nombre)
        self._resoluciones = {et: cl for cl, et, _p, _j in RESOLUCIONES_DATOS}
        self.var_resolucion = StringVar(value="Diaria (P24max) + d > 2 h")
        self.var_cn = BooleanVar(value=False)
        self.var_lat = DoubleVar(value=-17.766589)
        self.var_lon = DoubleVar(value=-65.734027)
        self.var_anios = IntVar(value=35)
        self.var_semilla = IntVar(value=42)
        self.var_exp_dp = DoubleVar(value=0.25)
        self.var_criterio = StringVar(value="ks")
        self.var_t_diseno = StringVar(value="auto")
        self.var_out = StringVar(value=str(_carpeta_documentos()))
        self.var_abrir = BooleanVar(value=True)
        self.var_estado = StringVar(value="Listo.")

        self._cola: queue.Queue[tuple[str, str]] = queue.Queue()
        self._hilo: threading.Thread | None = None

        self._construir()
        self.root.after(150, self._procesar_cola)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _construir(self) -> None:
        s = ttk.Style()
        try:
            s.theme_use("vista" if platform.system() == "Windows" else "clam")
        except Exception:
            pass

        main = ttk.Frame(self.root, padding=14)
        main.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)

        ttk.Label(
            main, text=APP_NAME,
            font=("Segoe UI", 16, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(
            main, text="Análisis hidrológico: IDF, tiempo de concentración e hietogramas",
            foreground="#555",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 12))

        # --- Datos del proyecto ---
        df = ttk.LabelFrame(main, text="Datos del proyecto", padding=10)
        df.grid(row=2, column=0, columnspan=3, sticky="ew", pady=4)
        df.columnconfigure(1, weight=1)
        ttk.Label(df, text="Proyecto:").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        ttk.Entry(df, textvariable=self.var_proyecto).grid(row=0, column=1, sticky="ew")
        ttk.Label(df, text="Ing. a cargo:").grid(row=1, column=0, sticky="w", padx=4, pady=3)
        ttk.Entry(df, textvariable=self.var_ingeniero).grid(row=1, column=1, sticky="ew")
        ttk.Label(df, text="Ubicación:").grid(row=2, column=0, sticky="w", padx=4, pady=3)
        ttk.Entry(df, textvariable=self.var_ubicacion).grid(row=2, column=1, sticky="ew")
        ttk.Label(df, text="Tipo de obra:").grid(row=3, column=0, sticky="w", padx=4, pady=3)
        ttk.Combobox(df, textvariable=self.var_obra, state="readonly",
                     values=[o.nombre for o in TIPOS_OBRA]).grid(row=3, column=1, sticky="ew")
        ttk.Label(df, text="Resolución datos:").grid(row=4, column=0, sticky="w", padx=4, pady=3)
        ttk.Combobox(df, textvariable=self.var_resolucion, state="readonly",
                     values=[et for _c, et, _p, _j in RESOLUCIONES_DATOS]).grid(
                     row=4, column=1, sticky="ew")
        ttk.Checkbutton(df, text="CN verificado (habilita SCS en Tc)",
                        variable=self.var_cn).grid(row=5, column=1, sticky="w", pady=(2, 0))

        # --- Coordenadas ---
        gf = ttk.LabelFrame(main, text="Sitio (coordenadas geográficas)", padding=10)
        gf.grid(row=3, column=0, columnspan=3, sticky="ew", pady=4)
        gf.columnconfigure(1, weight=1)
        gf.columnconfigure(3, weight=1)
        ttk.Label(gf, text="Latitud (°):").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        ttk.Entry(gf, textvariable=self.var_lat, width=14).grid(row=0, column=1, sticky="w")
        ttk.Label(gf, text="Longitud (°):").grid(row=0, column=2, sticky="w", padx=10)
        ttk.Entry(gf, textvariable=self.var_lon, width=14).grid(row=0, column=3, sticky="w")
        ttk.Label(
            gf, text="Negativo = sur / oeste. Ej: La Paz ≈ -16.5, -68.15",
            foreground="#777",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))

        # --- Parámetros ---
        pf = ttk.LabelFrame(main, text="Parámetros del análisis", padding=10)
        pf.grid(row=4, column=0, columnspan=3, sticky="ew", pady=6)
        pf.columnconfigure(1, weight=1)
        pf.columnconfigure(3, weight=1)
        ttk.Label(pf, text="Años de serie:").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        ttk.Spinbox(pf, from_=10, to=200, textvariable=self.var_anios, width=8).grid(
            row=0, column=1, sticky="w"
        )
        ttk.Label(pf, text="Semilla aleatoria:").grid(row=0, column=2, sticky="w", padx=10)
        ttk.Spinbox(pf, from_=0, to=99999, textvariable=self.var_semilla, width=10).grid(
            row=0, column=3, sticky="w"
        )
        ttk.Label(pf, text="Exponente Dyck-Peschke:").grid(
            row=1, column=0, sticky="w", padx=4, pady=3
        )
        ttk.Spinbox(
            pf, from_=0.15, to=0.40, increment=0.01,
            textvariable=self.var_exp_dp, width=8, format="%.2f",
        ).grid(row=1, column=1, sticky="w")
        ttk.Label(pf, text="Criterio mejor ajuste:").grid(row=1, column=2, sticky="w", padx=10)
        ttk.Combobox(
            pf, textvariable=self.var_criterio,
            values=("ks", "rmse", "aic"), state="readonly", width=8,
        ).grid(row=1, column=3, sticky="w")
        ttk.Label(pf, text="T diseño (años):").grid(
            row=2, column=0, sticky="w", padx=4, pady=3
        )
        ttk.Combobox(
            pf, textvariable=self.var_t_diseno,
            values=("auto", 2, 5, 10, 25, 50, 100, 200, 250, 500, 1000, 10000),
            state="readonly", width=8,
        ).grid(row=2, column=1, sticky="w")

        # --- Salida ---
        sf = ttk.LabelFrame(main, text="Carpeta de salida", padding=10)
        sf.grid(row=5, column=0, columnspan=3, sticky="ew", pady=6)
        sf.columnconfigure(0, weight=1)
        ttk.Entry(sf, textvariable=self.var_out).grid(row=0, column=0, sticky="ew")
        ttk.Button(sf, text="Examinar…", command=self._elegir_carpeta).grid(
            row=0, column=1, padx=(6, 0)
        )
        ttk.Checkbutton(
            sf, text="Abrir el PDF al terminar",
            variable=self.var_abrir,
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        # --- Botón principal ---
        bf = ttk.Frame(main)
        bf.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(10, 6))
        self.btn = ttk.Button(bf, text="Generar informe PDF", command=self._lanzar)
        self.btn.pack(side="left")
        self.barra = ttk.Progressbar(bf, mode="indeterminate", length=220)
        self.barra.pack(side="left", padx=12)

        # --- Log ---
        lf = ttk.LabelFrame(main, text="Registro", padding=6)
        lf.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=(4, 4))
        main.rowconfigure(7, weight=1)
        self.log = scrolledtext.ScrolledText(lf, height=10, wrap="word", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")

        # --- Barra de estado ---
        ttk.Label(
            main, textvariable=self.var_estado,
            relief="sunken", anchor="w", padding=4,
        ).grid(row=8, column=0, columnspan=3, sticky="ew")

    # ------------------------------------------------------------------
    # Eventos
    # ------------------------------------------------------------------

    def _elegir_carpeta(self) -> None:
        carpeta = filedialog.askdirectory(initialdir=self.var_out.get())
        if carpeta:
            self.var_out.set(carpeta)

    def _emitir(self, nivel: str, msg: str) -> None:
        self._cola.put((nivel, msg))

    def _procesar_cola(self) -> None:
        while not self._cola.empty():
            nivel, msg = self._cola.get_nowait()
            self.log.configure(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            self.log.insert("end", f"[{ts}] {msg}\n")
            self.log.see("end")
            self.log.configure(state="disabled")
            self.var_estado.set(msg if nivel != "error" else f"ERROR: {msg}")
        self.root.after(150, self._procesar_cola)

    def _lanzar(self) -> None:
        if self._hilo and self._hilo.is_alive():
            return
        try:
            lat = float(self.var_lat.get())
            lon = float(self.var_lon.get())
            anios = int(self.var_anios.get())
            semilla = int(self.var_semilla.get())
            exp_dp = float(self.var_exp_dp.get())
            criterio = self.var_criterio.get()
            _t = str(self.var_t_diseno.get()).strip()
            t_diseno = int(_t) if _t.isdigit() else None
            obra_clave = self._obras.get(self.var_obra.get(), "carretera_puente")
            resolucion = self._resoluciones.get(self.var_resolucion.get(), "diaria")
            cn_disp = bool(self.var_cn.get())
            proyecto = DatosProyecto(
                self.var_proyecto.get(), self.var_ingeniero.get(),
                self.var_ubicacion.get(),
            )
            out = Path(self.var_out.get())
        except Exception as e:
            messagebox.showerror("Datos inválidos", f"Revise los parámetros.\n\n{e}")
            return
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            messagebox.showerror("Coordenadas inválidas", "Lat ∈ [-90, 90], Lon ∈ [-180, 180].")
            return
        if anios < 10:
            messagebox.showerror("Datos insuficientes", "Se requieren al menos 10 años.")
            return

        self.btn.state(["disabled"])
        self.barra.start(12)
        self._hilo = threading.Thread(
            target=self._correr_pipeline,
            args=(lat, lon, anios, semilla, exp_dp, criterio, t_diseno, obra_clave,
                  resolucion, cn_disp, proyecto, out),
            daemon=True,
        )
        self._hilo.start()

    # ------------------------------------------------------------------
    # Pipeline (corre en hilo de fondo)
    # ------------------------------------------------------------------

    def _correr_pipeline(self, lat, lon, anios, semilla, exp_dp, criterio,
                         t_diseno, obra_clave, resolucion, cn_disp, proyecto,
                         out_base: Path) -> None:
        try:
            tag = f"lat{lat:+.4f}_lon{lon:+.4f}".replace(".", "p")
            out = out_base / f"informe_{tag}"
            self._emitir("info", f"Carpeta de salida: {out}")
            self._emitir("info", f"Coordenadas: ({lat:.6f}, {lon:.6f}). Procesando…")

            R = ejecutar_pipeline(
                out, proyecto=proyecto, lat=lat, lon=lon,
                tipo_obra_clave=obra_clave, T_diseno=t_diseno,
                anios=anios, semilla=semilla, exp_dp=exp_dp, criterio=criterio,
                resolucion_datos=resolucion, cn_disponible=cn_disp,
            )
            self._emitir("info",
                         f"Estación: {R.estacion.codigo} {R.estacion.nombre} "
                         f"({R.dist_km:.1f} km).")
            self._emitir("info", f"Fuente adoptada: {R.decision.fuente_adoptada}.")
            self._emitir("info", f"Mejor distribución: {R.mejor_ajuste.nombre}.")
            self._emitir("info",
                         f"Modelo IDF recomendado ({R.resolucion_datos}): "
                         f"{R.modelo_recomendado.nombre} (R²={R.modelo_recomendado.r2:.4f}).")
            self._emitir("info", f"Tc adoptado = {R.tc_adoptado.tc_min:.1f} min.")
            self._emitir("info",
                         f"Hietograma T={R.T_diseno}: P={R.hietogramas['bloques'].p_total_mm:.1f} mm.")
            pdf = R.pdf
            self._emitir("info", f"PDF generado: {pdf} ({pdf.stat().st_size / 1024:.0f} KB).")

            if self.var_abrir.get():
                _abrir_externamente(pdf)
            self._cola.put(("info", "Listo. Informe finalizado correctamente."))
        except Exception as e:
            tb = traceback.format_exc()
            self._emitir("error", f"{e}")
            self._emitir("error", tb.splitlines()[-1])
        finally:
            self.root.after(0, self._finalizar)

    def _finalizar(self) -> None:
        self.barra.stop()
        self.btn.state(["!disabled"])


def main() -> None:
    root = Tk()
    IDFApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
