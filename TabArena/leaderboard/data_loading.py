"""Data loading and subset configuration for the TabArena leaderboard.

This module owns everything about *where* leaderboard artifacts live and *how*
they are read. Layout (Gradio components) lives in ``views.py`` and ``pages.py``;
user-facing copy lives in ``website_texts.py``.

Performance note: the website optimizes for fast first paint. CSVs are tiny and
cached (:func:`load_leaderboard_csv`); the large per-subset PNGs are only
unzipped on demand (:meth:`LBContainer.image_path`) and only for the subset the
user is currently viewing.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
# BeyondArena artifacts live under their own root (see
# scripts/run_generate_beyondarena_website_artifacts.py in the tabarena repo).
BEYOND_DATA_DIR = Path(__file__).parent / "data_beyondarena"


# --------------------------------------------------------------------------- #
# Subset axes
#
# A leaderboard "subset" is one cell of a 4-axis grid. Two axes are *view
# modifiers* surfaced as toggles (imputation, splits); two are *content subsets*
# surfaced as tab bars (tasks, datasets). Keeping the axis definitions here (as
# data, not as if/elif chains) means adding or reordering a subset is a one-line
# edit. The first value of each axis is its default.
# --------------------------------------------------------------------------- #

# axis -> {value: human label}. Insertion order = display order; first = default.
TASK_LABELS = {
    "all": "All Tasks",
    "classification": "Classification",
    "regression": "Regression",
    "binary": "Binary",
    "multiclass": "Multiclass",
}
DATASET_LABELS = {
    "all": "All Datasets",
    "small": "Small",
    "medium": "Medium",
}

# Short labels used as column headers in the cross-subset overview.
TASK_SHORT = {
    "all": "Overall",
    "classification": "Class.",
    "regression": "Regr.",
    "binary": "Binary",
    "multiclass": "Multi.",
}
DATASET_SHORT = {
    "small": "Small",
    "medium": "Medium",
}

DATASET_SIZE_NOTE = {
    "small": "Small datasets contain between 500 and 10,000 samples.",
    "medium": "Medium datasets contain between 10,000 and 250,000 samples.",
    "tabpfn": (
        "TabPFNv2-compatible datasets contain at most 10,000 samples, "
        "500 features, and 10 classes."
    ),
}


@dataclass(frozen=True)
class Subset:
    """One cell of the leaderboard grid (imputation x splits x tasks x datasets)."""

    imputation: str = "yes"  # "yes" | "no"
    splits: str = "all"  # "all" | "lite"
    tasks: str = "all"  # see TASK_LABELS
    datasets: str = "all"  # see DATASET_LABELS

    @property
    def rel_path(self) -> str:
        return (
            f"imputation_{self.imputation}/"
            f"splits_{self.splits}/"
            f"tasks_{self.tasks}/"
            f"datasets_{self.datasets}"
        )


@lru_cache(maxsize=None)
def load_leaderboard_csv(path: str) -> pd.DataFrame:
    """Read a ``website_leaderboard.csv`` (cached; files are tiny and immutable)."""
    df = pd.read_csv(path)
    return df.rename(columns={"1#": "#"})


VARIANT_RE = re.compile(r"\((default|tuned \+ ensembled|tuned)\)")


def parse_model(model: str) -> tuple[str, str, str | None]:
    """Split a Model cell into (base name, variant, url).

    A cell looks like ``[TabFM (default)](https://…)``, optionally followed by an
    ``[X% IMPUTED]`` tag. Used both for display (``views.py``) and for the JSON
    records the API returns (``api.py``), so the two cannot disagree.
    """
    link = re.match(r"\[(.*?)\]\((.*?)\)", model)
    text, url = (link.group(1), link.group(2)) if link else (model, None)
    text = text.split("[")[0].strip()  # drop any [X% IMPUTED] tag
    variant_match = VARIANT_RE.search(text)
    variant = variant_match.group(1) if variant_match else ""
    base = VARIANT_RE.sub("", text).strip()
    return base, variant, url


def unzip_png(base_dir: Path, img_name: str) -> str:
    """Return the path to ``base_dir/img_name``.png, unzipping the ``.png.zip`` on first access."""
    base = Path(base_dir) / img_name
    img_path = base.with_suffix(".png")
    if img_path.exists():
        return str(img_path)
    with zipfile.ZipFile(base.with_suffix(".png.zip"), "r") as zipf:
        zipf.extractall(img_path.parent)
    return str(img_path)


@dataclass
class LBContainer:
    """Loads the artifacts for a single subset under a given data root."""

    data_root: Path
    subset: Subset
    name: str
    n_datasets: int | None = None
    blurb: str | None = None
    base_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.base_path = Path(self.data_root) / self.subset.rel_path
        for fname in self._listdir():
            match = re.match(r"n_datasets_(.+)", fname)
            if match:
                self.n_datasets = match.group(1)
                break

    def _listdir(self) -> list[str]:
        try:
            return [p.name for p in self.base_path.iterdir()]
        except FileNotFoundError:
            return []

    def load_df(self) -> pd.DataFrame:
        return load_leaderboard_csv(str((self.base_path / "website_leaderboard.csv").resolve())).copy()

    def image_path(self, img_name: str) -> str:
        """Return the path to ``img_name``.png, unzipping it on first access."""
        return unzip_png(self.base_path, img_name)

    def html_content(self, name: str) -> str | None:
        """Return the inline content of ``name``.html (a self-contained
        interactive plot generated by the tabarena artifact pipeline), or
        ``None`` when the subset's data predates these artifacts — callers
        fall back to the static PNG then.
        """
        path = self.base_path / f"{name}.html"
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None


def subset_name(subset: Subset) -> str:
    """Human-readable name for a subset, used in figure labels."""
    impute = "with imputation" if subset.imputation == "yes" else "no imputation"
    split = "all repeats" if subset.splits == "all" else "Lite"
    return (
        f"{TASK_LABELS[subset.tasks]} | {DATASET_LABELS[subset.datasets]} "
        f"| {split} | {impute}"
    )


def subset_blurb(subset: Subset, n_datasets: int | None) -> str:
    """One-line description of the subset shown above its figures."""
    datasets_name = DATASET_LABELS[subset.datasets].lower()
    blurb = (
        f"Leaderboard for {n_datasets} datasets "
        f"({datasets_name}, {TASK_LABELS[subset.tasks].lower()}) "
    )
    if subset.splits == "lite":
        blurb += "for one split (1st fold, 1st repeat) "
    blurb += "including all "
    if subset.imputation == "yes":
        blurb += "(imputed) "
    blurb += "models."

    note = DATASET_SIZE_NOTE.get(subset.datasets)
    if note:
        blurb += f"<br>{note}"
    return blurb


# --------------------------------------------------------------------------- #
# BeyondArena subsets
#
# BeyondArena diverges from TabArena: there is no imputation/splits/tasks/datasets
# grid. Instead a single axis of subset dimensions (split regime, size bucket,
# feature dimensionality/type) is surfaced as one tab bar, and every leaderboard
# is always computed on the recommended `core` protocol (`["core", <dim>]`; the
# "full" subset is `core` with no extra filter). The artifacts are produced by
# scripts/run_generate_beyondarena_website_artifacts.py in the tabarena repo, whose
# `BEYOND_SUBSETS` keys must match the labels below.
# --------------------------------------------------------------------------- #

# label -> human name. Insertion order = tab-bar order; first = default. Groups are
# only used to draw section separators in the tab bar / copy.
BEYOND_SUBSET_LABELS = {
    "full": "Full",
    "random": "IID",
    "temporal": "Temporal",
    "grouped": "Grouped",
    "tiny": "Tiny",
    "small": "Small",
    "medium": "Medium",
    "large": "Large",
    "low-dim": "Low-dim",
    "high-dim": "High-dim",
    "text": "Text",
    "high-cardinality": "High-cardinality",
}

# One-line description shown above each subset's figures. Kept in sync with the
# BeyondArena subset predicates (see BeyondArenaContext.SUBSET_PREDICATES).
BEYOND_SUBSET_NOTE = {
    "full": "All BeyondArena datasets, on the recommended core protocol.",
    "random": "IID (randomly split) tasks only.",
    "temporal": "Temporally split tasks only — train on the past, test on the future.",
    "grouped": "Group-wise split tasks only — disjoint groups between train and test.",
    "tiny": "Tiny datasets contain at most 1,000 training rows.",
    "small": "Small datasets contain between 1,001 and 10,000 training rows.",
    "medium": "Medium datasets contain between 10,001 and 100,000 training rows.",
    "large": "Large datasets contain between 100,001 and 1,000,000 training rows.",
    "low-dim": "Low-dimensional datasets have at most 100 columns after preprocessing.",
    "high-dim": "High-dimensional datasets have more than 100 columns after preprocessing.",
    "text": "Datasets that contain one or more text columns.",
    "high-cardinality": "Datasets that contain one or more high-cardinality categorical columns.",
}


@dataclass(frozen=True)
class BeyondSubset:
    """One cell of the BeyondArena leaderboard — a single subset dimension, always on core."""

    subset: str = "full"  # see BEYOND_SUBSET_LABELS

    @property
    def rel_path(self) -> str:
        return f"subsets/{self.subset}"


def beyond_subset_name(subset: BeyondSubset) -> str:
    """Human-readable name for a BeyondArena subset, used in figure labels."""
    return f"{BEYOND_SUBSET_LABELS[subset.subset]} · core"


def beyond_subset_blurb(subset: BeyondSubset, n_datasets: int | None) -> str:
    """One-line description of a BeyondArena subset shown above its figures."""
    human = BEYOND_SUBSET_LABELS[subset.subset].lower()
    blurb = (
        f"Leaderboard for {n_datasets} BeyondArena datasets ({human}), evaluated on the "
        "recommended <b>core</b> protocol."
    )
    note = BEYOND_SUBSET_NOTE.get(subset.subset)
    if note:
        blurb += f"<br>{note}"
    return blurb
