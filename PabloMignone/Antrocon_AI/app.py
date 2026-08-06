import json
import os
import re
from pathlib import Path
from typing import Any

import chromadb
import gradio as gr
from huggingface_hub import InferenceClient
from chromadb.utils import embedding_functions


# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================

# Directorio donde está guardado asistente_docente.py

# Directorio donde está guardado asistente_docente.py
PROJECT_DIR = Path(__file__).resolve().parent

# En el Space, los archivos TXT pueden quedar en la misma raíz que app.py.
# También se puede cambiar esta ubicación mediante la variable DOCS_DIR.
DOCS_DIR = Path(os.getenv("DOCS_DIR", str(PROJECT_DIR))).resolve()

# Chroma crea esta carpeta durante la ejecución del Space.
DB_PATH = PROJECT_DIR / "chroma_db"

# Se busca metadata.json primero junto a app.py y, para mantener
# compatibilidad con la versión local, también en configuracion/.
def resolver_metadata_path() -> Path:
    ruta_configurada = os.getenv("METADATA_PATH")
    if ruta_configurada:
        return Path(ruta_configurada).expanduser().resolve()

    candidatas = (
        PROJECT_DIR / "metadata.json",
        PROJECT_DIR / "configuracion" / "metadata.json",
    )

    for candidata in candidatas:
        if candidata.exists():
            return candidata

    # Devuelve la ubicación recomendada para que el mensaje de error
    # indique dónde debe cargarse el archivo.
    return PROJECT_DIR / "metadata.json"


METADATA_PATH = resolver_metadata_path()

COLLECTION_NAME = "bibliografia_clases"

EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
LLM_MODEL = os.getenv(
    "HF_MODEL",
    "Qwen/Qwen2.5-7B-Instruct",
)

HF_TOKEN = os.getenv("HF_TOKEN")

llm_client = InferenceClient(
    model=LLM_MODEL,
    token=HF_TOKEN,
)

TOP_K = 6
MAX_DISTANCE: float | None = 0.65

# True sólo una vez cuando cambies bibliografía o metadata.json.
REBUILD_DATABASE = os.getenv("REBUILD_DATABASE", "false").lower() == "true"

CHUNK_SIZE = 1400
CHUNK_OVERLAP = 250


# ============================================================
# INTERFAZ
# ============================================================

ASSETS_DIR = PROJECT_DIR / "assets"
BACKGROUND_IMAGE = ASSETS_DIR / "fondo.jpg"

custom_css = """
footer {
    visibility: hidden;
}

.gradio-container {
    font-size: 18px !important;
}

#encabezado {
    background: rgba(255, 255, 255, 0.93);
    border-radius: 14px;
    padding: 18px 22px;
    margin-bottom: 14px;
}

#output_res {
    font-size: 18px !important;
    line-height: 1.5 !important;
    min-height: 520px !important;
    overflow-y: auto !important;
    background-color: rgba(252, 252, 252, 0.96) !important;
    border-radius: 12px !important;
    padding: 14px !important;
}

#msg_in textarea {
    font-size: 18px !important;
    background-color: rgba(255, 255, 255, 0.96) !important;
}
"""

if BACKGROUND_IMAGE.exists():
    custom_css += """
    .gradio-container {
        background-image:
            linear-gradient(
                rgba(245, 242, 232, 0.86),
                rgba(245, 242, 232, 0.86)
            ),
            url('/gradio_api/file=assets/fondo.jpg');
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }
    """


# ============================================================
# UTILIDADES DE TEXTO
# ============================================================

def normalizar_texto(texto: str) -> str:
    """
    Limpia espacios repetidos sin eliminar la estructura básica
    del documento.
    """
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")

    # Reduce espacios horizontales repetidos.
    texto = re.sub(r"[ \t]+", " ", texto)

    # Reduce saltos de línea excesivos.
    texto = re.sub(r"\n{3,}", "\n\n", texto)

    return texto.strip()

