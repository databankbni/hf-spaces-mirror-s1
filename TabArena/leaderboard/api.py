"""The Space's machine-readable API, for agents rather than browsers.

Hugging Face serves a generated ``agents.md`` for every Gradio Space
(``huggingface.co/spaces/<id>/agents.md``). It is not a repo file and cannot be
overridden: it tells an agent to read ``/gradio_api/info`` and call whatever it
finds there. So the endpoints registered here *are* the agent-facing contract.

Two rules keep that contract readable. Everything in this file is a named,
described, typed endpoint; and every UI event listener elsewhere in the app
passes ``api_visibility="private"``, so render callbacks stay out of the schema
(a public listener would otherwise show up as ``/lambda_7`` with a parameter
called ``value_11``).

The same four functions are also served as MCP tools at ``/gradio_api/mcp/``,
from these type hints and docstrings, because ``main.py`` launches with
``mcp_server=True``. Anything written here is read by an agent twice over.

Two things follow from how an MCP client actually reads this, and both shape the
wording below.

*Each tool description has to introduce the subject.* Gradio 6 offers no
server-level instructions field, so there is nowhere to say once what TabArena
is; a client may surface a single tool with no sibling for context. So every
``api_description`` names the domain (predicting a target column from
structured, rows-and-columns data) and the methods people actually ask about by
name, and spells out the questions the tool answers. A description that only
says "TabArena results" is invisible to an agent whose user asked about TabPFN
or about which model to use on a CSV.

*Gradio keeps only the first line of each ``Args:`` entry.*
``utils.get_function_description`` splits on the first colon per line and drops
continuations, so a wrapped parameter description reaches the schema cut off
mid-sentence. Every entry below is therefore one long line, however wide it
reads in source.

Records are the published CSVs with agent-friendly keys, not a second source of
truth: the same files the site reads, the same model-cell parser the table uses.
For bulk access, skip the queue and fetch the CSV directly (see
:func:`list_leaderboards`, which hands out the URL template).
"""

from __future__ import annotations

import os
import re
from itertools import combinations
from pathlib import Path
from typing import Any, Literal, get_args

import gradio as gr
import pandas as pd

from constants import Constants
from data_loading import (
    BEYOND_DATA_DIR,
    BEYOND_SUBSET_LABELS,
    DATA_DIR,
    DATASET_LABELS,
    SYSTEM_CATEGORY_LABELS,
    BeyondSubset,
    LBContainer,
    Subset,
    TASK_LABELS,
    entrants_key,
    entrants_name,
    entrants_note,
    parse_model,
)

# Axis values as Literals, so /gradio_api/info carries an enum per parameter.
# That schema is the only place an agent reliably learns the valid values: a
# rejected call comes back over the REST route as a bare `event: error` with a
# null payload, message dropped. _validate_axes below keeps these in step with
# the label dicts that define the data layout.
# A leaderboard row is either a single model (evaluated in its default / tuned /
# tuned+ensembled variants) or a whole system such as AutoGluon, which the artifacts mark
# with method_class="system". Agents conflate the two otherwise, and "the best tabular
# model" answered with an AutoML system is a wrong answer, so the endpoints return models
# only unless asked for something else.
KindAxis = Literal["models", "systems", "all"]
SYSTEM_TYPE = Constants.system

# Which benchmark a cross-benchmark endpoint should read.
BenchmarkAxis = Literal["tabarena", "beyondarena"]
# What "best" means. The leaderboards rank by Elo; the rest are complementary.
QualityAxis = Literal["elo", "score", "rank", "harmonic_rank", "improvability_pct"]
_QUALITY_HIGHER_IS_BETTER = {
    "elo": True,
    "score": True,
    "rank": False,
    "harmonic_rank": False,
    "improvability_pct": False,
}
# What "cheap" means, and the record key each maps to.
CostAxis = Literal["predict_time", "train_time"]
_COST_KEY = {
    "predict_time": "median_predict_time_s_per_1k",
    "train_time": "median_train_time_s_per_1k",
}
_COST_UNITS = {
    "median_predict_time_s_per_1k": "seconds per 1000 rows to predict",
    "median_train_time_s_per_1k": "seconds per 1000 rows to train",
}

