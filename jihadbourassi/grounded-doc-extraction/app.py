"""Interface reviewer-facing de vérification documentaire SOBI."""

from __future__ import annotations

import html
import random
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import gradio as gr
import pypdfium2 as pdfium

from src.document_verifier import (
    DocumentVerification,
    verify_document,
)
from src.ocr_pipeline import (
    OCRPipelineError,
    ocr_pdf,
)
from src.bgs_client import (
    BGSClientError,
    download_scan,
    get_record_by_bgs_id,
    search_records,
)
from src.domain_config import load_config
from src.evidence_renderer import (
    EvidenceRenderError,
    render_verified_document_pages,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent

EXAMPLE_PATH = (
    ROOT
    / "examples"
    / "623562_NJ35NE18367-129.pdf"
)

KNOWN_EXAMPLE_BGS_ID = "623562"
KNOWN_EXAMPLE_REFERENCE = "NJ35NE18367/129"

PREVIEW_DPI = 90
EXTRACTION_DPI = 150

_CFG = load_config()


FIELD_LABELS = {
    "borehole_id": "Référence du forage",
    "easting": "Easting",
    "northing": "Northing",
    "final_depth": "Profondeur finale",
}


# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------

CUSTOM_CSS = """
.document-card {
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    padding: 14px 18px;
    margin-top: 4px;
    margin-bottom: 14px;
    background: #fafafa;
}

.document-card-label {
    font-size: 0.84rem;
    color: #6b7280;
    margin-bottom: 4px;
}

.document-card-title {
    font-size: 1.18rem;
    font-weight: 700;
    line-height: 1.35;
    margin-bottom: 5px;
}

.document-card-name {
    font-size: 0.92rem;
    color: #374151;
    margin-bottom: 5px;
}

.document-card-meta {
    font-size: 0.90rem;
    color: #6b7280;
}

.viewer-legend {
    font-size: 0.90rem;
    margin-top: 2px;
}

#run-verification-button {
    margin-top: 8px;
}

#another-document-button {
    margin-top: 10px;
}
"""


# ---------------------------------------------------------------------------
# Document courant
# ---------------------------------------------------------------------------


def _make_document(
    *,
    path: str | Path,
    display_name: str,
    source: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:

    return {
        "item_id": uuid.uuid4().hex,
        "path": str(path),
        "display_name": display_name,
        "source": source,
        "metadata": dict(
            metadata or {}
        ),
    }


def _initial_document() -> dict[str, Any]:

    if not EXAMPLE_PATH.exists():

        raise FileNotFoundError(
            f"Exemple introuvable : "
            f"{EXAMPLE_PATH}"
        )

    return _make_document(
        path=EXAMPLE_PATH,
        display_name=EXAMPLE_PATH.name,
        source="BGS public example",
        metadata={
            "bgs_id": KNOWN_EXAMPLE_BGS_ID,
            "reference": KNOWN_EXAMPLE_REFERENCE,
        },
    )


INITIAL_DOCUMENT = (
    _initial_document()
)


# ---------------------------------------------------------------------------
# Viewer PDF
# ---------------------------------------------------------------------------


def get_pdf_page_count(
    pdf_path: str | Path,
) -> int | None:

    try:

        document = (
            pdfium.PdfDocument(
                str(
                    pdf_path
                )
            )
        )

        try:
            return len(
                document
            )

        finally:
            document.close()

    except Exception:
        return None


def render_pdf_pages(
    pdf_path: str | Path,
):
    """Rasterise toutes les pages pour la visualisation.

    Aucun OCR n'est exécuté ici.
    """

    document = (
        pdfium.PdfDocument(
            str(
                pdf_path
            )
        )
    )

    rendered_pages = []

    try:

        page_count = len(
            document
        )

        for page_index in range(
            page_count
        ):

            page = document[
                page_index
            ]

            try:

                bitmap = page.render(
                    scale=(
                        PREVIEW_DPI
                        / 72.0
                    )
                )

                try:

                    image = (
                        bitmap
                        .to_pil()
                        .convert(
                            "RGB"
                        )
                        .copy()
                    )

                finally:
                    bitmap.close()

            finally:
                page.close()

            rendered_pages.append(
                (
                    image,
                    (
                        f"Page "
                        f"{page_index + 1} "
                        f"/ {page_count}"
                    ),
                )
            )

    finally:
        document.close()

    return rendered_pages


def _raw_viewer_update(
    pages,
):

    return gr.Gallery(
        value=pages,
        label="Rapport de forage",
        columns=1,
        rows=None,
        height=520,
        object_fit="contain",
        allow_preview=True,
        interactive=False,
        format="png",
        visible=True,
    )


def _annotated_viewer_update(
    pages,
):

    return gr.Gallery(
        value=pages,
        label=(
            "Rapport analysé — "
            "OCR et vérification"
        ),
        columns=1,
        rows=None,
        height=520,
        object_fit="contain",
        allow_preview=True,
        interactive=False,
        format="png",
        visible=True,
    )


# ---------------------------------------------------------------------------
# Carte du document
# ---------------------------------------------------------------------------


def _document_html(
    item: dict[str, Any],
) -> str:

    metadata = item.get(
        "metadata",
        {},
    )

    bgs_id = metadata.get(
        "bgs_id"
    )

    reference = metadata.get(
        "reference"
    )

    name = metadata.get(
        "name"
    )

    page_count = (
        get_pdf_page_count(
            item[
                "path"
            ]
        )
    )

    title = (
        reference
        or item[
            "display_name"
        ]
    )

    meta_parts: list[
        str
    ] = []

    if bgs_id:

        meta_parts.append(
            f"BGS ID {bgs_id}"
        )

    if page_count is not None:

        meta_parts.append(
            f"{page_count} page"
            f"{'s' if page_count != 1 else ''}"
        )

    meta_parts.append(
        "Source : BGS / SOBI"
    )

    safe_title = html.escape(
        str(
            title
        )
    )

    safe_meta = (
        " &nbsp;·&nbsp; ".join(
            html.escape(
                str(
                    value
                )
            )
            for value
            in meta_parts
        )
    )

    name_html = ""

    if name:

        name_html = (
            '<div class="document-card-name">'
            + html.escape(
                str(
                    name
                )
            )
            + "</div>"
        )

    return f"""
    <div class="document-card">
        <div class="document-card-label">
            Rapport sélectionné
        </div>

        <div class="document-card-title">
            {safe_title}
        </div>

        {name_html}

        <div class="document-card-meta">
            {safe_meta}
        </div>
    </div>
    """


# ---------------------------------------------------------------------------
# Catalogue SOBI
# ---------------------------------------------------------------------------


def _catalogue_metadata(
    item: dict[str, Any],
) -> tuple[
    dict[str, Any],
    bool,
]:

    metadata = dict(
        item.get(
            "metadata",
            {},
        )
    )

    bgs_id = metadata.get(
        "bgs_id"
    )

    has_catalogue_values = any(
        metadata.get(
            key
        ) is not None
        for key in (
            "easting",
            "northing",
            "length_m",
        )
    )

    if (
        bgs_id
        and not has_catalogue_values
    ):

        try:

            record = (
                get_record_by_bgs_id(
                    bgs_id
                )
            )

        except Exception:
            record = None

        if record:

            metadata.update(
                record
            )

    catalogue_available = any(
        metadata.get(
            key
        ) is not None
        for key in (
            "reference",
            "easting",
            "northing",
            "length_m",
        )
    )

    return (
        metadata,
        catalogue_available,
    )


# ---------------------------------------------------------------------------
# Formatage
# ---------------------------------------------------------------------------


def _format_number(
    value: Any,
    *,
    unit: str = "",
) -> str:

    if value is None:
        return "—"

    try:
        number = float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):
        return str(
            value
        )

    if number.is_integer():

        text = str(
            int(
                number
            )
        )

    else:

        text = (
            f"{number:.2f}"
            .rstrip(
                "0"
            )
            .rstrip(
                "."
            )
        )

    if unit:
        return (
            f"{text} {unit}"
        )

    return text


def _format_verification_value(
    field_name: str,
    value: Any,
) -> str:
    """Format a catalogue or document value for the reviewer table."""

    if value is None:
        return "—"

    if field_name in {
        "easting",
        "northing",
        "final_depth",
    }:

        return _format_number(
            value,
            unit="m",
        )

    return str(
        value
    )


def _format_signed_difference(
    difference: Any,
) -> str:

    try:

        number = float(
            difference
        )

    except (
        TypeError,
        ValueError,
    ):

        return "—"

    sign = (
        "+"
        if number > 0
        else "−"
        if number < 0
        else ""
    )

    magnitude = abs(
        number
    )

    if magnitude.is_integer():

        text = str(
            int(
                magnitude
            )
        )

    else:

        text = (
            f"{magnitude:.2f}"
            .rstrip(
                "0"
            )
            .rstrip(
                "."
            )
        )

    return (
        f"{sign}{text} m"
    )


def _verification_status(
    field,
) -> str:
    """Reviewer-facing status for one catalogue/document comparison."""

    if field.status == "exact_match":

        if field.name == "borehole_id":
            return "✅ Correspondance exacte"

        return "✅ Correspondance"

    if field.status == "local_id_match":

        return "✅ Identifiant local retrouvé"

    if field.status == "fuzzy_match":

        return "⚠️ Correspondance approximative"

    if field.status == "different":

        if field.difference is None:
            return "⚠️ Valeur différente"

        return (
            "⚠️ Écart "
            + _format_signed_difference(
                field.difference
            )
        )

    if field.status == "not_available":

        return "— Non disponible"

    if field.status == "not_found":

        return "❌ Non trouvée"

    return "⚠️ À examiner"


def _business_summary(
    verification: DocumentVerification,
) -> str:
    """Human-readable verification summary without treating SOBI as ground truth."""

    fields = list(
        verification.fields
    )

    matched = [
        field
        for field in fields
        if (
            field.matched_value
            is not None
            and field.status
            not in {
                "not_found",
                "not_available",
            }
        )
    ]

    parts: list[
        str
    ] = []

    if (
        fields
        and len(
            matched
        )
        == len(
            fields
        )
    ):

        parts.append(
            "✅ **Vérification terminée :** "
            "une correspondance documentaire a été identifiée "
            "pour les quatre informations du catalogue."
        )

    elif matched:

        parts.append(
            f"⚠️ **Vérification partielle :** "
            f"{len(matched)}/{len(fields)} informations "
            "ont une correspondance documentaire."
        )

    else:

        parts.append(
            "❌ **Aucune correspondance documentaire exploitable "
            "n'a été identifiée.**"
        )

    coordinate_differences = []

    for field_name, label in (
        (
            "easting",
            "Easting",
        ),
        (
            "northing",
            "Northing",
        ),
    ):

        try:

            field = verification.field(
                field_name
            )

        except KeyError:

            continue

        if (
            field.status == "different"
            and field.difference
            is not None
        ):

            coordinate_differences.append(
                (
                    label,
                    _format_signed_difference(
                        field.difference
                    ),
                )
            )

    if coordinate_differences:

        if len(
            coordinate_differences
        ) == 2:

            first_label, first_difference = (
                coordinate_differences[
                    0
                ]
            )

            second_label, second_difference = (
                coordinate_differences[
                    1
                ]
            )

            parts.append(
                "⚠️ Les coordonnées présentes dans le document "
                "diffèrent du catalogue SOBI : "
                f"**{first_difference} en {first_label}** "
                f"et **{second_difference} en {second_label}**."
            )

        else:

            label, difference = (
                coordinate_differences[
                    0
                ]
            )

            parts.append(
                "⚠️ La coordonnée présente dans le document "
                "diffère du catalogue SOBI : "
                f"**{difference} en {label}**."
            )

    return "\n\n".join(
        parts
    )


def _result_markdown(
    verification: DocumentVerification,
    total_seconds: float,
    ocr_seconds: float,
    verification_seconds: float,
    viewer_warning: str = "",
) -> str:

    rows = [
        "## Résultat de la vérification",
        "",
        (
            "| Champ | Catalogue SOBI | "
            "Valeur trouvée dans le document | Vérification |"
        ),
        "|---|---:|---:|---|",
    ]

    for field in verification.fields:

        label = (
            FIELD_LABELS.get(
                field.name,
                field.name,
            )
        )

        rows.append(
            f"| **{label}** "
            f"| {_format_verification_value(field.name, field.catalogue_value)} "
            f"| {_format_verification_value(field.name, field.matched_value)} "
            f"| {_verification_status(field)} |"
        )

    rows.extend(
        [
            "",
            _business_summary(
                verification
            ),
            "",
            (
                "*Les métadonnées imprimées dans le bandeau BGS "
                "sont exclues de la vérification afin d'éviter "
                "de comparer le catalogue avec une copie de ses "
                "propres informations.*"
            ),
            "",
            (
                "*SOBI sert ici de référence externe de comparaison. "
                "Un écart avec le catalogue n'implique pas à lui seul "
                "que la valeur présente dans le document est erronée.*"
            ),
            "",
            (
                f"Temps de traitement : "
                f"**{total_seconds:.1f} s** "
                f"· OCR : "
                f"{ocr_seconds:.1f} s "
                f"· Vérification : "
                f"{verification_seconds:.2f} s"
            ),
        ]
    )

    if viewer_warning:

        rows.extend(
            [
                "",
                f"⚠️ {viewer_warning}",
            ]
        )

    return "\n".join(
        rows
    )


# ---------------------------------------------------------------------------
# Progression
# ---------------------------------------------------------------------------


def _update_processing_progress(
    progress,
    stage: str,
    current: int,
    total: int,
) -> None:
    """Map real OCR events onto the reviewer-facing progress bar."""

    total_pages = max(
        int(
            total
        ),
        1,
    )

    # 0 - 5%   preparation
    # 5 - 86%  page-by-page OCR
    # 86 - 92% catalogue loading
    # 92 - 95% document verification
    # 95 -100% annotated rendering / final result

    ocr_start = 0.05
    ocr_end = 0.86
    ocr_span = (
        ocr_end
        - ocr_start
    )

    if stage == "document_opened":

        progress(
            0.04,
            desc=(
                f"Document ouvert — "
                f"{total_pages} page"
                f"{'s' if total_pages != 1 else ''}"
            ),
        )

        return

    if stage in {
        "rasterisation",
        "ocr",
        "normalisation",
        "page_complete",
    }:

        page_number = max(
            1,
            min(
                int(
                    current
                ),
                total_pages,
            ),
        )

        page_span = (
            ocr_span
            / total_pages
        )

        page_base = (
            ocr_start
            + (
                page_number
                - 1
            )
            * page_span
        )

        if stage == "rasterisation":

            value = page_base

            description = (
                f"Page {page_number}/{total_pages} "
                "— rasterisation"
            )

        elif stage == "ocr":

            value = (
                page_base
                + (
                    page_span
                    * 0.08
                )
            )

            description = (
                f"Page {page_number}/{total_pages} "
                "— analyse OCR"
            )

        elif stage == "normalisation":

            value = (
                page_base
                + (
                    page_span
                    * 0.94
                )
            )

            description = (
                f"Page {page_number}/{total_pages} "
                "— normalisation du texte"
            )

        else:

            value = (
                page_base
                + page_span
            )

            description = (
                f"Page {page_number}/{total_pages} "
                "— terminée"
            )

        progress(
            min(
                value,
                ocr_end,
            ),
            desc=description,
        )

        return

    if stage == "document_complete":

        progress(
            0.86,
            desc="Analyse OCR terminée",
        )


# ---------------------------------------------------------------------------
# Traitement
# ---------------------------------------------------------------------------


def start_processing():

    return (
        (
            "### Vérification en cours…\n\n"
            "Le rapport est en cours d'analyse."
        ),

        gr.Markdown(
            value="",
            visible=False,
        ),

        gr.Button(
            "Vérifier les données",
            variant="primary",
            visible=False,
        ),

        gr.Button(
            "Tester un autre rapport public",
            visible=False,
        ),

        gr.Markdown(
            value="",
            visible=False,
        ),
    )


def _processing_error_outputs(
    current_document: dict[str, Any],
    message: str,
):

    try:

        raw_pages = (
            render_pdf_pages(
                current_document[
                    "path"
                ]
            )
        )

    except Exception:

        raw_pages = []

    return (
        "",

        _raw_viewer_update(
            raw_pages
        ),

        gr.Markdown(
            value="",
            visible=False,
        ),

        gr.Markdown(
            value=(
                "## Le document n'a pas pu être vérifié\n\n"
                f"{message}\n\n"
                "Vous pouvez essayer un autre rapport public."
            ),
            visible=True,
        ),

        gr.Button(
            "Vérifier les données",
            variant="primary",
            visible=False,
        ),

        gr.Button(
            "Tester un autre rapport public",
            visible=True,
        ),
    )


def run_current_document(
    current_document: dict[str, Any],
    progress=gr.Progress(),
):

    started = (
        time.perf_counter()
    )

    progress(
        0.01,
        desc="Démarrage de l'analyse",
    )

    progress(
        0.02,
        desc="Préparation du document",
    )

    def on_ocr_stage(
        stage: str,
        current: int,
        total: int,
    ) -> None:

        _update_processing_progress(
            progress,
            stage,
            current,
            total,
        )

    # -----------------------------------------------------------------------
    # OCR
    # -----------------------------------------------------------------------

    try:

        ocr_started = (
            time.perf_counter()
        )

        document = ocr_pdf(
            current_document[
                "path"
            ],
            raster_dpi=EXTRACTION_DPI,
            progress_callback=on_ocr_stage,
        )

        ocr_seconds = (
            time.perf_counter()
            - ocr_started
        )

    except OCRPipelineError:

        return (
            _processing_error_outputs(
                current_document,
                (
                    "La lecture du PDF ou "
                    "l'analyse OCR a échoué."
                ),
            )
        )

    except Exception:

        return (
            _processing_error_outputs(
                current_document,
                (
                    "Une erreur inattendue s'est produite "
                    "pendant l'analyse OCR."
                ),
            )
        )

    # -----------------------------------------------------------------------
    # SOBI metadata
    # -----------------------------------------------------------------------

    progress(
        0.88,
        desc="Chargement des données du catalogue SOBI",
    )

    catalogue_metadata, catalogue_available = (
        _catalogue_metadata(
            current_document
        )
    )

    if not catalogue_available:

        return (
            _processing_error_outputs(
                current_document,
                (
                    "Les données SOBI nécessaires à la "
                    "vérification ne sont pas disponibles."
                ),
            )
        )

    # -----------------------------------------------------------------------
    # Verification
    # -----------------------------------------------------------------------

    progress(
        0.92,
        desc=(
            "Recherche des correspondances "
            "dans le document"
        ),
    )

    try:

        verification_started = (
            time.perf_counter()
        )

        verification = verify_document(
            document,
            catalogue_metadata,
            _CFG,
        )

        verification_seconds = (
            time.perf_counter()
            - verification_started
        )

    except Exception:

        return (
            _processing_error_outputs(
                current_document,
                (
                    "L'OCR a réussi, mais la vérification "
                    "des données n'a pas pu être terminée."
                ),
            )
        )

    # -----------------------------------------------------------------------
    # Annotated viewer
    # -----------------------------------------------------------------------

    viewer_warning = ""

    progress(
        0.95,
        desc="Génération du document annoté",
    )

    try:

        annotated_pages = (
            render_verified_document_pages(
                current_document[
                    "path"
                ],
                document,
                verification,
            )
        )

        viewer_update = (
            _annotated_viewer_update(
                annotated_pages
            )
        )

    except EvidenceRenderError:

        viewer_warning = (
            "La vérification a réussi, mais le document "
            "annoté n'a pas pu être affiché."
        )

        try:

            raw_pages = (
                render_pdf_pages(
                    current_document[
                        "path"
                    ]
                )
            )

        except Exception:

            raw_pages = []

        viewer_update = (
            _raw_viewer_update(
                raw_pages
            )
        )

    elapsed = (
        time.perf_counter()
        - started
    )

    progress(
        1.0,
        desc="Vérification terminée",
    )

    return (
        "",

        viewer_update,

        gr.Markdown(
            value=(
                "**Légende :** "
                "⬜ zones de texte détectées par OCR "
                "· 🟩 preuves utilisées pour la vérification"
            ),
            visible=True,
        ),

        gr.Markdown(
            value=_result_markdown(
                verification,
                elapsed,
                ocr_seconds,
                verification_seconds,
                viewer_warning,
            ),
            visible=True,
        ),

        gr.Button(
            "Vérifier les données",
            variant="primary",
            visible=False,
        ),

        gr.Button(
            "Tester un autre rapport public",
            visible=True,
        ),
    )


# ---------------------------------------------------------------------------
# Nouveau rapport public
# ---------------------------------------------------------------------------


def choose_random_document(
    current_document: dict[str, Any],
    progress=gr.Progress(),
):

    progress(
        0,
        desc=(
            "Recherche d'un autre "
            "rapport public"
        ),
    )

    try:

        records = search_records(
            n=5,
            seed=random.randint(
                1,
                2_000_000_000,
            ),
            type_filter="bh",
        )

        if not records:

            raise BGSClientError(
                "Aucun rapport public disponible."
            )

        output_dir = Path(
            tempfile.mkdtemp(
                prefix=(
                    "grounded_public_"
                )
            )
        )

        current_bgs_id = str(
            current_document
            .get(
                "metadata",
                {},
            )
            .get(
                "bgs_id",
                "",
            )
        )

        selected_item = None
        selected_pages = None

        for record in records:

            bgs_id = str(
                record.get(
                    "bgs_id",
                    "",
                )
            )

            if not bgs_id:
                continue

            if (
                bgs_id
                == current_bgs_id
            ):
                continue

            try:

                path = download_scan(
                    bgs_id=bgs_id,
                    output_dir=output_dir,
                    scan_url=record.get(
                        "scan_url"
                    ),
                )

                pages = (
                    render_pdf_pages(
                        path
                    )
                )

                if not pages:
                    continue

                selected_item = (
                    _make_document(
                        path=path,
                        display_name=Path(
                            path
                        ).name,
                        source="BGS/SOBI",
                        metadata=record,
                    )
                )

                selected_pages = pages

                break

            except (
                BGSClientError,
                ValueError,
                RuntimeError,
            ):
                continue

        if selected_item is None:

            raise BGSClientError(
                "Aucun rapport exploitable "
                "n'a été trouvé."
            )

    except Exception:

        try:

            current_pages = (
                render_pdf_pages(
                    current_document[
                        "path"
                    ]
                )
            )

        except Exception:
            current_pages = []

        return (
            current_document,

            _document_html(
                current_document
            ),

            _raw_viewer_update(
                current_pages
            ),

            (
                "### Impossible de charger un autre rapport\n\n"
                "Le service public BGS est temporairement "
                "indisponible ou aucun scan exploitable "
                "n'a été trouvé."
            ),

            gr.Markdown(
                value="",
                visible=False,
            ),

            gr.Markdown(
                value="",
                visible=False,
            ),

            gr.Button(
                "Vérifier les données",
                variant="primary",
                visible=False,
            ),

            gr.Button(
                "Tester un autre rapport public",
                visible=True,
            ),
        )

    return (
        selected_item,

        _document_html(
            selected_item
        ),

        _raw_viewer_update(
            selected_pages
        ),

        "",

        gr.Markdown(
            value="",
            visible=False,
        ),

        gr.Markdown(
            value="",
            visible=False,
        ),

        gr.Button(
            "Vérifier les données",
            variant="primary",
            visible=True,
        ),

        gr.Button(
            "Tester un autre rapport public",
            visible=False,
        ),
    )


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


HEADER = """
# Vérification documentaire des données SOBI

Cette application vérifie la cohérence entre des **données enregistrées dans le catalogue SOBI** et les informations présentes dans les **rapports de forage scannés correspondants**.

Le cas présenté ici utilise des documents publics du **Single Onshore Borehole Index (SOBI)** du British Geological Survey (BGS).

Pour chaque rapport, l'application analyse le document par OCR puis recherche les meilleures correspondances pour quatre informations du catalogue : **la référence du forage**, ses coordonnées **Easting** et **Northing**, ainsi que sa **profondeur finale**.

Les zones utilisées pour la vérification sont mises en évidence dans le document. Les valeurs trouvées sont ensuite comparées aux données SOBI afin de faire apparaître les correspondances et les éventuels écarts.
"""


FOOTER = """
---

**À propos**

La vérification part des valeurs enregistrées dans SOBI et recherche leurs meilleures correspondances dans le corps du rapport scanné.

Les métadonnées ajoutées par BGS autour du scan sont exclues de cette recherche afin d'éviter une comparaison circulaire avec le catalogue.

Source des documents : British Geological Survey (BGS).

Contains British Geological Survey materials © UKRI 2026.
"""


initial_pages = (
    render_pdf_pages(
        INITIAL_DOCUMENT[
            "path"
        ]
    )
)


with gr.Blocks(
    title=(
        "Vérification documentaire "
        "des données SOBI"
    ),
) as demo:

    current_document_state = (
        gr.State(
            INITIAL_DOCUMENT
        )
    )

    gr.Markdown(
        HEADER
    )

    document_card = gr.HTML(
        value=_document_html(
            INITIAL_DOCUMENT
        )
    )

    document_viewer = gr.Gallery(
        value=initial_pages,
        label="Rapport de forage",
        columns=1,
        rows=None,
        height=520,
        object_fit="contain",
        allow_preview=True,
        interactive=False,
        format="png",
    )

    viewer_legend = gr.Markdown(
        visible=False,
        elem_classes=[
            "viewer-legend"
        ],
    )

    run_button = gr.Button(
        "Vérifier les données",
        variant="primary",
        elem_id=(
            "run-verification-button"
        ),
    )

    run_status = gr.Markdown()

    result_output = gr.Markdown(
        visible=False
    )

    another_button = gr.Button(
        "Tester un autre rapport public",
        visible=False,
        elem_id=(
            "another-document-button"
        ),
    )

    gr.Markdown(
        FOOTER
    )

    run_button.click(
        fn=start_processing,
        inputs=None,
        outputs=[
            run_status,
            result_output,
            run_button,
            another_button,
            viewer_legend,
        ],

    ).then(
        fn=run_current_document,
        inputs=current_document_state,
        outputs=[
            run_status,
            document_viewer,
            viewer_legend,
            result_output,
            run_button,
            another_button,
        ],
        show_progress="full",
        show_progress_on=run_status,
    )

    another_button.click(
        fn=choose_random_document,
        inputs=current_document_state,
        outputs=[
            current_document_state,
            document_card,
            document_viewer,
            run_status,
            viewer_legend,
            result_output,
            run_button,
            another_button,
        ],
    )


if __name__ == "__main__":
    demo.launch(
        css=CUSTOM_CSS,
    )