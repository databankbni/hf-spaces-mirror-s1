"""Metadatos de proyecto para la carátula del informe."""

from __future__ import annotations

from dataclasses import dataclass


APP_NOMBRE = "CURVAS IDF"
APP_VERSION = "1.3.0"


@dataclass
class DatosProyecto:
    nombre_proyecto: str = ""
    ingeniero: str = ""
    ubicacion: str = ""
    # Datos administrativos de nivel EDTP (Reglamento Básico de Preinversión).
    contratante: str = ""          # entidad contratante / promotora
    codigo_sisin: str = ""         # código SISIN (inversión pública)
    municipio: str = ""            # municipio
    provincia: str = ""            # provincia
    departamento: str = ""         # departamento
    registro_profesional: str = ""  # nº de registro SIB/SBP del especialista
    jefe_proyecto: str = ""        # jefe de proyecto

    def limpio(self) -> "DatosProyecto":
        def _l(v):
            return (v or "").strip()
        return DatosProyecto(
            nombre_proyecto=(self.nombre_proyecto or "—").strip(),
            ingeniero=(self.ingeniero or "—").strip(),
            ubicacion=(self.ubicacion or "—").strip(),
            contratante=_l(self.contratante),
            codigo_sisin=_l(self.codigo_sisin),
            municipio=_l(self.municipio),
            provincia=_l(self.provincia),
            departamento=_l(self.departamento),
            registro_profesional=_l(self.registro_profesional),
            jefe_proyecto=_l(self.jefe_proyecto),
        )