def limpiar_basura_ocr(texto: str) -> str:
    """
    Elimina residuos frecuentes de OCR, encabezados y marcas
    temporales antes de dividir el documento en fragmentos.
    """
    lineas_limpias: list[str] = []

    patron_fecha_hora = re.compile(
        r"""
        \b
        \d{1,2}/\d{1,2}
        (?:/\d{2,4})?
        \s+
        \d{1,2}:\d{2}
        \s*
        (?:a\.?\s*m\.?|p\.?\s*m\.?)?
        \b
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    for linea in texto.splitlines():
        linea = linea.strip()

        if not linea:
            lineas_limpias.append("")
            continue

        linea = patron_fecha_hora.sub("", linea)

        # Líneas compuestas solamente por números o signos.
        if re.fullmatch(r"[\d\s\-–—.,:;/]+", linea):
            continue

        # Número de página aislado.
        if re.fullmatch(r"\d{1,4}", linea):
            continue

        minuscula = linea.lower()

        descartes = (
            "downloaded from",
            "copyright",
            "all rights reserved",
            "http://",
            "https://",
            "www.",
            "issn",
        )

        if any(expresion in minuscula for expresion in descartes):
            continue

        lineas_limpias.append(linea)

    texto_limpio = "\n".join(lineas_limpias)

    # Elimina también fechas y horas incrustadas dentro de una línea.
    texto_limpio = patron_fecha_hora.sub(
        " ",
        texto_limpio,
    )

    return texto_limpio

def dividir_texto(
    texto: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP
) -> list[str]:
    """
    Divide el texto procurando cortar al final de párrafos
    u oraciones e incorpora solapamiento entre fragmentos.
    """
    texto = normalizar_texto(texto)

    if not texto:
        return []

    chunks: list[str] = []
    inicio = 0
    longitud = len(texto)

    while inicio < longitud:
        fin_propuesto = min(inicio + chunk_size, longitud)
        fin = fin_propuesto

        if fin_propuesto < longitud:
            # Prioridad 1: corte al final de párrafo.
            corte_parrafo = texto.rfind(
                "\n\n",
                inicio + chunk_size // 2,
                fin_propuesto
            )

            # Prioridad 2: corte al final de oración.
            corte_oracion = texto.rfind(
                ". ",
                inicio + chunk_size // 2,
                fin_propuesto
            )

            if corte_parrafo != -1:
                fin = corte_parrafo + 2
            elif corte_oracion != -1:
                fin = corte_oracion + 1

        fragmento = texto[inicio:fin].strip()

        if fragmento:
            chunks.append(fragmento)

        if fin >= longitud:
            break

        nuevo_inicio = fin - overlap

        # Evita ciclos si el solapamiento fuera demasiado grande.
        if nuevo_inicio <= inicio:
            nuevo_inicio = fin

        inicio = nuevo_inicio

    return chunks


def nombre_legible_archivo(nombre: str) -> str:
    """
    Convierte el nombre técnico del archivo en una referencia
    más legible para mostrar en pantalla.
    """
    return Path(nombre).stem.replace("_", " ").strip()


# ============================================================
# CLASIFICACIÓN DEL TIPO DE CONSULTA
# ============================================================

def detectar_tipo_consulta(pregunta: str) -> str:
    """
    Clasifica la consulta para adaptar el formato de respuesta.
    """
    texto = pregunta.lower()

    palabras_didacticas = (
        "consigna",
        "consignas",
        "trabajo práctico",
        "trabajo practico",
        "actividad",
        "actividades",
        "guía de lectura",
        "guia de lectura",
        "preguntas para",
        "parcial",
        "evaluación",
        "evaluacion",
        "ejercicio",
        "ejercicios",
        "clase práctica",
        "clase practica",
    )

    palabras_comparacion = (
        "compará",
        "compara",
        "comparar",
        "comparación",
        "comparacion",
        "diferencia",
        "diferencias",
        "contrasta",
        "contrastar",
        "relación entre",
        "relacion entre",
        "coincidencias",
    )

    palabras_sintesis = (
        "resumí",
        "resume",
        "resumen",
        "síntesis",
        "sintesis",
        "sintetiza",
        "explica brevemente",
    )

    palabras_bibliograficas = (
        "qué dice",
        "que dice",
        "según",
        "segun",
        "autor",
        "autores",
        "bibliografía",
        "bibliografia",
        "texto",
        "artículo",
        "articulo",
    )

    if any(expresion in texto for expresion in palabras_didacticas):
        return "didactica"

    if any(expresion in texto for expresion in palabras_comparacion):
        return "comparacion"

    if any(expresion in texto for expresion in palabras_sintesis):
        return "sintesis"

    if any(expresion in texto for expresion in palabras_bibliograficas):
        return "bibliografica"

    return "conceptual"


def instrucciones_por_tipo(tipo: str) -> str:
    """
    Devuelve instrucciones particulares según el género de consulta.
    """
    if tipo == "didactica":
        return """
El usuario solicita una actividad docente.

Debés:
1. Formular un objetivo general breve.
2. Diseñar entre 4 y 6 consignas claras, numeradas y realizables.
3. Promover lectura crítica, comparación, argumentación y análisis
   de fuentes o interpretaciones.
4. Proponer una modalidad de trabajo.
5. Indicar criterios breves de evaluación.

No repitas el temario como si fuera una respuesta.
No conviertas cada título del programa en una definición.
Las consignas son propuestas didácticas tuyas: no las atribuyas
a los autores.
"""

    if tipo == "comparacion":
        return """
Organizá la respuesta en:
1. Coincidencias.
2. Diferencias.
3. Evidencias o fuentes utilizadas.
4. Problemas abiertos.

No mezcles a los autores como si sostuvieran una única posición.
Solo atribuí una idea cuando el contexto permita identificarla.
"""

    if tipo == "sintesis":
        return """
Elaborá una síntesis académica clara de entre 150 y 250 palabras.
Conservá los conceptos centrales y los matices de los autores.
No agregues información externa al contexto recuperado.
"""

    if tipo == "bibliografica":
        return """
Respondé identificando claramente qué autor o texto respalda cada
afirmación importante. Cuando el contexto no permita determinar
la autoría o la posición con seguridad, indicá esa limitación.
"""

    return """
Respondé en uno o dos párrafos académicos claros.
Definí los conceptos relevantes y explicá sus relaciones.
No agregues ejemplos o afirmaciones que no estén respaldados
por el contexto bibliográfico.
"""

def cargar_metadata(path: Path) -> dict[str, dict[str, Any]]:
    """
    Carga metadata.json y devuelve un diccionario cuya clave
    debe coincidir exactamente con el nombre real del archivo TXT.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"No se encontró el archivo de metadatos:\n{path}"
        )

    try:
        with path.open("r", encoding="utf-8") as archivo:
            metadata = json.load(archivo)

    except json.JSONDecodeError as error:
        raise ValueError(
            f"metadata.json contiene un error de formato:\n{error}"
        ) from error

    if not isinstance(metadata, dict):
        raise ValueError(
            "metadata.json debe contener un objeto JSON principal."
        )

    return metadata

