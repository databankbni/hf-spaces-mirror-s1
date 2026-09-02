"""PDF -> raster -> OCR -> normalized OCRDocument.

Scope of this module, deliberately narrow:

  * rasterise every page of a PDF with pypdfium2;
  * run OCR on each raster with rapidocr-onnxruntime;
  * normalize the result into the `ocr_document` contract.

Not here, on purpose: field extraction, page prefiltering, deskew, PDF
validation, retrieval, LLMs, caching, benchmarking. This layer produces the
representation those stages will consume.

The whole document is always processed. There is no `max_pages`: a layer that
later has to support completeness and grounding guarantees must not offer a
convenient way to silently see less than the document.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from .ocr_document import (
    MalformedOCRRegion,
    OCRDocument,
    OCRPage,
    OCRRegion,
    make_region_id,
    regions_to_page_text,
)


DEFAULT_RASTER_DPI = 200


# An OCR callable takes a PIL image and returns raw engine regions, each shaped
# (polygon, text, confidence). Injectable so tests need no ONNX models.
OCRCallable = Callable[
    [Any],
    Iterable[Any],
]


# Progress events are intentionally generic and contain no UI dependency.
#
# Arguments:
#   stage
#   current page (1-based, or 0 for document-level events)
#   total pages
OCRProgressCallback = Callable[
    [str, int, int],
    None,
]


class OCRPipelineError(RuntimeError):
    """Document-level failure: the PDF could not be opened at all."""


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def compute_document_id(
    pdf_bytes: bytes,
) -> str:
    """Full SHA-256 hex digest of the source bytes. Not truncated."""

    return hashlib.sha256(
        pdf_bytes
    ).hexdigest()


# ---------------------------------------------------------------------------
# OCR engine (lazy, one per process)
# ---------------------------------------------------------------------------


_OCR_ENGINE = None


def get_ocr_engine():
    """Build the RapidOCR engine once per process.

    Imported lazily so that importing this module — for the contract, for tests,
    for a CLI --help — never pays the ONNX session cost.
    """

    global _OCR_ENGINE

    if _OCR_ENGINE is None:

        from rapidocr_onnxruntime import RapidOCR

        _OCR_ENGINE = RapidOCR()

    return _OCR_ENGINE


def rapidocr_ocr(
    pil_image,
) -> list[Any]:
    """Default OCR callable: RapidOCR on a PIL image, regions as returned."""

    import numpy as np

    engine = get_ocr_engine()

    result, _elapse = engine(
        np.array(
            pil_image
        )
    )

    return list(
        result or []
    )


# ---------------------------------------------------------------------------
# Page normalization
# ---------------------------------------------------------------------------


def normalize_page_regions(
    page_number: int,
    raw_regions: Iterable[Any],
) -> list[OCRRegion]:
    """Normalize one page's raw engine output.

    Raises MalformedOCRRegion (naming the offending region with the same 1-based
    number used in its region_id) rather than skipping, so the caller can mark
    the page as an error instead of losing regions quietly.
    """

    regions: list[
        OCRRegion
    ] = []

    for index, entry in enumerate(
        raw_regions
    ):

        region_number = (
            index + 1
        )

        try:
            polygon, text, confidence = entry

        except (
            TypeError,
            ValueError,
        ) as exc:

            raise MalformedOCRRegion(
                f"region {region_number} is not a "
                "(polygon, text, confidence) triple: "
                f"{type(entry).__name__} {_safe_repr(entry)}"
            ) from exc

        try:

            regions.append(
                OCRRegion.from_ocr(
                    region_id=make_region_id(
                        page_number,
                        region_number,
                    ),
                    polygon=polygon,
                    text=text,
                    confidence=confidence,
                )
            )

        except MalformedOCRRegion as exc:

            raise MalformedOCRRegion(
                f"region {region_number}: {exc}"
            ) from exc

    return regions


def _safe_repr(
    value: Any,
    limit: int = 200,
) -> str:
    """Bounded repr for error messages: never dump a whole page of data."""

    try:
        text = repr(
            value
        )

    except Exception:
        return (
            f"<unreprable "
            f"{type(value).__name__}>"
        )

    if len(text) <= limit:
        return text

    return (
        text[:limit]
        + "…"
    )


def _error_page(
    page_number: int,
    message: str,
    width: int | None,
    height: int | None,
) -> OCRPage:

    return OCRPage(
        page_number=page_number,
        width_px=width,
        height_px=height,
        status="error",
        error_message=message,
        text="",
        regions=[],
    )


def _emit_progress(
    callback: OCRProgressCallback | None,
    stage: str,
    current: int,
    total: int,
) -> None:
    """Emit one optional progress event."""

    if callback is None:
        return

    callback(
        stage,
        current,
        total,
    )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def ocr_pdf_bytes(
    pdf_bytes: bytes,
    source_name: str,
    raster_dpi: int = DEFAULT_RASTER_DPI,
    ocr_fn: OCRCallable | None = None,
    progress_callback: OCRProgressCallback | None = None,
) -> OCRDocument:
    """Normalize a whole PDF into an OCRDocument.

    One page is rasterised and OCR'd at a time; no more than a single page
    raster is held in memory.

    Per-page failures never remove a page: they become status="error" with an
    error_message, preserving 1-based numbering against the physical document.

    ``progress_callback`` is optional and UI-agnostic. It receives events for:

    - document_opened
    - rasterisation
    - ocr
    - normalisation
    - page_complete
    - document_complete
    """

    import pypdfium2 as pdfium

    if ocr_fn is None:
        ocr_fn = rapidocr_ocr

    try:

        pdf = pdfium.PdfDocument(
            pdf_bytes
        )

        n_pages = len(
            pdf
        )

    except Exception as exc:

        raise OCRPipelineError(
            f"could not open PDF "
            f"{source_name!r}: {exc}"
        ) from exc

    _emit_progress(
        progress_callback,
        "document_opened",
        0,
        n_pages,
    )

    pages: list[
        OCRPage
    ] = []

    scale = (
        raster_dpi
        / 72
    )

    for index in range(
        n_pages
    ):

        page_number = (
            index + 1
        )

        width_px: int | None = None
        height_px: int | None = None

        # -------------------------------------------------------------------
        # Rasterisation
        # -------------------------------------------------------------------

        _emit_progress(
            progress_callback,
            "rasterisation",
            page_number,
            n_pages,
        )

        try:

            pdf_page = pdf[
                index
            ]

            image = (
                pdf_page
                .render(
                    scale=scale
                )
                .to_pil()
                .convert("RGB")
            )

            width_px = int(
                image.width
            )

            height_px = int(
                image.height
            )

        except Exception as exc:

            pages.append(
                _error_page(
                    page_number,
                    (
                        "rasterisation failed: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                    None,
                    None,
                )
            )

            _emit_progress(
                progress_callback,
                "page_complete",
                page_number,
                n_pages,
            )

            continue

        # -------------------------------------------------------------------
        # OCR
        # -------------------------------------------------------------------

        _emit_progress(
            progress_callback,
            "ocr",
            page_number,
            n_pages,
        )

        try:

            raw_regions = ocr_fn(
                image
            )

        except Exception as exc:

            pages.append(
                _error_page(
                    page_number,
                    (
                        "OCR failed: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                    width_px,
                    height_px,
                )
            )

            _emit_progress(
                progress_callback,
                "page_complete",
                page_number,
                n_pages,
            )

            continue

        # -------------------------------------------------------------------
        # Normalisation
        # -------------------------------------------------------------------

        _emit_progress(
            progress_callback,
            "normalisation",
            page_number,
            n_pages,
        )

        try:

            regions = (
                normalize_page_regions(
                    page_number,
                    raw_regions,
                )
            )

        except MalformedOCRRegion as exc:

            pages.append(
                _error_page(
                    page_number,
                    (
                        "malformed OCR output, "
                        "page not normalized: "
                        f"{exc}"
                    ),
                    width_px,
                    height_px,
                )
            )

            _emit_progress(
                progress_callback,
                "page_complete",
                page_number,
                n_pages,
            )

            continue

        pages.append(
            OCRPage(
                page_number=page_number,
                width_px=width_px,
                height_px=height_px,
                status=(
                    "ok"
                    if regions
                    else "no_text"
                ),
                error_message=None,
                text=regions_to_page_text(
                    regions
                ),
                regions=regions,
            )
        )

        _emit_progress(
            progress_callback,
            "page_complete",
            page_number,
            n_pages,
        )

    _emit_progress(
        progress_callback,
        "document_complete",
        n_pages,
        n_pages,
    )

    return OCRDocument(
        document_id=compute_document_id(
            pdf_bytes
        ),
        source_name=source_name,
        page_count=len(
            pages
        ),
        raster_dpi=raster_dpi,
        pages=pages,
    )


def ocr_pdf(
    pdf_path: str | Path,
    raster_dpi: int = DEFAULT_RASTER_DPI,
    ocr_fn: OCRCallable | None = None,
    progress_callback: OCRProgressCallback | None = None,
) -> OCRDocument:
    """Normalize a PDF from disk. `source_name` is the file name only."""

    path = Path(
        pdf_path
    )

    if not path.is_file():

        raise OCRPipelineError(
            f"no such PDF: {path}"
        )

    return ocr_pdf_bytes(
        path.read_bytes(),
        source_name=path.name,
        raster_dpi=raster_dpi,
        ocr_fn=ocr_fn,
        progress_callback=progress_callback,
    )


# ---------------------------------------------------------------------------
# CLI — inspection only
# ---------------------------------------------------------------------------


def main(
    argv: list[str] | None = None,
) -> int:

    parser = argparse.ArgumentParser(
        description=(
            "Normalize a PDF into the OCR "
            "document representation."
        )
    )

    parser.add_argument(
        "pdf",
        help="path to a local PDF",
    )

    parser.add_argument(
        "--dpi",
        type=int,
        default=DEFAULT_RASTER_DPI,
        help="raster DPI",
    )

    parser.add_argument(
        "--json",
        dest="json_out",
        help="write the full result to this path",
    )

    args = parser.parse_args(
        argv
    )

    t0 = time.perf_counter()

    try:

        document = ocr_pdf(
            args.pdf,
            raster_dpi=args.dpi,
        )

    except OCRPipelineError as exc:

        print(
            f"error: {exc}",
            file=sys.stderr,
        )

        return 2

    elapsed = (
        time.perf_counter()
        - t0
    )

    counts = (
        document.status_counts
    )

    print(
        f"document_id : "
        f"{document.document_id}"
    )

    print(
        f"source_name : "
        f"{document.source_name}"
    )

    print(
        f"pages       : "
        f"{document.page_count}  "
        f"raster_dpi: "
        f"{document.raster_dpi}"
    )

    print(
        "status      : "
        f"ok={counts['ok']} "
        f"no_text={counts['no_text']} "
        f"error={counts['error']}"
    )

    print(
        f"regions     : "
        f"{document.region_count}"
    )

    print(
        f"elapsed     : "
        f"{elapsed:.2f}s "
        f"({elapsed / max(document.page_count, 1):.2f}s/page)"
    )

    for page in document.pages:

        head = (
            (
                page.text.splitlines()
                or [""]
            )[0][:70]
        )

        size = (
            f"{page.width_px}x{page.height_px}"
            if page.width_px
            else "unrendered"
        )

        print(
            f"  p{page.page_number:<3} "
            f"{page.status:<8} "
            f"{size:>11}  "
            f"{len(page.regions):>3} regions  "
            f"{head}"
        )

        if page.error_message:

            print(
                f"        error_message: "
                f"{page.error_message}"
            )

    if args.json_out:

        Path(
            args.json_out
        ).write_text(
            json.dumps(
                document.to_dict(),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        print(
            f"wrote {args.json_out}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )