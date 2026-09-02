"""Normalized OCR document representation.

This module is the *contract*. It knows nothing about PDFs, RapidOCR, extraction,
retrieval or models — it only defines the shape that every downstream stage
(extractors, grounding, evidence rendering, caching) will agree on.

Coordinate convention
---------------------
All polygon and bbox coordinates are in **pixels of the rasterised page image
that was actually sent to OCR**, with origin at the top-left. They are therefore
only meaningful together with `OCRDocument.raster_dpi`, which is why that field
lives on the document rather than being left implicit.

Why the polygon is preserved
----------------------------
RapidOCR returns a quadrilateral per detected region. Collapsing it immediately
to an axis-aligned rectangle destroys orientation information that later phases
need (deskew, evidence highlighting on tilted scans). So the polygon is stored
as returned and `bbox` is *derived* from it, in exactly one place.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

PageStatus = Literal["ok", "no_text", "error"]

VALID_PAGE_STATUSES: tuple[str, ...] = ("ok", "no_text", "error")


class MalformedOCRRegion(ValueError):
    """Raised when an OCR engine returns a region this layer cannot normalize.

    Deliberately an exception rather than a silent skip: this project is about
    traceability, so information loss must be observable. The pipeline turns
    this into a page with `status="error"` and a populated `error_message`.
    """


# ---------------------------------------------------------------------------
# bbox derivation — the single source of truth
# ---------------------------------------------------------------------------


def normalize_polygon(polygon: Any) -> list[list[float]]:
    """Coerce an engine polygon into plain nested Python floats.

    Accepts anything point-sequence-shaped (lists, tuples, numpy arrays) and
    returns JSON-safe data. numpy float32 coordinates are a real occurrence with
    ONNX-based engines and would otherwise leak into `json.dumps` as an error.
    """
    if polygon is None:
        raise MalformedOCRRegion("polygon is None")

    try:
        points = list(polygon)
    except TypeError as exc:
        raise MalformedOCRRegion(f"polygon is not iterable: {type(polygon).__name__}") from exc

    if len(points) < 3:
        raise MalformedOCRRegion(f"polygon needs at least 3 points, got {len(points)}")

    cleaned: list[list[float]] = []
    for index, point in enumerate(points):
        try:
            coords = list(point)
        except TypeError as exc:
            raise MalformedOCRRegion(
                f"polygon point {index} is not iterable: {type(point).__name__}"
            ) from exc
        if len(coords) != 2:
            raise MalformedOCRRegion(
                f"polygon point {index} must have 2 coordinates, got {len(coords)}"
            )
        try:
            x, y = float(coords[0]), float(coords[1])
        except (TypeError, ValueError) as exc:
            raise MalformedOCRRegion(f"polygon point {index} has non-numeric coordinates") from exc
        if not math.isfinite(x) or not math.isfinite(y):
            raise MalformedOCRRegion(
                f"polygon point {index} is not finite: ({coords[0]!r}, {coords[1]!r})"
            )
        cleaned.append([x, y])
    return cleaned


def bbox_from_polygon(polygon: Any) -> list[float]:
    """Axis-aligned bounding box of a polygon: [x0, y0, x1, y1].

    Computed over *all* vertices, not the first and third — a rotated
    quadrilateral has no guarantee that any two opposite points bound it.
    """
    points = normalize_polygon(polygon)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


@dataclass
class OCRRegion:
    """One region of text as detected by the OCR engine.

    `bbox` is always derived from `polygon`; it is never supplied by a caller.
    """

    region_id: str
    text: str
    confidence: float
    polygon: list[list[float]]
    bbox: list[float]

    @classmethod
    def from_ocr(
        cls,
        region_id: str,
        polygon: Any,
        text: Any,
        confidence: Any,
    ) -> "OCRRegion":
        """Build a region from raw engine output, deriving the bbox.

        Raises MalformedOCRRegion if the engine output cannot be normalized.
        """
        normalized = normalize_polygon(polygon)
        try:
            score = float(confidence)
        except (TypeError, ValueError) as exc:
            raise MalformedOCRRegion(
                f"confidence is not numeric: {type(confidence).__name__}"
            ) from exc
        if not math.isfinite(score):
            raise MalformedOCRRegion(f"confidence is not finite: {confidence!r}")
        if text is None:
            raise MalformedOCRRegion("text is None")
        return cls(
            region_id=region_id,
            text=str(text),
            # Not rounded: this is the canonical representation, so the engine's
            # own precision is preserved. Any display rounding belongs in the UI.
            confidence=score,
            polygon=normalized,
            bbox=bbox_from_polygon(normalized),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "text": self.text,
            "confidence": self.confidence,
            "polygon": [[float(x), float(y)] for x, y in self.polygon],
            "bbox": [float(v) for v in self.bbox],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OCRRegion":
        """Rebuild a region from serialized data, re-deriving the bbox.

        Deserialization must not be a back door around the invariant that bbox
        is a function of polygon. The stored bbox is therefore recomputed, and a
        stored value that disagrees is rejected rather than trusted — a file
        whose bbox no longer matches its polygon is corrupt or tampered with,
        and silently preferring either one would break evidence provenance.
        """
        region = cls.from_ocr(
            region_id=str(data["region_id"]),
            polygon=data["polygon"],
            text=data["text"],
            confidence=data["confidence"],
        )
        stored = data.get("bbox")
        if stored is not None:
            try:
                stored_values = [float(v) for v in stored]
            except (TypeError, ValueError) as exc:
                raise ValueError(f"bbox is not numeric: {stored!r}") from exc
            if len(stored_values) != 4 or not all(
                math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6)
                for a, b in zip(stored_values, region.bbox)
            ):
                raise ValueError(
                    f"serialized bbox {stored_values} does not match the bbox derived "
                    f"from the polygon {region.bbox} for region {region.region_id!r}"
                )
        return region


@dataclass
class OCRPage:
    """One page of the document, kept even when it yielded no text.

    Pages are never dropped: a page that failed to rasterise or whose OCR output
    could not be normalized becomes `status="error"` with an `error_message`, so
    that `page_number` stays aligned with the physical document and
    `page_count == len(pages)` always holds.

    `width_px`/`height_px` are the dimensions of the raster actually sent to OCR,
    and are None only when rasterisation itself failed.
    """

    page_number: int
    width_px: int | None
    height_px: int | None
    status: PageStatus
    error_message: str | None = None
    text: str = ""
    regions: list[OCRRegion] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.page_number < 1:
            raise ValueError(f"page_number must be 1-based, got {self.page_number}")
        if self.status not in VALID_PAGE_STATUSES:
            raise ValueError(f"invalid status {self.status!r}, expected one of {VALID_PAGE_STATUSES}")
        if self.status == "error":
            if not self.error_message:
                raise ValueError("status='error' requires a non-empty error_message")
        elif self.error_message is not None:
            raise ValueError(f"status={self.status!r} must have error_message=None")

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "width_px": self.width_px,
            "height_px": self.height_px,
            "status": self.status,
            "error_message": self.error_message,
            "text": self.text,
            "regions": [r.to_dict() for r in self.regions],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OCRPage":
        return cls(
            page_number=int(data["page_number"]),
            width_px=None if data["width_px"] is None else int(data["width_px"]),
            height_px=None if data["height_px"] is None else int(data["height_px"]),
            status=data["status"],
            error_message=data["error_message"],
            text=data["text"],
            regions=[OCRRegion.from_dict(r) for r in data["regions"]],
        )


@dataclass
class OCRDocument:
    """A whole document, normalized page by page.

    `document_id` is the full SHA-256 hex digest of the source bytes, so the same
    file yields the same identity regardless of filename. `source_name` keeps the
    human-readable name separately.
    """

    document_id: str
    source_name: str
    page_count: int
    raster_dpi: int
    pages: list[OCRPage] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.page_count != len(self.pages):
            raise ValueError(
                f"page_count={self.page_count} does not match len(pages)={len(self.pages)}"
            )
        expected = list(range(1, len(self.pages) + 1))
        actual = [p.page_number for p in self.pages]
        if actual != expected:
            raise ValueError(f"page numbers must be 1..N with no gaps, got {actual}")

    # --- convenience read-only views (no layout logic) ---

    @property
    def status_counts(self) -> dict[str, int]:
        counts = {status: 0 for status in VALID_PAGE_STATUSES}
        for page in self.pages:
            counts[page.status] += 1
        return counts

    @property
    def region_count(self) -> int:
        return sum(len(p.regions) for p in self.pages)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "source_name": self.source_name,
            "page_count": self.page_count,
            "raster_dpi": self.raster_dpi,
            "pages": [p.to_dict() for p in self.pages],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OCRDocument":
        return cls(
            document_id=str(data["document_id"]),
            source_name=str(data["source_name"]),
            page_count=int(data["page_count"]),
            raster_dpi=int(data["raster_dpi"]),
            pages=[OCRPage.from_dict(p) for p in data["pages"]],
        )


def make_region_id(page_number: int, region_index_1based: int) -> str:
    """Human-readable, 1-based region identifier, e.g. 'p1-r1'.

    Stable for a given (document, raster_dpi, engine version); NOT stable across
    engine upgrades, so it is an intra-run evidence handle, not a durable key.
    """
    return f"p{page_number}-r{region_index_1based}"


def regions_to_page_text(regions: Sequence[OCRRegion]) -> str:
    """Newline-join region text in engine return order.

    Intentionally no reading-order or layout reconstruction: that is a later
    phase's decision and would be invisible, unverifiable magic here.
    """
    return "\n".join(r.text for r in regions)