# Which field the numbers were computed against. Not a filter: each pool is its own
# evaluation, because Elo is pairwise over the participants and improvability is measured
# against the best of them. One value per combination of the system categories, so `models`
# is models only and `open_llm_api` is everything; `llm` is models plus LLM-based systems
# without the plain open-source ones.
EntrantsAxis = Literal[
    "models",
    "open",
    "llm",
    "api",
    "open_llm",
    "open_api",
    "llm_api",
    "open_llm_api",
]
TasksAxis = Literal["all", "classification", "regression", "binary", "multiclass"]
DatasetsAxis = Literal["all", "small", "medium"]
ImputationAxis = Literal["yes", "no"]
SplitsAxis = Literal["all", "lite"]
BeyondSubsetAxis = Literal[
    "full",
    "random",
    "temporal",
    "grouped",
    "tiny",
    "small",
    "medium",
    "large",
    "low-dim",
    "high-dim",
    "text",
    "high-cardinality",
]

IMPUTATION_VALUES = list(get_args(ImputationAxis))
SPLITS_VALUES = list(get_args(SplitsAxis))
KIND_VALUES = list(get_args(KindAxis))


def _validate_axes() -> None:
    """Fail at import if an axis Literal has drifted from the data layout."""
    for name, literal, allowed in (
        ("TasksAxis", TasksAxis, TASK_LABELS),
        ("DatasetsAxis", DatasetsAxis, DATASET_LABELS),
        ("BeyondSubsetAxis", BeyondSubsetAxis, BEYOND_SUBSET_LABELS),
    ):
        if set(get_args(literal)) != set(allowed):
            raise RuntimeError(
                f"api.{name} is out of sync with data_loading: "
                f"{sorted(set(get_args(literal)) ^ set(allowed))} on one side only."
            )


def _validate_entrants_axis() -> None:
    """Fail at import if EntrantsAxis has drifted from the category combinations."""
    keys = list(SYSTEM_CATEGORY_LABELS)
    expected = {entrants_key(c) for size in range(len(keys) + 1) for c in combinations(keys, size)}
    if set(get_args(EntrantsAxis)) != expected:
        raise RuntimeError(
            "api.EntrantsAxis is out of sync with data_loading.SYSTEM_CATEGORY_LABELS: "
            f"{sorted(set(get_args(EntrantsAxis)) ^ expected)} on one side only."
        )


_validate_axes()
_validate_entrants_axis()

# The Space serving this app; HF sets SPACE_ID in the container.
SPACE_ID = os.environ.get("SPACE_ID", "TabArena/leaderboard")
_RAW_URL = f"https://huggingface.co/spaces/{SPACE_ID}/resolve/main"

# Column headers carry a sort-direction marker for the table widget; it is not
# part of the data, so it is stripped before the header becomes a JSON key.
_DIRECTION_RE = re.compile(r"\s*\[[⬆⬇]️?\]$")
_KEY_OVERRIDES = {"#": "position", "TypeName": "type_name"}

# Bulk-download URLs, templated on the same rel_path the app reads from so the
# two cannot drift.
_TABARENA_CSV_TEMPLATE = (
    f"{_RAW_URL}/{DATA_DIR.name}/"
    + Subset("{entrants}", "{imputation}", "{splits}", "{tasks}", "{datasets}").rel_path
    + "/website_leaderboard.csv"
)
_BEYOND_CSV_TEMPLATE = (
    f"{_RAW_URL}/{BEYOND_DATA_DIR.name}/"
    + BeyondSubset("{subset}").rel_path
    + "/website_leaderboard.csv"
)


