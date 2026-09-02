"""Render OCR evidence and selected field evidence back onto PDF pages.

Three rendering modes are available:

1. ``render_evidence_pages``
   Legacy Phase 6 renderer.
   Renders only pages cited by extraction evidence.

2. ``render_annotated_document_pages``
   Legacy extraction-oriented full-document viewer.

3. ``render_verified_document_pages``
   Reviewer-facing verification viewer.
   Renders every page, all OCR regions, and highlights evidence selected by
   the SOBI catalogue verifier.

The renderer never trusts the copied bbox stored in EvidenceRef.
Every evidence region is resolved back to the authoritative OCRDocument.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw

from .document_verifier import DocumentVerification
from .extraction_result import ExtractionResult
from .ocr_document import OCRDocument, OCRRegion


class EvidenceRenderError(RuntimeError):
    """Raised when visual evidence cannot be rendered safely."""


# ---------------------------------------------------------------------------
# Display configuration
# ---------------------------------------------------------------------------

# The OCR itself can still run at 200 DPI.
#
# The annotated result viewer does not need to send 200-DPI images to the
# browser. Bounding boxes are rescaled from the authoritative OCR raster.
ANNOTATED_DISPLAY_DPI = 120


# Neutral OCR boxes.
OCR_BOX_COLOR = (155, 155, 155)

# Evidence actually supporting accepted extraction fields.
EVIDENCE_BOX_COLOR = (0, 145, 80)


FIELD_DISPLAY_NAMES = {
    "borehole_id": "Forage",
    "easting": "Easting",
    "northing": "Northing",
    "final_depth": "Profondeur finale",
}


# ---------------------------------------------------------------------------
# Authoritative OCR lookup
# ---------------------------------------------------------------------------


def _region_lookup(
    document: OCRDocument,
) -> dict[str, tuple[int, OCRRegion]]:
    """Map each OCR region id to its authoritative source page and region."""

    lookup: dict[
        str,
        tuple[int, OCRRegion],
    ] = {}

    for page in document.pages:

        for region in page.regions:

            if region.region_id in lookup:

                raise EvidenceRenderError(
                    f"duplicate OCR region id: {region.region_id}"
                )

            lookup[
                region.region_id
            ] = (
                page.page_number,
                region,
            )

    return lookup


def _evidence_by_page(
    document: OCRDocument,
    result: ExtractionResult,
) -> dict[
    int,
    list[
        tuple[
            str,
            OCRRegion,
        ]
    ],
]:
    """
    Resolve all selected field evidence to authoritative OCR regions.

    This helper preserves the semantics of the original Phase 6 evidence
    renderer.
    """

    lookup = _region_lookup(
        document
    )

    by_page: dict[
        int,
        list[
            tuple[
                str,
                OCRRegion,
            ]
        ],
    ] = defaultdict(list)

    seen: set[
        tuple[
            str,
            str,
        ]
    ] = set()

    for field in result.fields:

        for evidence in field.evidence:

            source = lookup.get(
                evidence.region_id
            )

            if source is None:

                raise EvidenceRenderError(
                    "evidence region not found in OCRDocument: "
                    f"{evidence.region_id}"
                )

            page_number, region = source

            if (
                page_number
                != evidence.page_number
            ):

                raise EvidenceRenderError(
                    f"page mismatch for {evidence.region_id}: "
                    f"result says page {evidence.page_number}, "
                    f"OCRDocument says page {page_number}"
                )

            key = (
                field.name,
                region.region_id,
            )

            if key in seen:
                continue

            seen.add(
                key
            )

            by_page[
                page_number
            ].append(
                (
                    field.name,
                    region,
                )
            )

    return dict(
        by_page
    )


def _accepted_evidence_by_page(
    document: OCRDocument,
    result: ExtractionResult,
) -> dict[
    int,
    dict[
        str,
        tuple[
            OCRRegion,
            set[str],
        ],
    ],
]:
    """
    Resolve evidence only for accepted extraction fields.

    Structure:

        page_number
            -> region_id
                -> (authoritative OCRRegion, {field names})

    A region can theoretically support more than one field, hence the set.
    """

    lookup = _region_lookup(
        document
    )

    by_page: dict[
        int,
        dict[
            str,
            tuple[
                OCRRegion,
                set[str],
            ],
        ],
    ] = defaultdict(dict)

    for field in result.fields:

        if field.status != "accepted":
            continue

        for evidence in field.evidence:

            source = lookup.get(
                evidence.region_id
            )

            if source is None:

                raise EvidenceRenderError(
                    "accepted evidence region not found in OCRDocument: "
                    f"{evidence.region_id}"
                )

            page_number, region = source

            if (
                page_number
                != evidence.page_number
            ):

                raise EvidenceRenderError(
                    f"page mismatch for {evidence.region_id}: "
                    f"result says page {evidence.page_number}, "
                    f"OCRDocument says page {page_number}"
                )

            existing = (
                by_page[
                    page_number
                ].get(
                    region.region_id
                )
            )

            if existing is None:

                by_page[
                    page_number
                ][
                    region.region_id
                ] = (
                    region,
                    {
                        field.name
                    },
                )

            else:

                existing[
                    1
                ].add(
                    field.name
                )

    return {
        page_number: dict(
            regions
        )
        for page_number, regions
        in by_page.items()
    }


def _verification_evidence_by_page(
    document: OCRDocument,
    verification: DocumentVerification,
) -> dict[
    int,
    dict[
        str,
        tuple[
            OCRRegion,
            set[str],
        ],
    ],
]:
    """Resolve selected verification evidence to authoritative OCR regions.

    Every field-level evidence item selected by the catalogue verifier is
    highlighted, including fields whose document value differs from SOBI.
    Green therefore means "used for verification", not "identical to SOBI".
    """

    lookup = _region_lookup(
        document
    )

    by_page: dict[
        int,
        dict[
            str,
            tuple[
                OCRRegion,
                set[str],
            ],
        ],
    ] = defaultdict(dict)

    for field in verification.fields:

        for evidence in field.evidence:

            source = lookup.get(
                evidence.region_id
            )

            if source is None:

                raise EvidenceRenderError(
                    "verification evidence region not found in OCRDocument: "
                    f"{evidence.region_id}"
                )

            page_number, region = source

            if (
                page_number
                != evidence.page_number
            ):

                raise EvidenceRenderError(
                    f"page mismatch for {evidence.region_id}: "
                    f"verification says page {evidence.page_number}, "
                    f"OCRDocument says page {page_number}"
                )

            existing = (
                by_page[
                    page_number
                ].get(
                    region.region_id
                )
            )

            if existing is None:

                by_page[
                    page_number
                ][
                    region.region_id
                ] = (
                    region,
                    {
                        field.name
                    },
                )

            else:

                existing[
                    1
                ].add(
                    field.name
                )

    return {
        page_number: dict(
            regions
        )
        for page_number, regions
        in by_page.items()
    }


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def _validate_result_document_pair(
    document: OCRDocument,
    result: ExtractionResult,
) -> None:
    """Ensure extraction result and OCR document refer to the same raster."""

    if (
        result.document_id
        != document.document_id
    ):

        raise EvidenceRenderError(
            "ExtractionResult and OCRDocument refer to different documents"
        )

    if (
        result.raster_dpi
        != document.raster_dpi
    ):

        raise EvidenceRenderError(
            "ExtractionResult and OCRDocument use different raster DPI values"
        )


def _validate_verification_document_pair(
    document: OCRDocument,
    verification: DocumentVerification,
) -> None:
    """Ensure verification evidence belongs to this OCR document."""

    if (
        verification.document_id
        != document.document_id
    ):

        raise EvidenceRenderError(
            "DocumentVerification and OCRDocument refer to different documents"
        )


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------


def _draw_label(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
) -> None:
    """
    Draw the original Phase 6 evidence label.

    Kept unchanged for backwards compatibility.
    """

    bbox = draw.textbbox(
        (x, y),
        text,
    )

    padding = 4

    left = (
        bbox[0]
        - padding
    )

    top = (
        bbox[1]
        - padding
    )

    right = (
        bbox[2]
        + padding
    )

    bottom = (
        bbox[3]
        + padding
    )

    draw.rectangle(
        [
            left,
            top,
            right,
            bottom,
        ],
        fill="white",
        outline="black",
    )

    draw.text(
        (x, y),
        text,
        fill="black",
    )


def _draw_evidence_label(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
) -> None:
    """Draw a compact green label for accepted extraction evidence."""

    bbox = draw.textbbox(
        (x, y),
        text,
    )

    padding = 4

    left = max(
        0,
        bbox[0]
        - padding,
    )

    top = max(
        0,
        bbox[1]
        - padding,
    )

    right = (
        bbox[2]
        + padding
    )

    bottom = (
        bbox[3]
        + padding
    )

    draw.rectangle(
        [
            left,
            top,
            right,
            bottom,
        ],
        fill="white",
        outline=EVIDENCE_BOX_COLOR,
        width=2,
    )

    draw.text(
        (x, y),
        text,
        fill=EVIDENCE_BOX_COLOR,
    )


def _scaled_box(
    region: OCRRegion,
    *,
    scale_x: float,
    scale_y: float,
) -> list[int]:
    """Scale an OCR-region bbox from OCR raster coordinates to display size."""

    x0, y0, x1, y1 = (
        region.bbox
    )

    return [
        int(
            round(
                x0
                * scale_x
            )
        ),
        int(
            round(
                y0
                * scale_y
            )
        ),
        int(
            round(
                x1
                * scale_x
            )
        ),
        int(
            round(
                y1
                * scale_y
            )
        ),
    ]


def _render_pdf_page(
    pdf,
    page_number: int,
    *,
    dpi: int,
) -> Image.Image:
    """Rasterise one 1-based PDF page and return a detached RGB PIL image."""

    try:

        pdf_page = pdf[
            page_number
            - 1
        ]

        try:

            bitmap = pdf_page.render(
                scale=dpi / 72.0
            )

            try:

                image = (
                    bitmap
                    .to_pil()
                    .convert("RGB")
                    .copy()
                )

            finally:
                bitmap.close()

        finally:
            pdf_page.close()

    except Exception as exc:

        raise EvidenceRenderError(
            f"could not rasterise page {page_number}: {exc}"
        ) from exc

    return image


# ---------------------------------------------------------------------------
# Legacy evidence-only renderer
# ---------------------------------------------------------------------------


def render_evidence_pages(
    pdf_path: str | Path,
    document: OCRDocument,
    result: ExtractionResult,
) -> list[
    tuple[
        Image.Image,
        str,
    ]
]:
    """
    Render only pages cited by the selected extraction evidence.

    This is the original Phase 6 renderer and is deliberately retained so
    existing call sites and tests continue to work.

    Returns Gradio-gallery-friendly ``(PIL image, caption)`` tuples.

    Bboxes come from the authoritative OCRDocument regions, not from copied
    EvidenceRef bbox values.
    """

    import pypdfium2 as pdfium

    path = Path(
        pdf_path
    )

    if not path.is_file():

        raise EvidenceRenderError(
            f"PDF not found: {path}"
        )

    _validate_result_document_pair(
        document,
        result,
    )

    evidence_pages = (
        _evidence_by_page(
            document,
            result,
        )
    )

    if not evidence_pages:
        return []

    try:

        pdf = pdfium.PdfDocument(
            str(path)
        )

    except Exception as exc:

        raise EvidenceRenderError(
            f"could not open PDF for evidence rendering: {exc}"
        ) from exc

    scale = (
        document.raster_dpi
        / 72
    )

    rendered: list[
        tuple[
            Image.Image,
            str,
        ]
    ] = []

    try:

        for page_number in sorted(
            evidence_pages
        ):

            if (
                page_number < 1
                or page_number > len(pdf)
            ):

                raise EvidenceRenderError(
                    f"evidence refers to missing PDF page {page_number}"
                )

            ocr_page = (
                document.pages[
                    page_number
                    - 1
                ]
            )

            try:

                pdf_page = pdf[
                    page_number
                    - 1
                ]

                try:

                    bitmap = (
                        pdf_page.render(
                            scale=scale
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
                    pdf_page.close()

            except Exception as exc:

                raise EvidenceRenderError(
                    "could not rasterise evidence page "
                    f"{page_number}: {exc}"
                ) from exc

            expected_size = (
                ocr_page.width_px,
                ocr_page.height_px,
            )

            actual_size = (
                image.size
            )

            if (
                None not in expected_size
                and actual_size
                != expected_size
            ):

                raise EvidenceRenderError(
                    f"rendered page {page_number} size "
                    f"{actual_size} does not match "
                    f"OCR raster size {expected_size}"
                )

            draw = (
                ImageDraw.Draw(
                    image
                )
            )

            line_width = max(
                3,
                image.width
                // 700,
            )

            labels: list[str] = []

            for (
                field_name,
                region,
            ) in evidence_pages[
                page_number
            ]:

                x0, y0, x1, y1 = (
                    region.bbox
                )

                box = [
                    int(
                        round(
                            x0
                        )
                    ),
                    int(
                        round(
                            y0
                        )
                    ),
                    int(
                        round(
                            x1
                        )
                    ),
                    int(
                        round(
                            y1
                        )
                    ),
                ]

                draw.rectangle(
                    box,
                    outline="red",
                    width=line_width,
                )

                label = (
                    f"{field_name} · "
                    f"{region.region_id}"
                )

                labels.append(
                    label
                )

                label_y = max(
                    2,
                    box[1]
                    - 20,
                )

                _draw_label(
                    draw,
                    max(
                        2,
                        box[0],
                    ),
                    label_y,
                    label,
                )

            caption = (
                f"Page {page_number} — "
                + ", ".join(
                    labels
                )
            )

            rendered.append(
                (
                    image,
                    caption,
                )
            )

    finally:
        pdf.close()

    return rendered


# ---------------------------------------------------------------------------
# Full annotated document renderer
# ---------------------------------------------------------------------------


def render_annotated_document_pages(
    pdf_path: str | Path,
    document: OCRDocument,
    result: ExtractionResult,
    *,
    display_dpi: int = ANNOTATED_DISPLAY_DPI,
) -> list[
    tuple[
        Image.Image,
        str,
    ]
]:
    """
    Render the complete PDF as an OCR/extraction inspection view.

    Every page is returned.

    Visual semantics:

    - grey box:
        OCR region detected in the source document

    - green box:
        authoritative OCR region used as supporting evidence for an
        ACCEPTED extraction field

    Only accepted extraction evidence is highlighted in green. Evidence
    associated with rejected / unsupported candidates remains visually neutral.

    The source OCR can have been produced at a higher DPI than the display
    image. Bounding boxes are therefore rescaled from the authoritative OCR
    raster dimensions to the display raster dimensions.

    Returns Gradio-gallery-friendly ``(PIL image, caption)`` tuples.
    """

    import pypdfium2 as pdfium

    path = Path(
        pdf_path
    )

    if not path.is_file():

        raise EvidenceRenderError(
            f"PDF not found: {path}"
        )

    if display_dpi <= 0:

        raise EvidenceRenderError(
            "display_dpi must be greater than zero"
        )

    _validate_result_document_pair(
        document,
        result,
    )

    accepted_evidence = (
        _accepted_evidence_by_page(
            document,
            result,
        )
    )

    try:

        pdf = pdfium.PdfDocument(
            str(path)
        )

    except Exception as exc:

        raise EvidenceRenderError(
            f"could not open PDF for annotated rendering: {exc}"
        ) from exc

    rendered: list[
        tuple[
            Image.Image,
            str,
        ]
    ] = []

    try:

        pdf_page_count = len(
            pdf
        )

        ocr_page_count = len(
            document.pages
        )

        if (
            pdf_page_count
            != ocr_page_count
        ):

            raise EvidenceRenderError(
                "PDF page count does not match OCRDocument page count: "
                f"PDF={pdf_page_count}, OCR={ocr_page_count}"
            )

        for page_index, ocr_page in enumerate(
            document.pages
        ):

            page_number = (
                page_index
                + 1
            )

            if (
                ocr_page.page_number
                != page_number
            ):

                raise EvidenceRenderError(
                    "OCRDocument page ordering is inconsistent: "
                    f"expected page {page_number}, "
                    f"found {ocr_page.page_number}"
                )

            if (
                ocr_page.width_px is None
                or ocr_page.height_px is None
                or ocr_page.width_px <= 0
                or ocr_page.height_px <= 0
            ):

                raise EvidenceRenderError(
                    f"OCR page {page_number} has no valid raster dimensions"
                )

            image = (
                _render_pdf_page(
                    pdf,
                    page_number,
                    dpi=display_dpi,
                )
            )

            scale_x = (
                image.width
                / ocr_page.width_px
            )

            scale_y = (
                image.height
                / ocr_page.height_px
            )

            # A pure DPI change should produce practically identical X/Y
            # scaling. A large discrepancy suggests that the rendered page no
            # longer corresponds geometrically to the OCR raster.
            scale_delta = abs(
                scale_x
                - scale_y
            )

            scale_reference = max(
                scale_x,
                scale_y,
            )

            if (
                scale_reference <= 0
                or scale_delta
                > (
                    0.02
                    * scale_reference
                )
            ):

                raise EvidenceRenderError(
                    f"display raster geometry for page {page_number} "
                    "does not match OCR raster geometry"
                )

            draw = (
                ImageDraw.Draw(
                    image
                )
            )

            # Thin neutral boxes for every OCR-detected region.
            ocr_line_width = max(
                1,
                image.width
                // 1200,
            )

            for region in ocr_page.regions:

                box = (
                    _scaled_box(
                        region,
                        scale_x=scale_x,
                        scale_y=scale_y,
                    )
                )

                draw.rectangle(
                    box,
                    outline=OCR_BOX_COLOR,
                    width=ocr_line_width,
                )

            # Accepted extraction evidence overlays the neutral OCR boxes.
            page_evidence = (
                accepted_evidence.get(
                    page_number,
                    {},
                )
            )

            evidence_line_width = max(
                3,
                image.width
                // 450,
            )

            page_field_names: set[
                str
            ] = set()

            for (
                region,
                field_names,
            ) in page_evidence.values():

                box = (
                    _scaled_box(
                        region,
                        scale_x=scale_x,
                        scale_y=scale_y,
                    )
                )

                draw.rectangle(
                    box,
                    outline=EVIDENCE_BOX_COLOR,
                    width=evidence_line_width,
                )

                page_field_names.update(
                    field_names
                )

                display_names = [
                    FIELD_DISPLAY_NAMES.get(
                        field_name,
                        field_name,
                    )
                    for field_name
                    in sorted(
                        field_names
                    )
                ]

                label = " / ".join(
                    display_names
                )

                label_y = max(
                    2,
                    box[1]
                    - 20,
                )

                _draw_evidence_label(
                    draw,
                    max(
                        2,
                        box[0],
                    ),
                    label_y,
                    label,
                )

            if page_field_names:

                caption_fields = [
                    FIELD_DISPLAY_NAMES.get(
                        field_name,
                        field_name,
                    )
                    for field_name
                    in sorted(
                        page_field_names
                    )
                ]

                caption = (
                    f"Page {page_number} / {pdf_page_count}"
                    " · Extraction : "
                    + ", ".join(
                        caption_fields
                    )
                )

            else:

                caption = (
                    f"Page {page_number} / {pdf_page_count}"
                )

            rendered.append(
                (
                    image,
                    caption,
                )
            )

    finally:
        pdf.close()

    return rendered


# ---------------------------------------------------------------------------
# Full verified document renderer
# ---------------------------------------------------------------------------


def render_verified_document_pages(
    pdf_path: str | Path,
    document: OCRDocument,
    verification: DocumentVerification,
    *,
    display_dpi: int = ANNOTATED_DISPLAY_DPI,
) -> list[
    tuple[
        Image.Image,
        str,
    ]
]:
    """
    Render the complete PDF as an OCR/verification inspection view.

    Every page is returned.

    Visual semantics:

    - grey box:
        OCR region detected in the source document

    - green box:
        authoritative OCR region selected as evidence by the catalogue
        verification engine

    A green region can support either an exact catalogue match or a measured
    difference. Green means "used for verification", not "identical to SOBI".

    The source OCR can have been produced at a higher DPI than the display
    image. Bounding boxes are therefore rescaled from the authoritative OCR
    raster dimensions to the display raster dimensions.

    Returns Gradio-gallery-friendly ``(PIL image, caption)`` tuples.
    """

    import pypdfium2 as pdfium

    path = Path(
        pdf_path
    )

    if not path.is_file():

        raise EvidenceRenderError(
            f"PDF not found: {path}"
        )

    if display_dpi <= 0:

        raise EvidenceRenderError(
            "display_dpi must be greater than zero"
        )

    _validate_verification_document_pair(
        document,
        verification,
    )

    verification_evidence = (
        _verification_evidence_by_page(
            document,
            verification,
        )
    )

    try:

        pdf = pdfium.PdfDocument(
            str(path)
        )

    except Exception as exc:

        raise EvidenceRenderError(
            f"could not open PDF for annotated rendering: {exc}"
        ) from exc

    rendered: list[
        tuple[
            Image.Image,
            str,
        ]
    ] = []

    try:

        pdf_page_count = len(
            pdf
        )

        ocr_page_count = len(
            document.pages
        )

        if (
            pdf_page_count
            != ocr_page_count
        ):

            raise EvidenceRenderError(
                "PDF page count does not match OCRDocument page count: "
                f"PDF={pdf_page_count}, OCR={ocr_page_count}"
            )

        for page_index, ocr_page in enumerate(
            document.pages
        ):

            page_number = (
                page_index
                + 1
            )

            if (
                ocr_page.page_number
                != page_number
            ):

                raise EvidenceRenderError(
                    "OCRDocument page ordering is inconsistent: "
                    f"expected page {page_number}, "
                    f"found {ocr_page.page_number}"
                )

            if (
                ocr_page.width_px is None
                or ocr_page.height_px is None
                or ocr_page.width_px <= 0
                or ocr_page.height_px <= 0
            ):

                raise EvidenceRenderError(
                    f"OCR page {page_number} has no valid raster dimensions"
                )

            image = (
                _render_pdf_page(
                    pdf,
                    page_number,
                    dpi=display_dpi,
                )
            )

            scale_x = (
                image.width
                / ocr_page.width_px
            )

            scale_y = (
                image.height
                / ocr_page.height_px
            )

            # A pure DPI change should produce practically identical X/Y
            # scaling. A large discrepancy suggests that the rendered page no
            # longer corresponds geometrically to the OCR raster.
            scale_delta = abs(
                scale_x
                - scale_y
            )

            scale_reference = max(
                scale_x,
                scale_y,
            )

            if (
                scale_reference <= 0
                or scale_delta
                > (
                    0.02
                    * scale_reference
                )
            ):

                raise EvidenceRenderError(
                    f"display raster geometry for page {page_number} "
                    "does not match OCR raster geometry"
                )

            draw = (
                ImageDraw.Draw(
                    image
                )
            )

            # Thin neutral boxes for every OCR-detected region.
            ocr_line_width = max(
                1,
                image.width
                // 1200,
            )

            for region in ocr_page.regions:

                box = (
                    _scaled_box(
                        region,
                        scale_x=scale_x,
                        scale_y=scale_y,
                    )
                )

                draw.rectangle(
                    box,
                    outline=OCR_BOX_COLOR,
                    width=ocr_line_width,
                )

            # Selected verification evidence overlays the neutral OCR boxes.
            page_evidence = (
                verification_evidence.get(
                    page_number,
                    {},
                )
            )

            evidence_line_width = max(
                3,
                image.width
                // 450,
            )

            page_field_names: set[
                str
            ] = set()

            for (
                region,
                field_names,
            ) in page_evidence.values():

                box = (
                    _scaled_box(
                        region,
                        scale_x=scale_x,
                        scale_y=scale_y,
                    )
                )

                draw.rectangle(
                    box,
                    outline=EVIDENCE_BOX_COLOR,
                    width=evidence_line_width,
                )

                page_field_names.update(
                    field_names
                )

                display_names = [
                    FIELD_DISPLAY_NAMES.get(
                        field_name,
                        field_name,
                    )
                    for field_name
                    in sorted(
                        field_names
                    )
                ]

                label = " / ".join(
                    display_names
                )

                label_y = max(
                    2,
                    box[1]
                    - 20,
                )

                _draw_evidence_label(
                    draw,
                    max(
                        2,
                        box[0],
                    ),
                    label_y,
                    label,
                )

            if page_field_names:

                caption_fields = [
                    FIELD_DISPLAY_NAMES.get(
                        field_name,
                        field_name,
                    )
                    for field_name
                    in sorted(
                        page_field_names
                    )
                ]

                caption = (
                    f"Page {page_number} / {pdf_page_count}"
                    " · Vérification : "
                    + ", ".join(
                        caption_fields
                    )
                )

            else:

                caption = (
                    f"Page {page_number} / {pdf_page_count}"
                )

            rendered.append(
                (
                    image,
                    caption,
                )
            )

    finally:
        pdf.close()

    return rendered