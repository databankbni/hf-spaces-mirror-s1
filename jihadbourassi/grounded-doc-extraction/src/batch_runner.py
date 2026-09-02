"""Small sequential batch runner for document extraction.

Phase 6.5:
document basket -> OCR once per document -> expert extraction -> summary rows.

This module deliberately contains:
- no Gradio code;
- no BGS/network code;
- no evidence image rendering.

Visual evidence is rendered only when a user inspects one result.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .domain_config import DomainConfig
from .expert_extractor import extract
from .extraction_result import ExtractionResult
from .ocr_document import OCRDocument
from .ocr_pipeline import (
    OCRPipelineError,
    ocr_pdf,
)


# Existing document-level progress callback.
# Kept for backwards compatibility.
ProgressCallback = Callable[
    [int, int, str],
    None,
]


# Fine-grained processing-stage callback.
#
# Arguments:
#   stage
#   current
#   total
#   document display name
StageProgressCallback = Callable[
    [str, int, int, str],
    None,
]


@dataclass
class BatchInput:
    """One document selected in the application basket."""

    item_id: str
    path: str
    display_name: str
    source: str
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass
class BatchDocumentResult:
    """Processing outcome for one basket item."""

    item: BatchInput
    status: str
    document: OCRDocument | None = None
    result: ExtractionResult | None = None
    ocr_seconds: float | None = None
    extraction_seconds: float | None = None
    error: str | None = None

    @property
    def accepted_count(
        self,
    ) -> int:

        if self.result is None:
            return 0

        return sum(
            field.status == "accepted"
            for field in self.result.fields
        )

    def accepted_value(
        self,
        field_name: str,
    ) -> Any:

        if self.result is None:
            return None

        try:
            field = self.result.field(
                field_name
            )

        except KeyError:
            return None

        return field.accepted_value

    def summary_row(
        self,
    ) -> dict[str, Any]:
        """Compact row suitable for a batch-results table."""

        if (
            self.status != "ok"
            or self.result is None
        ):

            return {
                "item_id": self.item.item_id,
                "document": self.item.display_name,
                "source": self.item.source,
                "method": "expert",
                "borehole_id": None,
                "easting": None,
                "northing": None,
                "final_depth": None,
                "accepted_fields": "0/4",
                "ocr_s": None,
                "extraction_s": None,
                "status": "error",
                "error": self.error,
            }

        return {
            "item_id": self.item.item_id,
            "document": self.item.display_name,
            "source": self.item.source,
            "method": self.result.method,
            "borehole_id": self.accepted_value(
                "borehole_id"
            ),
            "easting": self.accepted_value(
                "easting"
            ),
            "northing": self.accepted_value(
                "northing"
            ),
            "final_depth": self.accepted_value(
                "final_depth"
            ),
            "accepted_fields": (
                f"{self.accepted_count}/"
                f"{len(self.result.fields)}"
            ),
            "ocr_s": (
                None
                if self.ocr_seconds is None
                else round(
                    self.ocr_seconds,
                    2,
                )
            ),
            "extraction_s": (
                None
                if self.extraction_seconds is None
                else round(
                    self.extraction_seconds,
                    3,
                )
            ),
            "status": "ok",
            "error": None,
        }


def _emit_stage(
    callback: StageProgressCallback | None,
    stage: str,
    current: int,
    total: int,
    item: BatchInput,
) -> None:

    if callback is None:
        return

    callback(
        stage,
        current,
        total,
        item.display_name,
    )


def _process_one(
    item: BatchInput,
    config: DomainConfig,
    raster_dpi: int,
    stage_callback: StageProgressCallback | None = None,
) -> BatchDocumentResult:
    """Process one item without allowing its failure to stop the batch."""

    path = Path(
        item.path
    )

    if not path.is_file():

        return BatchDocumentResult(
            item=item,
            status="error",
            error=f"file not found: {path}",
        )

    if path.suffix.lower() != ".pdf":

        return BatchDocumentResult(
            item=item,
            status="error",
            error=(
                "unsupported file type; "
                "expected PDF"
            ),
        )

    _emit_stage(
        stage_callback,
        "preparing",
        0,
        1,
        item,
    )

    # -----------------------------------------------------------------------
    # OCR
    # -----------------------------------------------------------------------

    try:

        started = (
            time.perf_counter()
        )

        if stage_callback is None:

            # Preserve the original call shape when no detailed progress
            # callback is requested. This also keeps older test doubles and
            # monkeypatches compatible.
            document = ocr_pdf(
                path,
                raster_dpi=raster_dpi,
            )

        else:

            def ocr_progress(
                stage: str,
                current: int,
                total: int,
            ) -> None:

                _emit_stage(
                    stage_callback,
                    stage,
                    current,
                    total,
                    item,
                )

            document = ocr_pdf(
                path,
                raster_dpi=raster_dpi,
                progress_callback=ocr_progress,
            )

        ocr_seconds = (
            time.perf_counter()
            - started
        )

        _emit_stage(
            stage_callback,
            "ocr_complete",
            1,
            1,
            item,
        )

    except OCRPipelineError as exc:

        _emit_stage(
            stage_callback,
            "error",
            1,
            1,
            item,
        )

        return BatchDocumentResult(
            item=item,
            status="error",
            error=(
                f"OCR pipeline error: {exc}"
            ),
        )

    except Exception as exc:

        _emit_stage(
            stage_callback,
            "error",
            1,
            1,
            item,
        )

        return BatchDocumentResult(
            item=item,
            status="error",
            error=(
                f"OCR error: "
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        )

    # -----------------------------------------------------------------------
    # Extraction
    # -----------------------------------------------------------------------

    try:

        _emit_stage(
            stage_callback,
            "extraction",
            0,
            1,
            item,
        )

        started = (
            time.perf_counter()
        )

        result = extract(
            document,
            config,
        )

        extraction_seconds = (
            time.perf_counter()
            - started
        )

        _emit_stage(
            stage_callback,
            "extraction_complete",
            1,
            1,
            item,
        )

    except Exception as exc:

        _emit_stage(
            stage_callback,
            "error",
            1,
            1,
            item,
        )

        return BatchDocumentResult(
            item=item,
            status="error",
            document=document,
            ocr_seconds=ocr_seconds,
            error=(
                "extraction error: "
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        )

    return BatchDocumentResult(
        item=item,
        status="ok",
        document=document,
        result=result,
        ocr_seconds=ocr_seconds,
        extraction_seconds=extraction_seconds,
        error=None,
    )


def run_batch(
    items: list[BatchInput],
    config: DomainConfig,
    *,
    raster_dpi: int = 200,
    progress_callback: ProgressCallback | None = None,
    stage_callback: StageProgressCallback | None = None,
) -> list[BatchDocumentResult]:
    """Process basket items sequentially.

    ``progress_callback`` keeps the original document-level callback.

    ``stage_callback`` provides detailed events from OCR and extraction.

    One document failure is recorded in its own result and does not stop
    subsequent documents.
    """

    results: list[
        BatchDocumentResult
    ] = []

    total = len(
        items
    )

    for index, item in enumerate(
        items,
        start=1,
    ):

        if progress_callback is not None:

            progress_callback(
                index,
                total,
                item.display_name,
            )

        if stage_callback is None:

            results.append(
                _process_one(
                    item=item,
                    config=config,
                    raster_dpi=raster_dpi,
                )
            )

        else:

            results.append(
                _process_one(
                    item=item,
                    config=config,
                    raster_dpi=raster_dpi,
                    stage_callback=stage_callback,
                )
            )

    return results


def summary_rows(
    results: list[BatchDocumentResult],
) -> list[dict[str, Any]]:
    """Return compact table rows for all processed documents."""

    return [
        result.summary_row()
        for result in results
    ]