# ============================================================
# MOTOR RAG
# ============================================================

class DocenciaRAG:
    def __init__(self) -> None:
        DB_PATH.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(path=str(DB_PATH))

        self.embedding_function = (
            embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=EMBEDDING_MODEL
            )
        )

        self.collection = self._obtener_coleccion()

    def _obtener_coleccion(self):
        return self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=self.embedding_function,
            metadata={"hnsw:space": "cosine"},
        )

    def reconstruir_coleccion(self) -> None:
        try:
            self.client.delete_collection(name=COLLECTION_NAME)
            print("🗑️ Colección anterior eliminada.")
        except Exception:
            pass

        self.collection = self._obtener_coleccion()

    def build(
        self,
        folder: Path,
        rebuild: bool = False,
    ) -> None:
        """Indexa únicamente los archivos autorizados en metadata.json."""
        folder.mkdir(parents=True, exist_ok=True)

        if rebuild:
            self.reconstruir_coleccion()

        if self.collection.count() > 0:
            print(
                f"📚 Base de datos cargada: "
                f"{self.collection.count()} fragmentos."
            )
            return

        metadata_documentos = cargar_metadata(METADATA_PATH)
        archivos = sorted(folder.glob("*.txt"))

        if not archivos:
            print(f"⚠️ No se encontraron archivos TXT en:\n{folder}")
            return

        print(f"📖 Indexando documentos en:\n{folder}")

        total_fragmentos = 0
        total_documentos = 0
        omitidos = 0
        sin_metadata = 0

        for archivo in archivos:
            datos = metadata_documentos.get(archivo.name)

            if datos is None:
                print(f"  ⚠️ Sin entrada en metadata.json: {archivo.name}")
                sin_metadata += 1
                continue

            if not datos.get("include", False):
                print(f"  ⏭️ Excluido por metadata.json: {archivo.name}")
                omitidos += 1
                continue

            autor = datos.get("author", "Autor no identificado")
            titulo = datos.get("title", "Título no identificado")
            anio = str(datos.get("year", "s. f."))
            tipo_documento = datos.get(
                "document_type",
                "no identificado",
            )

            temas = datos.get("themes", [])
            if not isinstance(temas, list):
                temas = [str(temas)]

            temas_texto = " | ".join(temas)
            estado = datos.get("status", "sin estado")

            try:
                texto = archivo.read_text(
                    encoding="utf-8",
                    errors="ignore",
                )
            except OSError as error:
                print(f"⚠️ No se pudo leer {archivo.name}: {error}")
                continue

            texto = limpiar_basura_ocr(texto)
            chunks = dividir_texto(texto)

            if not chunks:
                print(f"⚠️ Documento vacío o ilegible: {archivo.name}")
                continue

            ids: list[str] = []
            documents: list[str] = []
            metadatas: list[dict[str, Any]] = []

            for indice, fragmento in enumerate(chunks):
                identificador = f"{archivo.stem}_{indice:05d}"

                ids.append(identificador)
                documents.append(fragmento)
                metadatas.append({
                    "source": archivo.name,
                    "author": autor,
                    "title": titulo,
                    "year": anio,
                    "document_type": tipo_documento,
                    "themes": temas_texto,
                    "status": estado,
                    "chunk": indice,
                    "total_chunks": len(chunks),
                })

            self.collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )

            total_fragmentos += len(chunks)
            total_documentos += 1

            print(
                f"  ✅ {autor} — {titulo}: "
                f"{len(chunks)} fragmentos."
            )

        print()
        print(f"✅ Documentos indexados: {total_documentos}")
        print(f"✅ Fragmentos creados: {total_fragmentos}")
        print(f"⏭️ Documentos excluidos: {omitidos}")
        print(f"⚠️ Archivos sin metadata: {sin_metadata}")

    def search(
        self,
        query: str,
        n_results: int = TOP_K,
        document_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Recupera fragmentos y permite filtrar por tipo documental:
        - bibliografía académica
        - fuente histórica
        """
        if self.collection.count() == 0:
            return []

        parametros: dict[str, Any] = {
            "query_texts": [query],
            "n_results": min(
                n_results,
                self.collection.count()
            ),
            "include": [
                "documents",
                "metadatas",
                "distances",
            ],
        }

        if document_type is not None:
            parametros["where"] = {
                "document_type": document_type
            }

        try:
            results = self.collection.query(
                **parametros
            )
        except Exception as error:
            print(
                f"⚠️ Error en la búsqueda "
                f"({document_type or 'sin filtro'}): {error}"
            )
            return []

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        hits: list[dict[str, Any]] = []

        for document, metadata, distance in zip(
            documents,
            metadatas,
            distances,
        ):
            distancia = float(distance)

            if (
                MAX_DISTANCE is not None
                and distancia > MAX_DISTANCE
            ):
                continue


            print(
                f"🔎 {document_type or 'sin filtro'} | "
                f"distancia={distancia:.4f} | "
                f"{metadata.get('author')} — "
                f"{metadata.get('title')}"
            )

            hits.append({
                "text": document,
                "source": metadata.get(
                    "source",
                    "Archivo no identificado",
                ),
                "author": metadata.get(
                    "author",
                    "Autor no identificado",
                ),
                "title": metadata.get(
                    "title",
                    "Título no identificado",
                ),
                "year": metadata.get(
                    "year",
                    "s. f.",
                ),
                "document_type": metadata.get(
                    "document_type",
                    "no identificado",
                ),
                "themes": metadata.get(
                    "themes",
                    "",
                ),
                "chunk": metadata.get("chunk"),
                "distance": distancia,
            })

        return hits


rag = DocenciaRAG()


# ============================================================
# CONSTRUCCIÓN DEL CONTEXTO
# ============================================================

def construir_contexto_diferenciado(
    bibliografia: list[dict[str, Any]],
    fuentes_historicas: list[dict[str, Any]],
) -> str:
    """
    Organiza por separado interpretaciones académicas
    y fuentes históricas.
    """
    bloques: list[str] = []

    if bibliografia:
        bloques.append(
            "========================================\n"
            "BIBLIOGRAFÍA ACADÉMICA\n"
            "========================================"
        )

        for numero, hit in enumerate(
            bibliografia,
            start=1,
        ):
            bloques.append(
                f"[BIBLIOGRAFÍA {numero}]\n"
                f"AUTOR: {hit['author']}\n"
                f"TÍTULO: {hit['title']}\n"
                f"AÑO: {hit['year']}\n"
                f"TEMAS: {hit['themes']}\n"
                f"ARCHIVO: {hit['source']}\n"
                f"FRAGMENTO: {hit['chunk']}\n\n"
                f"TEXTO:\n"
                f"{hit['text'].strip()}"
            )

    if fuentes_historicas:
        bloques.append(
            "========================================\n"
            "FUENTES HISTÓRICAS\n"
            "========================================"
        )

        for numero, hit in enumerate(
            fuentes_historicas,
            start=1,
        ):
            bloques.append(
                f"[FUENTE HISTÓRICA {numero}]\n"
                f"AUTOR O PRODUCTOR: {hit['author']}\n"
                f"TÍTULO: {hit['title']}\n"
                f"FECHA: {hit['year']}\n"
                f"TEMAS: {hit['themes']}\n"
                f"ARCHIVO: {hit['source']}\n"
                f"FRAGMENTO: {hit['chunk']}\n\n"
                f"TEXTO:\n"
                f"{hit['text'].strip()}"
            )

    return "\n\n".join(bloques)


def construir_lista_referencias(
    bibliografia: list[dict[str, Any]],
    fuentes_historicas: list[dict[str, Any]],
) -> str:
    """
    Presenta por separado la bibliografía académica
    y las fuentes históricas recuperadas.
    """
    secciones: list[str] = []

    if bibliografia:
        referencias: list[str] = []
        vistos: set[str] = set()

        for hit in bibliografia:
            referencia = (
                f"{hit['author']} "
                f"({hit['year']}). "
                f"{hit['title']}."
            )

            if referencia not in vistos:
                vistos.add(referencia)
                referencias.append(
                    f"- {referencia}"
                )

        secciones.append(
            "### Bibliografía académica recuperada\n"
            + "\n".join(referencias)
        )

    if fuentes_historicas:
        referencias: list[str] = []
        vistos: set[str] = set()

        for hit in fuentes_historicas:
            referencia = (
                f"{hit['author']} "
                f"({hit['year']}). "
                f"{hit['title']}."
            )

            if referencia not in vistos:
                vistos.add(referencia)
                referencias.append(
                    f"- {referencia}"
                )

        secciones.append(
            "### Fuentes históricas recuperadas\n"
            + "\n".join(referencias)
        )

    if not secciones:
        return "No se identificaron referencias."

    return "\n\n".join(secciones)

def parece_respuesta_truncada(texto: str) -> bool:
    """
    Detecta finales claramente incompletos sin modificar
    la respuesta generada por el modelo.
    """
    if not texto:
        return True

    texto = texto.rstrip()

    finales_validos = (
        ".",
        "!",
        "?",
        ":",
        ";",
        ")",
        "]",
        "»",
        '"',
    )

    if texto.endswith(finales_validos):
        return False

    ultima_linea = texto.splitlines()[-1].strip()

    palabras_incompletas = (
        " de",
        " del",
        " la",
        " las",
        " los",
        " un",
        " una",
        " por",
        " para",
        " como",
        " que",
        " y",
        " o",
    )

    return (
        len(ultima_linea) < 80
        or ultima_linea.endswith(palabras_incompletas)
    )


def requiere_fuentes_historicas(pregunta: str) -> bool:
    texto = pregunta.lower()

    indicadores = (
        "fuente histórica",
        "fuentes históricas",
        "fuente primaria",
        "fuentes primarias",
        "crónica",
        "cronica",
        "cronista",
        "cronistas",
        "códice",
        "codice",
        "documento colonial",
        "testimonio",
        "según garcilaso",
        "según betanzos",
        "según cieza",
        "comparar fuentes",
        "analizar la fuente",
    )

    return any(
        indicador in texto
        for indicador in indicadores
    )


# ============================================================
# GENERACIÓN DE RESPUESTAS
# ============================================================

def responder(pregunta: str) -> str:
    pregunta = pregunta.strip()

    if not pregunta:
        return "Por favor, escribí una pregunta."

    tipo_consulta = detectar_tipo_consulta(pregunta)

    bibliografia = rag.search(
        query=pregunta,
        n_results=4,
        document_type="bibliografía académica",
    )

    if requiere_fuentes_historicas(pregunta):
        fuentes_historicas = rag.search(
            query=pregunta,
            n_results=3,
            document_type="fuente histórica",
        )
    else:
        fuentes_historicas = []


    if not bibliografia and not fuentes_historicas:
        return (
            "No encontré fragmentos suficientemente pertinentes "
            "en la bibliografía académica ni en las fuentes "
            "históricas incorporadas."
        )

    contexto = construir_contexto_diferenciado(
        bibliografia,
        fuentes_historicas,
    )

    fuentes = construir_lista_referencias(
        bibliografia,
        fuentes_historicas,
    )

    instrucciones = instrucciones_por_tipo(tipo_consulta)

    system_prompt = f"""
Sos el asistente académico de la asignatura
Procesos Sociales de América I.

Tu función es ayudar a estudiar y trabajar con la bibliografía
seleccionada por la cátedra.

REGLAS GENERALES:

1. Trabajá exclusivamente con el contexto bibliográfico
   proporcionado.
2. No inventes autores, obras, conceptos, argumentos, citas,
   páginas ni datos históricos.
3. No atribuyas una idea a un autor cuando el fragmento no permita
   identificar esa autoría.
4. No mezcles posiciones diferentes como si fueran una sola.
5. El contexto puede estar incompleto. Cuando no alcance para
   responder, explicá la limitación.
6. Distinguí entre las afirmaciones de los investigadores y las
   actividades didácticas que vos propongas.
7. Escribí en español académico claro, correcto y natural.
8. Evitá errores ortográficos, palabras inexistentes y frases
   truncadas.
9. No presentes la respuesta como una verdad absoluta cuando la
   bibliografía contenga debates o interpretaciones divergentes.
10. No digas que un tema no pertenece al programa solamente porque
    no apareció en los fragmentos recuperados. Decí, en cambio,
    que no encontraste apoyo suficiente en el contexto disponible.
11. Distinguí siempre entre bibliografía académica y fuentes
    históricas.
12. La bibliografía académica contiene interpretaciones,
    reconstrucciones y debates de investigadores.
13. Las fuentes históricas son documentos producidos en contextos
    específicos. No las presentes como descripciones neutrales
    o transparentes de los hechos.
14. Cuando utilices una fuente histórica, identificá, cuando el
    contexto lo permita, su autor o productor, su fecha, su posición
    o contexto de producción y el problema para el cual resulta
    pertinente.
15. No atribuyas a una fuente histórica una interpretación formulada
    por un investigador moderno.
16. No presentes a cronistas, documentos coloniales e investigadores
    contemporáneos como autores equivalentes.
17. Cuando aparezcan ambos tipos documentales, organizá la respuesta
    diferenciando:
    a) la interpretación de la bibliografía académica;
    b) la evidencia o representación presente en las fuentes;
    c) la relación crítica entre ambas.
