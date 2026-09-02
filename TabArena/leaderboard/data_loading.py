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
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd

from constants import Constants

DATA_DIR = Path(__file__).parent / "data"
# BeyondArena artifacts live under their own root (see
# scripts/run_generate_beyondarena_website_artifacts.py in the tabarena repo).
BEYOND_DATA_DIR = Path(__file__).parent / "data_beyondarena"


# --------------------------------------------------------------------------- #
# Subset axes
#
# A leaderboard "subset" is one cell of a 5-axis grid. Three axes are *view
# modifiers* surfaced as controls (entrants, imputation, splits); two are
# *content subsets* surfaced as tab bars (tasks, datasets). Keeping the axis
# definitions here (as data, not as if/elif chains) means adding or reordering a
# subset is a one-line edit. The first value of each axis is its default.
# --------------------------------------------------------------------------- #

# Who competes. Every leaderboard number is relative to the field: Elo is pairwise over
# the participants and improvability is measured against the best of them, so each pool is
# its own evaluation with its own artifacts rather than a filter over a shared table.
#
# Models always compete. Systems fall into these independently selectable categories, and
# every combination is published. Independent rather than a cumulative ladder on purpose:
# "LLM-based systems but not the plain open-source ones" is a real question, and a ladder
# cannot express it. Mirrors `SYSTEM_CATEGORIES` in tabarena/evaluation/entrants.py, whose
# `pool_key` builds the folder segments below.
SYSTEM_CATEGORY_LABELS = {
    "open": "📊 Open-source systems",
    "llm": "🤖 Systems with LLMs",
    "api": "🔒 Closed-source API systems",
}

# The tag that puts a system in each category; None is the untagged (plain open-source) group.
SYSTEM_CATEGORY_TAGS = {
    "open": None,
    "llm": "with-llm",
    "api": "closed-source-api",
}

SYSTEM_CATEGORY_NOTES = {
    "open": "Systems you can inspect and run yourself, such as AutoGluon.",
    "llm": "Systems with an LLM in the loop, including agents.",
    "api": "Systems behind a remote API whose internals we cannot inspect.",
}

# Shown on a category that has no entrant yet, which is rendered as a disabled toggle.
CATEGORY_COMING_SOON = "Coming soon: waiting for a submission"

# Folder segment for the pool where no system competes.
MODELS_ONLY_KEY = "models"


def entrants_key(categories: Iterable[str]) -> str:
    """Folder segment for a set of selected categories, in `SYSTEM_CATEGORY_LABELS` order.

    Order-independent, so ticking the boxes in any order lands on the same artifacts.
    Mirrors `pool_key` in tabarena/evaluation/entrants.py.
    """
    selected = set(categories or ())
    ordered = [key for key in SYSTEM_CATEGORY_LABELS if key in selected]
    return "_".join(ordered) if ordered else MODELS_ONLY_KEY


def widest_entrants_key() -> str:
    """The pool where every category competes; the one to read totals from."""
    return entrants_key(SYSTEM_CATEGORY_LABELS)


def entrants_categories(key: str) -> list[str]:
    """The selected category keys encoded in a folder segment."""
    return [] if key == MODELS_ONLY_KEY else [k for k in SYSTEM_CATEGORY_LABELS if k in key.split("_")]


def entrants_name(key: str) -> str:
    """Human-readable name for a pool, used in figure labels."""
    selected = entrants_categories(key)
    if not selected:
        return "Models only"
    return "Models + " + ", ".join(SYSTEM_CATEGORY_LABELS[k] for k in selected)


def entrants_note(key: str) -> str:
    """One line describing who competes in a pool."""
    selected = entrants_categories(key)
    if not selected:
        return "Individual models only, each run under TabArena's shared tuning protocol."
    return "Also competing: " + " ".join(SYSTEM_CATEGORY_NOTES[k] for k in selected)


@lru_cache(maxsize=None)
def available_categories(data_root: str) -> frozenset[str]:
    """Which system categories actually have an entrant in the published artifacts.

    Read from the widest pool's leaderboard, so a category nobody has submitted to yet can be
    shown as a disabled toggle instead of a setting that silently changes nothing.
    """
    path = Path(data_root) / Subset(entrants=widest_entrants_key()).rel_path / "website_leaderboard.csv"
    if not path.exists():
        return frozenset()
    df = load_leaderboard_csv(str(path.resolve()))
    if "MethodClass" not in df.columns:
        return frozenset()
    systems = df[df["MethodClass"] == "system"]
    if systems.empty:
        return frozenset()
    # An empty Tags cell round-trips through CSV as NaN, and `str(nan)` is the string "nan",
    # so an untagged system would read as tagged. Test for null rather than truthiness.
    tag_sets = [
        set() if pd.isna(v) else {t for t in str(v).split(";") if t}
        for v in systems.get("Tags", pd.Series(dtype=object))
    ]
    found = set()
    for key, tag in SYSTEM_CATEGORY_TAGS.items():
        if tag is None:
            if any(not tags for tags in tag_sets):
                found.add(key)
        elif any(tag in tags for tags in tag_sets):
            found.add(key)
    return frozenset(found)


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