def _api_key(column: str) -> str:
    """Turn a CSV header into a JSON key: ``Improvability (%) [⬇️]`` -> ``improvability_pct``."""
    if column in _KEY_OVERRIDES:
        return _KEY_OVERRIDES[column]
    name = _DIRECTION_RE.sub("", column).replace("%", "pct").replace("/", "_per_")
    return re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """One JSON record per leaderboard row."""
    # NaN is not JSON; None is. Casting to object first keeps ints from turning
    # into floats on the way through.
    df = df.astype(object).where(pd.notna(df), None)
    records = []
    for row in df.to_dict("records"):
        record = {_api_key(key): value for key, value in row.items()}
        # The Model cell is markdown (`[TabFM (default)](url)`); agents want the
        # three parts separately.
        name, variant, url = parse_model(str(row["Model"]))
        record["model"] = name
        record["variant"] = variant
        record["model_url"] = url
        record["verified"] = str(row.get("Verified") or "").strip() == "✔️"
        record["kind"] = "system" if row.get("TypeName") == SYSTEM_TYPE else "model"
        # Semicolon-joined upstream; agents want a list. Empty for every model, and for a
        # system that is open-source, local and LLM-free.
        record["tags"] = [t for t in str(row.get("Tags") or "").split(";") if t]
        records.append(record)
    return records