18. La coincidencia regional no implica pertinencia temática.
    Un texto sobre los mexicas no puede utilizarse para explicar
    específicamente el Estado maya, salvo que el fragmento establezca
    explícitamente una comparación pertinente.
19. Si el contexto recuperado no contiene información suficiente
    sobre la sociedad, historia o Estado maya, indicá que la
    bibliografía disponible no permite desarrollar adecuadamente
    la consulta. No sustituyas el tema maya por información mexica
    o andina.
20. Cuando la consulta incluya varios componentes, indicá cuáles
    pueden responderse con el contexto recuperado y cuáles no.
    No uses una explicación general sobre Mesoamérica para afirmar
    que se ha explicado específicamente el Estado maya.

INSTRUCCIONES PARA ESTA CONSULTA:

{instrucciones}
"""

    user_prompt = f"""
CONTEXTO DOCUMENTAL RECUPERADO:

{contexto}

CONSULTA:

{pregunta}
"""

    try:
        if not HF_TOKEN:
            return (
                "⚠️ No se encontró el secreto HF_TOKEN. "
                "Configurá un token de Hugging Face en "
                "Settings → Variables and secrets del Space."
            )

        response = llm_client.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            max_tokens=900,
            temperature=0.2,
            top_p=0.9,
        )

        contenido = response.choices[0].message.content.strip()

        if not contenido:
            return (
                "El modelo no produjo una respuesta. "
                "Intentá reformular la consulta."
            )

        if parece_respuesta_truncada(contenido):
            contenido += (
                "\n\n⚠️ La respuesta parece haber quedado "
                "incompleta. Repetí la consulta o pedí una "
                "respuesta más breve."
            )

        return (
            f"{contenido}\n\n"
            f"{fuentes}"
        )

    except Exception as error:
        return (
            "⚠️ Error al generar la respuesta:\n"
            f"{type(error).__name__}: {error}"
        )


# ============================================================
# FUNCIONES DE INTERFAZ
# ============================================================

def limpiar_campos():
    return "", ""


# ============================================================
# INTERFAZ GRADIO
# ============================================================

with gr.Blocks(
    title="Asistente de Cátedra"
) as demo:

    gr.Markdown(
        "# 🎓 Asistente: Procesos Sociales de América I\n"
        "Consulta guiada de la bibliografía y las fuentes "
        "seleccionadas por la cátedra.",
        elem_id="encabezado",
    )

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 🛠️ Panel de consulta")

            msg_in = gr.Textbox(
                label="Tu pregunta",
                placeholder=(
                    "Ejemplo: compará las definiciones de "
                    "Etnohistoria presentes en la bibliografía."
                ),
                lines=7,
                elem_id="msg_in"
            )

            with gr.Row():
                btn_limpiar = gr.Button(
                    "🗑️ Limpiar"
                )

                btn_consultar = gr.Button(
                    "🔍 Consultar",
                    variant="primary"
                )

        with gr.Column(scale=2):
            gr.Markdown(
                "### 🤖 Respuesta del asistente"
            )

            output_res = gr.Markdown(
                value="",
                elem_id="output_res"
            )

    btn_consultar.click(
        fn=responder,
        inputs=msg_in,
        outputs=output_res,
        show_progress="full"
    )

    # También permite enviar con Enter.
    msg_in.submit(
        fn=responder,
        inputs=msg_in,
        outputs=output_res,
        show_progress="full"
    )

    btn_limpiar.click(
        fn=limpiar_campos,
        inputs=[],
        outputs=[msg_in, output_res]
    )

    with gr.Accordion("ℹ️ Cómo usar el asistente", open=False):
        gr.Markdown(
            "- Formulá preguntas conceptuales o comparativas.\n"
            "- Para consultar crónicas o documentos coloniales, "
            "mencioná explícitamente la fuente histórica.\n"
            "- Verificá las respuestas en los textos recuperados.\n"
            "- Las respuestas del asistente no sustituyen la "
            "bibliografía ni deben citarse como fuente."
        )

    gr.Examples(
        examples=[
            [
                "Compará las definiciones de Etnohistoria "
                "presentes en la bibliografía."
            ],
            [
                "¿Cómo se relacionan reciprocidad y "
                "redistribución en los Andes?"
            ],
            [
                "Compará una fuente histórica andina con una "
                "mesoamericana sobre legitimación del poder."
            ],
        ],
        inputs=msg_in,
    )


# ============================================================
# EJECUCIÓN
# ============================================================

if __name__ == "__main__":
    DOCS_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print(f"📁 Carpeta de documentos: {DOCS_DIR}")
    print(f"🗂️ Metadatos: {METADATA_PATH}")
    print(f"🤖 Modelo remoto: {LLM_MODEL}")

    rag.build(
        DOCS_DIR,
        rebuild=REBUILD_DATABASE
    )

    allowed_paths: list[str] = []
    if ASSETS_DIR.exists():
        allowed_paths.append(str(ASSETS_DIR.resolve()))

    demo.launch(
        css=custom_css,
        allowed_paths=allowed_paths,
    )