# What each choice means, shown as a hover tooltip on the chip (see `main.taStampTitles`).
# Every selector in the control card carries one, so nothing has to be guessed from a label.
TASK_NOTES = {
    "all": "Every task type: binary and multiclass classification plus regression.",
    "classification": "Classification only, binary and multiclass together.",
    "regression": "Regression tasks only, scored with RMSE.",
    "binary": "Binary classification only, scored with ROC AUC.",
    "multiclass": "Multiclass classification only, scored with log-loss.",
}

DATASET_NOTES = {
    "all": "Every curated dataset, whatever its size.",
    "small": "Datasets with at most 10,000 training rows.",
    "medium": "Datasets with between 10,001 and 100,000 training rows.",
}

# What each row of the control card selects, hovered on the caption at its left. Keyed by the
# class on the row, because a CSS ::before caption cannot carry a title of its own; the title
# goes on the row and a chip's own tooltip still wins over it (see `main.taStampTitles`).
AXIS_NOTES = {
    "ta-row-entrants": (
        "Who is scored together. Each combination is evaluated separately, so switching re-rates "
        "everyone rather than hiding rows: Elo is pairwise over the entrants and Improvability is "
        "the gap to the best of them."
    ),
    "axis-care": (
        "What to optimise for. Reorders the figures and picks the time axis the Pareto front is "
        "plotted against."
    ),
    "axis-metric": (
        "Which headline metric the page leads with. The second figure stays pinned to the other "
        "one, so both are always on the page."
    ),
    "axis-tasks": "Restrict the leaderboard to one task type.",
    "axis-datasets": "Restrict the leaderboard to one dataset-size bucket.",
    "ta-row-protocol": "How the reported numbers were computed.",
}

PROTOCOL_NOTES = {
    "imputed": (
        "Include methods that cannot run on every dataset. Their missing results are imputed "
        "with a default RandomForest, which counts against them for not covering the benchmark."
    ),
    "lite": (
        "Score each experiment on one split (first fold, first repeat) instead of all repeats. "
        "Cheaper and less reliable, but usually a good proxy."
    ),
}

DATASET_SIZE_NOTE = {
    "small": "Small datasets have at most 10,000 training rows.",
    "medium": "Medium datasets have between 10,001 and 100,000 training rows.",
    "tabpfn": (
        "TabPFNv2-compatible datasets contain at most 10,000 samples, "
        "500 features, and 10 classes."
    ),
}


@dataclass(frozen=True)
class Subset:
    """One cell of the leaderboard grid (entrants x imputation x splits x tasks x datasets).

    ``rel_path`` mirrors ``get_website_folder_name`` in
    ``tabarena/evaluation/subset_grid.py`` segment for segment: the path *is* the subset's
    identity on both sides, so changing the layout means changing both.
    """

    entrants: str = "models"  # `entrants_key(...)` of the selected categories
    imputation: str = "yes"  # "yes" | "no"
    splits: str = "all"  # "all" | "lite"
    tasks: str = "all"  # see TASK_LABELS
    datasets: str = "all"  # see DATASET_LABELS

    @property
    def rel_path(self) -> str:
        return (
            f"entrants_{self.entrants}/"
            f"imputation_{self.imputation}/"
            f"splits_{self.splits}/"
            f"tasks_{self.tasks}/"
            f"datasets_{self.datasets}"
        )


#: Family name the artifacts used before systems became their own entrant class. Artifacts
#: generated then are still served: every BeyondArena subset, and any TabArena subset not yet
#: regenerated. Without this the rows keep a family nothing maps a colour or pill to and render
#: grey, so the name is normalized on read and the rest of the app only ever sees "System".
_LEGACY_FAMILY_NAMES = {"Reference Pipeline": Constants.system}


@lru_cache(maxsize=None)
def load_leaderboard_csv(path: str) -> pd.DataFrame:
    """Read a ``website_leaderboard.csv`` (cached; files are tiny and immutable)."""
    df = pd.read_csv(path)
    df = df.rename(columns={"1#": "#"})
    if "TypeName" in df.columns:
        df["TypeName"] = df["TypeName"].replace(_LEGACY_FAMILY_NAMES)
    return df


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

    def has_image(self, img_name: str) -> bool:
        """Whether this subset ships a static ``img_name`` figure.

        TabArena subsets ship interactive explorers only, so this is False for them; the
        BeyondArena subsets and any pre-explorer artifacts still carry PNGs.
        """
        base = self.base_path / img_name
        return base.with_suffix(".png").exists() or base.with_suffix(".png.zip").exists()

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
        f"{entrants_name(subset.entrants)} | {TASK_LABELS[subset.tasks]} "
        f"| {DATASET_LABELS[subset.datasets]} | {split} | {impute}"
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

    # Which entrants competed decides every number above, so it is said here too.
    entrant_note = entrants_note(subset.entrants)
    if entrant_note:
        blurb += f"<br>{entrant_note}"
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
    "temporal": "Temporally split tasks only: train on the past, test on the future.",
    "grouped": "Group-wise split tasks only, with disjoint groups between train and test.",
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