def _select_kind(records: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    if kind == "all":
        return records
    wanted = "system" if kind == "systems" else "model"
    return [r for r in records if r["kind"] == wanted]


def _check(axis: str, value: str, allowed: list[str]) -> None:
    if value not in allowed:
        raise gr.Error(f"Unknown {axis}={value!r}. Valid values: {', '.join(allowed)}.")


def _pareto_frontier(
    records: list[dict[str, Any]], quality: str, cost_key: str
) -> list[dict[str, Any]]:
    """The non-dominated records: nothing is both better and cheaper.

    Walks cheapest-first and keeps a record only when it beats every cheaper one on
    quality, which is the 2-D skyline. Ties on cost keep the better-quality record.
    """
    higher_is_better = _QUALITY_HIGHER_IS_BETTER[quality]
    usable = [
        r
        for r in records
        if isinstance(r.get(quality), (int, float)) and isinstance(r.get(cost_key), (int, float))
    ]
    ordered = sorted(
        usable,
        key=lambda r: (r[cost_key], -r[quality] if higher_is_better else r[quality]),
    )
    frontier: list[dict[str, Any]] = []
    best = None
    for record in ordered:
        value = record[quality]
        if best is None or (value > best if higher_is_better else value < best):
            frontier.append(record)
            best = value
    return frontier


def _best(records: list[dict[str, Any]], quality: str) -> dict[str, Any] | None:
    """The single best record on `quality`, ignoring rows that lack it."""
    usable = [r for r in records if isinstance(r.get(quality), (int, float))]
    if not usable:
        return None
    return max(
        usable,
        key=lambda r: r[quality] if _QUALITY_HIGHER_IS_BETTER[quality] else -r[quality],
    )


def _brief(record: dict[str, Any] | None, quality: str, cost_key: str) -> dict[str, Any] | None:
    """The fields worth returning for one model in a Pareto answer."""
    if record is None:
        return None
    return {
        "model": record.get("model"),
        "variant": record.get("variant"),
        "kind": record.get("kind"),
        "type_name": record.get("type_name"),
        "verified": record.get("verified"),
        "model_url": record.get("model_url"),
        quality: record.get(quality),
        cost_key: record.get(cost_key),
        "median_train_time_s_per_1k": record.get("median_train_time_s_per_1k"),
        "median_predict_time_s_per_1k": record.get("median_predict_time_s_per_1k"),
    }


def _describe(name: str | None, variant: str | None) -> str:
    return f"{name} ({variant})" if variant else str(name)


def _load(data_root: Path, subset: Subset | BeyondSubset) -> list[dict[str, Any]]:
    lb = LBContainer(data_root=data_root, subset=subset, name="")
    try:
        return _records(lb.load_df())
    except FileNotFoundError:
        raise gr.Error(
            f"No results for {subset.rel_path!r} in this deployment. "
            "Call list_leaderboards for the subsets that are available."
        ) from None


def get_tabarena_leaderboard(
    tasks: TasksAxis = "all",
    datasets: DatasetsAxis = "all",
    kind: KindAxis = "models",
    imputation: ImputationAxis = "yes",
    splits: SplitsAxis = "all",
    entrants: EntrantsAxis = "models",
) -> list[dict[str, Any]]:
    """Ranked results for one subset of TabArena, the IID tabular machine-learning benchmark.

    Each row is a method evaluated on 51 curated datasets whose task is to predict a target
    column from structured, rows-and-columns data: tabular foundation models (TabPFN, TabICL,
    TabDPT, Mitra, TabM), gradient-boosted trees (LightGBM, XGBoost, CatBoost), neural networks
    (RealMLP, ModernNCA) and AutoML systems (AutoGluon).

    Args:
        tasks: Restrict to a task type. ``all`` (default), ``classification``, ``regression``, ``binary`` or ``multiclass``.
        datasets: Restrict by dataset size. ``all`` (default), ``small`` (up to 2500 rows) or ``medium`` (up to 100k rows).
        kind: What to rank. ``models`` (default) returns individual models such as TabPFN, RealMLP or LightGBM; ``systems`` returns whole AutoML systems such as AutoGluon, which tune and ensemble many models inside their own budget and so are not comparable to a single model; ``all`` returns both, as the website's table does. Ask for ``models`` when the question is "which model should I use" and ``systems`` when it is "which AutoML framework should I use". Every record also carries its own ``kind``.
        imputation: Whether to keep methods with incomplete coverage. ``yes`` (default, and what the website shows) includes models that cannot run on every dataset, filling their missing runs with a default RandomForest; ``no`` drops those models entirely.
        splits: Which evaluation protocol. ``all`` (default) is the full repeated cross-validation; ``lite`` is the cheaper single-split TabArena-Lite protocol.
        entrants: Which field the numbers were computed against, not a row filter: Elo is a pairwise rating over whoever competed and Improvability is the gap to the best of them, so each pool is a separate published evaluation and switching re-ranks everything. ``models`` (default) is individual models only; ``open`` adds open-source local systems such as AutoGluon; ``llm`` adds systems with an LLM in the loop; ``api`` adds systems behind a closed-source API; the compound values (``open_llm``, ``open_api``, ``llm_api``, ``open_llm_api``) admit those categories together.

    Returns:
        One record per model variant, best first, with ``model``, ``variant``,
        ``elo``, ``score``, ``rank``, ``median_train_time_s_per_1k`` and the
        remaining leaderboard columns. ``variant`` is ``default``, ``tuned`` or
        ``tuned + ensembled``, and empty for systems such as AutoGluon, which
        are whole pipelines rather than one model's variant (``kind`` identifies
        those, and ``tags`` lists any caveats such as ``with-llm`` or
        ``closed-source-api``). Note the website's variant filter groups them with
        the tuned ensembles instead.
    """
    _check("tasks", tasks, list(TASK_LABELS))
    _check("datasets", datasets, list(DATASET_LABELS))
    _check("kind", kind, KIND_VALUES)
    _check("imputation", imputation, IMPUTATION_VALUES)
    _check("splits", splits, SPLITS_VALUES)
    _check("entrants", entrants, list(get_args(EntrantsAxis)))
    subset = Subset(
        entrants=entrants, imputation=imputation, splits=splits, tasks=tasks, datasets=datasets
    )
    return _select_kind(_load(DATA_DIR, subset), kind)


def get_beyondarena_leaderboard(
    subset: BeyondSubsetAxis = "full", kind: KindAxis = "models"
) -> list[dict[str, Any]]:
    """Ranked BeyondArena results for one subset, on the recommended core protocol.

    BeyondArena runs the same tabular methods (TabPFN, LightGBM, CatBoost, AutoGluon and the
    rest) where the IID assumption does not hold: random, temporal and grouped splits, across
    dataset sizes and feature types. It has a single subset axis rather than TabArena's grid.

    Args:
        subset: Which slice of BeyondArena to read. ``full`` (default) is everything; ``random`` / ``temporal`` / ``grouped`` pick a split type; ``tiny`` / ``small`` / ``medium`` / ``large`` pick a dataset size; ``low-dim`` / ``high-dim`` / ``text`` / ``high-cardinality`` pick a feature profile.
        kind: What to rank: ``models`` (default), ``systems`` for whole AutoML systems, or ``all`` for both. See `get_tabarena_leaderboard` for why the two are not directly comparable.

    Returns:
        One record per model variant, best first, in the same shape as
        `get_tabarena_leaderboard`.
    """
    _check("subset", subset, list(BEYOND_SUBSET_LABELS))
    _check("kind", kind, KIND_VALUES)
    return _select_kind(_load(BEYOND_DATA_DIR, BeyondSubset(subset=subset)), kind)


def get_pareto_frontier(
    benchmark: BenchmarkAxis = "tabarena",
    quality: QualityAxis = "elo",
    cost: CostAxis = "predict_time",
    kind: KindAxis = "models",
    tasks: TasksAxis = "all",
    datasets: DatasetsAxis = "all",
    beyond_subset: BeyondSubsetAxis = "full",
    max_train_time_s_per_1k: float = 0.0,
    max_predict_time_s_per_1k: float = 0.0,
    imputation: ImputationAxis = "yes",
    splits: SplitsAxis = "all",
    entrants: EntrantsAxis = "models",
) -> dict[str, Any]:
    """The accuracy-versus-time trade-off, for answering "which tabular model should I use".

    The top of a leaderboard is only one answer, and often the wrong one: the
    highest-Elo model can be orders of magnitude slower than one a hair behind it.
    This returns the whole trade-off: the outright best, the models that nothing
    beats on both axes at once, and the best model that fits a time budget. It
    covers tabular foundation models (TabPFN, TabICL, TabDPT), boosted trees
    (LightGBM, XGBoost, CatBoost), neural networks (RealMLP, TabM) and AutoML
    systems (AutoGluon), all on predicting a target column from structured data.

    Args:
        benchmark: Which benchmark to read: ``tabarena`` (default, IID splits) or ``beyondarena`` (temporal, grouped and other non-IID splits).
        quality: What "better" means: ``elo`` (default) or ``score``, where higher wins, or ``rank`` / ``harmonic_rank`` / ``improvability_pct``, where lower wins.
        cost: What "cheaper" means: ``predict_time`` (default, what matters for serving) or ``train_time`` (what matters for retraining).
        kind: What to consider: ``models`` (default), ``systems`` for whole AutoML systems, or ``all``. See `get_tabarena_leaderboard`.
        tasks: TabArena task subset (``all``, ``classification``, ``regression``, ``binary``, ``multiclass``); ignored when `benchmark` is ``beyondarena``.
        datasets: TabArena dataset-size subset (``all``, ``small``, ``medium``); ignored when `benchmark` is ``beyondarena``.
        beyond_subset: BeyondArena subset (``full``, ``temporal``, ``grouped``, a size or a feature profile); ignored when `benchmark` is ``tabarena``.
        max_train_time_s_per_1k: Ceiling on median train seconds per 1000 rows; 0 (default) means no limit. Use it for "what can I afford to retrain".
        max_predict_time_s_per_1k: Ceiling on median predict seconds per 1000 rows; 0 (default) means no limit. Use it for "what is the best model I can afford to serve".
        imputation: TabArena only; ``yes`` (default) keeps models with incomplete dataset coverage, ``no`` drops them. See `get_tabarena_leaderboard`.
        splits: TabArena only; ``all`` (default) is repeated cross-validation, ``lite`` the single-split protocol. See `get_tabarena_leaderboard`.
        entrants: TabArena only; which field the numbers were computed against, ``models`` by default. See `get_tabarena_leaderboard`.

    Returns:
        ``best_overall`` (the outright leader, ignoring cost), ``frontier`` (the
        non-dominated models, cheapest first, each with ``speedup_vs_best`` and
        ``quality_gap_vs_best``), ``best_within_limits`` (the leader among models
        satisfying the time ceilings, absent when no ceiling was given),
        ``dominated_count``, and a ``summary`` sentence to relay.
    """
    _check("benchmark", benchmark, list(get_args(BenchmarkAxis)))
    _check("quality", quality, list(_QUALITY_HIGHER_IS_BETTER))
    _check("cost", cost, list(_COST_KEY))
    _check("kind", kind, KIND_VALUES)
    if benchmark == "beyondarena":
        records = get_beyondarena_leaderboard(subset=beyond_subset, kind=kind)
        where = f"BeyondArena ({beyond_subset}, core protocol)"
    else:
        records = get_tabarena_leaderboard(
            tasks=tasks,
            datasets=datasets,
            kind=kind,
            imputation=imputation,
            splits=splits,
            entrants=entrants,
        )
        where = f"TabArena ({tasks} tasks, {datasets} datasets, {entrants})"

    cost_key = _COST_KEY[cost]
    best_overall = _best(records, quality)
    frontier = _pareto_frontier(records, quality, cost_key)

    limits = {
        "median_train_time_s_per_1k": max_train_time_s_per_1k,
        "median_predict_time_s_per_1k": max_predict_time_s_per_1k,
    }
    active_limits = {key: value for key, value in limits.items() if value and value > 0}
    within = records
    for key, ceiling in active_limits.items():
        within = [
            r for r in within if isinstance(r.get(key), (int, float)) and r[key] <= ceiling
        ]
    best_within = _best(within, quality) if active_limits else None

    entries = []
    for record in frontier:
        entry = _brief(record, quality, cost_key)
        if best_overall and isinstance(best_overall.get(cost_key), (int, float)):
            reference = best_overall[cost_key]
            entry["speedup_vs_best"] = (
                round(reference / record[cost_key], 2) if record[cost_key] else None
            )
            entry["quality_gap_vs_best"] = round(
                abs(best_overall[quality] - record[quality]), 4
            )
        entries.append(entry)

    return {
        "benchmark": benchmark,
        "subset": where,
        "quality": quality,
        "higher_is_better": _QUALITY_HIGHER_IS_BETTER[quality],
        "cost": cost_key,
        "kind": kind,
        "best_overall": _brief(best_overall, quality, cost_key),
        "frontier": entries,
        "dominated_count": max(0, len(records) - len(frontier)),
        "limits": active_limits or None,
        "best_within_limits": _brief(best_within, quality, cost_key),
        "summary": _pareto_summary(
            where, quality, cost_key, best_overall, entries, active_limits, best_within
        ),
    }


def _pareto_summary(
    where: str,
    quality: str,
    cost_key: str,
    best_overall: dict[str, Any] | None,
    frontier: list[dict[str, Any]],
    limits: dict[str, float],
    best_within: dict[str, Any] | None,
) -> str:
    """One paragraph an agent can relay instead of reciting the whole frontier."""
    if best_overall is None:
        return f"No {quality} values are available for {where}."
    lead = _describe(best_overall.get("model"), best_overall.get("variant"))
    units = _COST_UNITS.get(cost_key, cost_key)
    parts = [
        f"On {where}, the best {quality} is {lead} at {best_overall[quality]} "
        f"({best_overall.get(cost_key)} {units})."
    ]
    if len(frontier) > 1:
        cheapest = frontier[0]
        parts.append(
            f"{len(frontier)} models are on the accuracy/time frontier. The cheapest, "
            f"{_describe(cheapest.get('model'), cheapest.get('variant'))}, is "
            f"{cheapest.get('speedup_vs_best')}x faster but {cheapest.get('quality_gap_vs_best')} "
            f"{quality} behind."
        )
        # The trade-off worth naming is the smallest sacrifice that still buys a real
        # speedup, not the biggest speedup (that is just the cheapest model again).
        bargains = [
            entry
            for entry in frontier
            if (entry.get("speedup_vs_best") or 0) >= 2 and entry.get("quality_gap_vs_best")
        ]
        if bargains:
            pick = min(bargains, key=lambda e: e["quality_gap_vs_best"])
            parts.append(
                # "at a cost of" rather than "less", which reads backwards for the
                # metrics where lower is better.
                f"The best compromise is {_describe(pick.get('model'), pick.get('variant'))}: "
                f"{pick.get('speedup_vs_best')}x faster at a cost of "
                f"{pick.get('quality_gap_vs_best')} {quality}."
            )
    if limits:
        stated = ", ".join(f"{key} <= {value}" for key, value in limits.items())
        if best_within:
            parts.append(
                f"Within {stated}, the best is "
                f"{_describe(best_within.get('model'), best_within.get('variant'))} at "
                f"{best_within[quality]}."
            )
        else:
            parts.append(f"No model satisfies {stated}.")
    return " ".join(parts)


def list_leaderboards() -> dict[str, Any]:
    """Describe the available leaderboards, their subset axes, and the bulk-download URLs.

    TabArena benchmarks tabular machine learning: predicting a target column from
    structured, rows-and-columns data. Call this first: it lists the valid argument
    values for the other endpoints and the record keys they return. It also gives the
    raw CSV URL template for each benchmark, which serves the identical numbers over
    plain HTTP with no queue or session, and is the better choice for reading many
    subsets.
    """
    default_rows = _load(DATA_DIR, Subset())
    return {
        "about": (
            "TabArena benchmarks tabular machine learning: predicting a target column from "
            "structured, rows-and-columns data such as CSV files, spreadsheets, dataframes "
            "and database tables. Entrants range from tabular foundation models (TabPFN, "
            "TabICL, TabDPT, Mitra, TabM) through gradient-boosted trees (LightGBM, XGBoost, "
            "CatBoost) and neural networks (RealMLP, ModernNCA) to AutoML systems "
            "(AutoGluon). Every method is run under one protocol with its training and "
            "inference time measured, so accuracy and cost can be read together."
        ),
        "leaderboards": [
            {
                "name": "tabarena",
                "endpoint": "/get_tabarena_leaderboard",
                "description": (
                    "Tabular ML on 51 curated datasets with IID (random) splits, ranked by "
                    "Elo. The default question: which method predicts best."
                ),
                "axes": {
                    "tasks": list(TASK_LABELS),
                    "datasets": list(DATASET_LABELS),
                    "kind": KIND_VALUES,
                    "imputation": IMPUTATION_VALUES,
                    "splits": SPLITS_VALUES,
                    "entrants": list(get_args(EntrantsAxis)),
                },
                "csv_url_template": _TABARENA_CSV_TEMPLATE,
            },
            {
                "name": "beyondarena",
                "endpoint": "/get_beyondarena_leaderboard",
                "description": (
                    "Tabular ML beyond the IID assumption: random, temporal and grouped "
                    "splits across dataset sizes and feature types. Read this one when the "
                    "data shifts over time or arrives in groups."
                ),
                "axes": {"subset": list(BEYOND_SUBSET_LABELS), "kind": KIND_VALUES},
                "csv_url_template": _BEYOND_CSV_TEMPLATE,
            },
        ],
        "record_keys": sorted(default_rows[0]) if default_rows else [],
        "kinds": {
            "models": "Individual models (TabPFN, RealMLP, LightGBM, ...). The default.",
            "systems": (
                f"Whole systems (AutoGluon, TabFM+, hosted APIs, ...), marked '{SYSTEM_TYPE}' "
                "in the artifacts. They tune and ensemble many models inside their own budget, "
                "so ranking them against a single model compares different things. Only present "
                "when `entrants` admits them; see the `entrants` axis."
            ),
            "all": "Both, as the website's table shows them.",
        },
        "entrants": {
            key: f"{entrants_name(key)}. {entrants_note(key)}" for key in get_args(EntrantsAxis)
        },
        "tags": {
            "with-llm": (
                "An LLM is involved somewhere in this system, possibly as an agent. Its results "
                "depend on a model that can change and whose training data cannot be audited."
            ),
            "closed-source-api": (
                "The system runs behind a remote API whose internals cannot be inspected, so the "
                "numbers are not reproducible from source."
            ),
        },
        "choosing_a_model": (
            "For 'which model should I use', call get_pareto_frontier rather than reading the "
            "top row here: it returns the accuracy/time trade-off, since the highest-Elo model "
            "is often orders of magnitude slower than one just behind it. It also takes "
            "train- and predict-time budgets."
        ),
        "notes": (
            "Scores are read from the published artifacts, so they match the website exactly. "
            "Higher is better for elo and score; lower is better for rank, harmonic_rank, "
            "improvability_pct and the time columns. Every record carries a `kind` of "
            "'model' or 'system'; the get_* endpoints return models only unless asked."
        ),
    }


# Every description opens by naming the subject, because an MCP client may show one tool with
# no sibling for context and Gradio has no server-level instructions field. See the module
# docstring.
_WHAT_IS_TABARENA = (
    "TabArena is a living benchmark for tabular machine learning: predicting a target column "
    "from structured, rows-and-columns data (CSV files, spreadsheets, dataframes, database "
    "tables). It ranks tabular foundation models (TabPFN, TabICL, TabDPT, Mitra, TabM), "
    "gradient-boosted trees (LightGBM, XGBoost, CatBoost), neural networks (RealMLP, "
    "ModernNCA) and AutoML systems (AutoGluon) by Elo over 51 curated datasets, with "
    "measured training and inference time for each."
)


def register_api() -> None:
    """Register the endpoints. Call inside the app's ``gr.Blocks`` context."""
    gr.api(
        list_leaderboards,
        api_name="list_leaderboards",
        api_description=(
            f"{_WHAT_IS_TABARENA} This endpoint is the index: it lists the available "
            "leaderboards, the valid subset values for every other endpoint, the difference "
            "between a model and a whole system, the keys each record carries, and the raw "
            "CSV URLs for bulk download. Call it before the get_* endpoints when you are "
            "unsure which arguments exist."
        ),
    )
    gr.api(
        get_tabarena_leaderboard,
        api_name="get_tabarena_leaderboard",
        api_description=(
            f"{_WHAT_IS_TABARENA} This endpoint returns the ranked results (Elo, score, "
            "ranks, train and predict time) for one subset of the IID benchmark, selected by "
            "task type, dataset size, imputation and split protocol. Use it to look up where "
            "a named method stands, to compare two of them (\"is TabPFN better than "
            "LightGBM on small data\"), or to report the current state of the art on tabular "
            "data. Pass kind='models' (the default) for individual models, kind='systems' "
            "for whole AutoML systems such as AutoGluon, or kind='all' for both: a question "
            "about the best model wants 'models', one about the best AutoML framework wants "
            "'systems'."
        ),
    )
    gr.api(
        get_beyondarena_leaderboard,
        api_name="get_beyondarena_leaderboard",
        api_description=(
            "Ranked results for BeyondArena, the companion benchmark that measures the same "
            "tabular models (TabPFN, LightGBM, CatBoost, AutoGluon and the rest) where the "
            "IID assumption does not hold: random, temporal and grouped splits, sliced by "
            "dataset size and feature type. Use it whenever the question involves "
            "distribution shift, time-ordered rows, leakage-prone grouped splits, or how "
            "well a tabular model generalizes beyond a random train/test split. Takes the "
            "same kind='models' | 'systems' | 'all' distinction as the TabArena endpoint."
        ),
    )
    gr.api(
        get_pareto_frontier,
        api_name="get_pareto_frontier",
        api_description=(
            "The accuracy-versus-time trade-off among tabular models (TabPFN, TabICL, "
            "LightGBM, XGBoost, CatBoost, RealMLP, AutoGluon and the rest), measured on "
            "TabArena or BeyondArena. Returns the outright best model, the models nothing "
            "beats on both accuracy and speed at once (each with its speedup and accuracy "
            "gap versus the leader), and the best model that fits a train- or predict-time "
            "budget. Prefer it over the leaderboard endpoints for 'which model should I use "
            "on my tabular data', 'what is the best tabular model', 'what is a faster "
            "alternative to TabPFN', or anything about cost of training or serving: the top "
            "of the leaderboard is often orders of magnitude slower than a model just behind "
            "it. Returns a summary sentence you can relay."
        ),
    )
