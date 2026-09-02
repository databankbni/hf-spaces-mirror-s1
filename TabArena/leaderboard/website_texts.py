from __future__ import annotations

TITLE = """
<div style="display: flex; align-items: center; justify-content: center; gap: 16px; margin-bottom: 6px;">
  <img src="https://avatars.githubusercontent.com/u/210855230"
       alt="TabArena logo" width="56" height="56"
       style="flex: 0 0 auto; border-radius: 10px;">
  <div style="text-align: left;">
    <div id="space-title" style="font-size: 2.1em; font-weight: 700; line-height: 1.1;">TabArena Ecosystem</div>
    <div style="font-size: 1.05em; opacity: 0.8; margin-top: 2px;">
      Living benchmarks and leaderboards for machine learning on tabular data
    </div>
  </div>
</div>
"""
INTRODUCTION_TEXT = """
**TabArena** is a living benchmark for predictive machine learning on IID tabular data, built to measure the
peak performance of model-specific pipelines.
"""

# Conflict-of-interest statement, surfaced as a small corner hint that opens a
# CSS-only popup (see main.py). Condenses our public position: name the conflict
# plainly, then make the case — open code, open evidence, competing institutions —
# that it does not affect the validity of the results. No JS so it works inside
# the embedded Hugging Face Space iframe.
COI_HTML = """
<div class="coi-widget">
  <input type="checkbox" id="coi-toggle" class="coi-toggle">
  <label for="coi-toggle" class="coi-badge" title="Read our conflict-of-interest statement">🔍 What's our COI?</label>
  <div class="coi-overlay">
    <label for="coi-toggle" class="coi-backdrop" aria-label="Close"></label>
    <div class="coi-modal" role="dialog" aria-modal="true" aria-label="Conflict of interest statement">
      <label for="coi-toggle" class="coi-x" title="Close" aria-label="Close">×</label>
      <h2>🔍 Our Conflict of Interest</h2>
      <div class="coi-tldr"><b>TL;DR:</b> TabArena maintainers also develop models and are affiliated with
      commercial institutions. This creates a conflict of interest. We do not hide it, and we believe (and let
      anyone verify) that it does not affect the validity or scientific rigor of the results shown here.</div>
      <h3>Where the conflict lies</h3>
      <ul>
        <li><b>Maintainers vs. model developers.</b> Several of us develop tabular models that appear on this
        leaderboard. Building the benchmark and competing on it at the same time is a tension we can't fully
        remove (it is also documented in the <i>Competing Interests</i> section of our NeurIPS paper).</li>
        <li><b>Science vs. industry.</b> Some maintainers are employed by commercial institutions. We are also
        open-source researchers and PhD students maintaining TabArena in the open.</li>
      </ul>
      <p>We won't pretend that simply telling you we act without bias settles the question; it doesn't, and you
      are right to stay skeptical. And we'll say it outright: maintainers building a benchmark that features
      their own models is not, by itself, a prudent arrangement.</p>

      <h3>Why we believe the results still stand</h3>
      <p>Rather than ask you to trust us, we try to make trust unnecessary by letting anyone check everything:</p>
      <ul>
        <li><b>Everything is open source:</b> the benchmarking code, the leaderboard, the plots, the model
        implementations, and the models themselves.</li>
        <li><b>So is the evidence:</b> we publish the raw predictions, hardware details, and exact software
        environments. Anyone can reproduce our numbers, hunt for errors, submit their own model, and call us
        out.</li>
      </ul>
      <p>This puts the burden of proof on the other side: we hand any critic everything they would need to prove
      we did something wrong. Almost no one will check all of it, but the point is that anyone can.</p>

      <h3>Competing interests as checks and balances</h3>
      <p>TabArena is maintained, on purpose, by people from <i>different and competing</i> institutions, whose
      interests pull against each other. That way no single model or company sets the rules unchallenged, and we
      keep widening that mix as the benchmark grows.</p>

      <h3>What we are still working on</h3>
      <p>TabArena is young and still changing fast. The biggest thing we're missing is governance: we'd like
      proper open-source governance, and we have a TabArena organization and are heading that way, but right now
      we're too few people with too little time to set it up. We bring in more of the community with every
      release, and we'll keep adjusting.</p>

      <a class="coi-cta" href="https://tabarena.ai/code" target="_blank" rel="noopener noreferrer">💬 Concerns? Open a public issue for a public discussion ↗</a>
    </div>
  </div>
</div>
"""

# Jump menu, built like COI_HTML: a checkbox toggles a CSS-only popup, so it needs no JS and
# works inside the embedded Hugging Face Space iframe. Targets are the section anchors set in
# pages.render_internal_page.
TOC_HTML = """
<div class="toc-widget">
  <input type="checkbox" id="toc-toggle" class="toc-toggle">
  <label for="toc-toggle" class="toc-badge" title="Jump to a section">📑 Contents</label>
  <label for="toc-toggle" class="toc-backdrop" aria-label="Close"></label>
  <div class="toc-menu">
    <a href="#ta-controls-anchor" onclick="document.getElementById('toc-toggle').checked=false">🎛️ Select Your Leaderboard</a>
    <a href="#ta-overview-section" onclick="document.getElementById('toc-toggle').checked=false">🔭 Performance across leaderboards</a>
    <a href="#lb-detailed" onclick="document.getElementById('toc-toggle').checked=false">🏆 TabArena Leaderboard</a>
    <a href="#ta-perdataset-section" onclick="document.getElementById('toc-toggle').checked=false">🔎 Per-dataset results</a>
    <a href="#ta-agentic-section" onclick="document.getElementById('toc-toggle').checked=false">⚙️ Agentic Use &amp; Interpretation</a>
    <a href="#ta-version-section" onclick="document.getElementById('toc-toggle').checked=false">📂 Version History</a>
  </div>
</div>
"""

OVERVIEW_DATASETS = """
The leaderboard is built on a manually curated collection of **51 classification and regression datasets**
for independent and identically distributed (IID) tabular data. They span the small-to-medium data regime and
were chosen to reflect a wide range of real-world predictive machine learning use cases.

**Subsets:** Use the task and dataset-size tabs above the leaderboard to focus on a subset, and the toggles
to include imputed models or switch to TabArena-Lite.
"""
OVERVIEW_MODELS = """
TabArena ranks two kinds of entrant, and the difference is the pipeline.

- 🤖 **Models** are single methods, and TabArena owns the pipeline around them. It tunes each one
  under a shared protocol on the same compute budget as every other model, and reports three
  regimes: **default**, **tuned**, and an **ensemble of tuned** configurations. Each sits in a
  tested, real-world pipeline built by the maintainers and, where possible, with the model's
  original authors.
- 📊 **Systems** own their pipeline end to end. A system decides what to fit, how much to tune it
  (if at all), and how to combine the result, all inside one budget; TabArena hands it the data
  and the constraints and nothing else. AutoGluon is the familiar example; TabFM+, agents and
  hosted APIs are others.

Both are measured the same way and held to the same budget, so the comparison is fair on final
performance. What differs is how much the setup is controlled. A model's score isolates one
method under a fixed pipeline; a system is free to step outside those constraints and do whatever
works, so its score reflects the whole package without saying which part earned it. That makes
systems the better guide to what you should run, and models the better basis for a research
claim. Use **Who's competing?** at the top of the page to choose which of them appear.

Systems carry tags for the things that might rule them out for you. **with LLMs** means an LLM
is somewhere in the loop, possibly as an agent, so the result depends on a model we cannot
inspect and that may already have seen the test data. 🔒 **closed-source API** means the system
runs remotely, we cannot see what it did, and it can behave differently on another day.

**Verified:** A ✔️ marks an implementation confirmed by the original authors or the TabArena
maintainers. Established, stable models (XGBoost, LightGBM, CatBoost, Random Forests, the
baselines) count as verified once the maintainers confirm the implementation. Treat unverified or
very recent entries with more caution.
"""
OVERVIEW_METRICS = """
Each model is scored on every dataset with a **metric** suited to the task: **ROC AUC** for binary
classification, **log-loss** for multiclass classification, **RMSE** for regression. Those per-dataset
scores are then combined into a single leaderboard number by an **aggregation**. The leaderboards are ranked by the **Elo** aggregation, and we report several complementary
aggregations (Score, Improvability, Average & Harmonic Rank). Click any column in the key above the leaderboard
table for its definition and motivation.

**Imputation:** Toggle *Include imputed models* to add models that cannot run on every dataset, whether
because of the task type or the dataset size. Their missing results are filled in with a default
RandomForest's, which drags their score down. That is deliberate: a model that only covers part of the
benchmark should not rank as if it covered all of it.

**Repeats:** Toggle *TabArena-Lite* to score each experiment on a single repeat instead of several. It is
noisier than the full setting, but much cheaper to compute and usually close enough to be worth it.
"""
# One warning per system category, shown only when that category is competing. They are not the
# same kind of caveat, and the styling says so: the open-source one is about how to *read* a
# result that is otherwise sound, so it gets the amber accent; the other two are about results
# that may not be sound at all, and keep the red.
WARNING_SYSTEMS = """
### ⚠️ Systems and models are not the same kind of result

A system faces the same datasets, splits and metric as every model here, and it is held to the
same budget, so the comparison is fair on final performance: if a system scores higher, it really
did do better on this benchmark. What it gives up is the controlled setup. A model is one method
under a fixed pipeline, so its score isolates the method; a system is free to step outside those
constraints and do whatever works, so its score tells you what the whole package achieves without
telling you which part earned it.
"""

WARNING_WITH_LLM = """
### ⚠️ Results from LLM-based systems may be contaminated

These systems call an LLM, in some cases as an agent driving the whole pipeline. We cannot see
what that model was trained on, so we cannot rule out that it has already seen these datasets,
or read about them. A score that looks strong may be partly recall rather than prediction.

The model behind an API can also be replaced without notice, so the same system may not score
the same next month.
"""

WARNING_CLOSED_API = """
### ⚠️ Closed-source API results cannot be verified

These systems run on someone else's machine. We send the data and record what comes back, but we
cannot inspect what ran, pin a version, or reproduce the numbers from source. Treat them as a
measurement of a service on the day it was queried rather than of a fixed method.
"""

# The per-dataset browser. Shown while collapsed (the teaser), above it once opened (the
# intro), and instead of it when a leaderboard has no per-dataset artifact yet.
PER_DATASET_TEASER = (
    "Open this to browse the benchmark one dataset at a time: pick a method and see where it "
    "wins, where it loses, and how the whole field got there on each dataset."
)

PER_DATASET_MISSING = (
    "Per-dataset results have not been published for this leaderboard yet. They are generated "
    "with the rest of the artifacts and appear here once this combination has been rerun."
)

ABOUT_TEXT = r"""
TabArena is a living benchmark for predictive machine learning on tabular data. Here are the key resources
for understanding, using, and contributing to it.

#### 📚 Papers & talks
- The paper, [TabArena: A Living Benchmark for Machine Learning on Tabular Data](https://tabarena.ai/paper-tabular-ml-iid-study), covers the methodology and the motivation.
- A [talk on YouTube](https://www.youtube.com/watch?v=mcPRMcJHW2Y) walks through it.

#### 🧪 Benchmark your own method
Compare your method against the pre-computed results for every model on the leaderboard. The
[code examples](https://tabarena.ai/code-examples) are the place to start.

#### 🤝 Contribute
- To add your model or submit results, follow the guidelines in the [code repository](https://tabarena.ai/code).
- For anything about the benchmark datasets themselves, see the [data documentation](https://tabarena.ai/data-tabular-ml-iid-study).

#### 📈 Metrics & aggregations
Each model is scored per dataset with a task-appropriate **metric** (ROC AUC, log-loss, or RMSE); these scores
are combined across datasets by an **aggregation**. The leaderboards are ranked by the **Elo** aggregation,
alongside complementary aggregations (Score, Improvability, Average & Harmonic Rank). Click any column in the
key above the leaderboard table for its definition and motivation.

#### 📬 Contact
For most questions, please open an issue in the relevant GitHub repository or here on Hugging Face. For
anything else, reach out to **mail@tabarena.ai**.

#### 👥 Core maintainers
[Nick Erickson](https://github.com/Innixma) · [Lennart Purucker](https://github.com/LennartPurucker) · [Andrej Tschalzev](https://github.com/atschalz) · [David Holzmüller](https://github.com/dholzmueller)
"""

CITATION_BUTTON_LABEL = (
    "If you use TabArena or the leaderboard in your research please cite the following:"
)
CITATION_BUTTON_TEXT = r"""@inproceedings{erickson2025tabarena,
  title     = {TabArena: A Living Benchmark for Machine Learning on Tabular Data},
  author    = {Erickson, Nick and Purucker, Lennart and Tschalzev, Andrej and Holzm{\"u}ller, David and Desai, Prateek Mutalik and Salinas, David and Hutter, Frank},
  booktitle = {Proceedings of the 39th Conference on Neural Information Processing Systems (NeurIPS)},
  year      = {2025},
  url       = {https://arxiv.org/abs/2506.16791}
}
"""

# Single source of truth for the interactive metric/aggregation reference next to the table.
METRICS = [
    {
        "name": "🏆 Elo (ranking aggregation)",
        "details": (
            "A pairwise comparison-based rating: each model's rating predicts its expected win "
            "probability against others, with a 400-point gap corresponding to a 10:1 (~91%) "
            "expected win rate. We calibrate 1000 Elo to a default Random Forest and bootstrap "
            "95% confidence intervals. Elo is computed from ROC AUC (binary), log-loss "
            "(multiclass), and RMSE (regression)."
        ),
        "why": (
            "Elo aggregates many head-to-head comparisons into a single interpretable scale that "
            "is robust to the choice of error normalization and to a few extreme datasets, which "
            "is why it is our primary ranking aggregation."
        ),
    },
    {
        "name": "📊 Score",
        "details": (
            "Following TabRepo, a normalized score: we linearly rescale the error so the best "
            "method scores 1 and the median method scores 0 (negative values clipped to 0), then "
            "average across datasets."
        ),
        "why": (
            "Gives an intuitive 0–1 sense of how close a model is to the best, complementing "
            "Elo's purely relative scale."
        ),
    },
    {
        "name": "📉 Improvability (%)",
        "details": (
            "How many percent lower the best method's error is than this method's, on a dataset, "
            "averaged over datasets: (err − best_err) / err × 100%. Always between 0% and 100%."
        ),
        "why": (
            "Directly answers 'how much could I still gain by switching to the best model here?' "
            "in the error-relative terms practitioners care about."
        ),
    },
    {
        "name": "🔢 Average Rank",
        "details": "Per-dataset rank of each method (lower is better), averaged across datasets.",
        "why": (
            "Simple and familiar, but sensitive to ties and treats every dataset equally "
            "regardless of how large the performance gap is."
        ),
    },
    {
        "name": "🎯 Harmonic Rank",
        "details": (
            "The harmonic mean of per-dataset ranks, 1 / ((1/N) · Σ 1/rankᵢ), which more strongly "
            "rewards being very good on some datasets."
        ),
        "why": (
            "Favors models that are sometimes excellent (and thus useful inside an ensemble or "
            "portfolio) over models that are uniformly mediocre."
        ),
    },
    {
        "name": "⏱️ Train / Predict Time (s/1K)",
        "details": (
            "Median training and prediction time in seconds per 1,000 samples, measured on the "
            "hardware shown in the Hardware column."
        ),
        "why": (
            "Peak accuracy is not free. These columns let you trade quality against training "
            "cost and inference latency for your own deployment."
        ),
    },
    {
        "name": "✔️ Verified",
        "details": (
            "✔️ marks models whose implementation was verified by the original authors or the "
            "TabArena maintainers; ➖ marks contributed-but-unverified implementations."
        ),
        "why": (
            "Recent or unverified results should be read with more caution; we surface this so "
            "rankings are not taken at face value."
        ),
    },
    {
        "name": "🧩 Imputed (%)",
        "details": (
            "Percentage of datasets where a model could not run (due to task or dataset-size "
            "constraints) and was imputed with a default Random Forest's performance."
        ),
        "why": (
            "Imputation makes benchmark coverage part of the score rather than hiding it: a model "
            "is penalized for not being able to run everywhere."
        ),
    },
]

AGENTIC_GUIDE = """
### ⚙️ Using TabArena results in agentic & automated pipelines

TabArena is designed so that an automated system, an LLM agent included, can pick a tabular model from
evidence rather than guesswork. The leaderboards expose exactly the signals such a system needs:
accuracy (**Elo** / **Score**), robustness (**Average** & **Harmonic Rank**), and cost
(**Train / Predict Time**). A few heuristics for choosing automatically:

- **No tuning budget?** Compare the **(default)** variants, which show what each model achieves out-of-the-box,
  with no hyperparameter search.
- **Small datasets?** Check the **Small** subset to see which models lead in that regime.
- **Medium / larger datasets?** Check the **Medium** subset for the strongest models at that scale.
- **Task-specific?** Use the **Classification**, **Regression**, **Binary**, and **Multiclass** subsets to find the
  leaders for your task type.
- **Latency-bound deployment?** Sort by **Median Predict Time (s/1K)** to weigh accuracy against inference cost.
- **Want one robust pipeline instead of a single model?** Switch *Who's competing?* to include systems and look at **AutoGluon**.
- **Production trust:** prefer **Verified ✔️** models, and treat unverified or very recent entries as provisional.

These are starting heuristics rather than guarantees, so always validate on your own data. These aggregations and their
trade-offs are motivated in our [paper](https://arxiv.org/abs/2506.16791).

#### Reading the numbers programmatically

Every leaderboard on this page is a CSV in the Space repo, so a script or agent can read the same values the
table shows without scraping it:

```bash
curl -sL https://huggingface.co/spaces/TabArena/leaderboard/resolve/main/data/imputation_yes/splits_all/tasks_all/datasets_all/website_leaderboard.csv
```

Swap the path segments for another subset (`imputation_{yes,no}` / `splits_{all,lite}` /
`tasks_{all,classification,regression,binary,multiclass}` / `datasets_{all,small,medium}`); BeyondArena lives
under `data_beyondarena/subsets/{subset}/`.

#### Connecting an AI assistant (MCP)

This Space is also an **MCP server**, so an assistant can query the leaderboard as a tool instead of you
pasting numbers into a chat. Four tools are exposed:

- `list_leaderboards`: the available benchmarks, their valid subset values, and the keys every record carries.
  Worth calling first.
- `get_tabarena_leaderboard`: ranked results for one IID subset (tasks, datasets, imputation, splits).
- `get_beyondarena_leaderboard`: the same for a BeyondArena subset.
- `get_pareto_frontier`: the accuracy-versus-time trade-off. Ask this rather than reading the top row: the
  highest-Elo model is often far slower than one just behind it, and this returns the outright best, the
  models nothing beats on both axes at once, and the best model that fits a train- or predict-time budget.

All four take a `kind` of `models` (the default), `systems`, or `all`: individual models like TabPFN, whole
AutoML systems like AutoGluon, or both.

**Claude Code**: add the server once, then use it in any session:

```bash
claude mcp add --transport http tabarena https://tabarena-leaderboard.hf.space/gradio_api/mcp/
```

Add `--scope user` to make it available across all your projects. `claude mcp list` shows `✔ Connected`
when it worked, and `/mcp` inside a session lists the tools. The trailing slash on the URL matters.

**Claude Desktop and claude.ai**: add the same URL as a custom connector in settings.

Any other MCP client works too; the endpoint speaks streamable HTTP. Then just ask, for example:
*"Using TabArena, what's the best tabular model for a 5k-row regression dataset if inference has to stay
under 0.5 s per 1000 rows?"*
"""

# --- BeyondArena tab -------------------------------------------------------
# BeyondArena is the second internal leaderboard: the first unified benchmark for
# tabular data that goes beyond the IID assumption. Copy mirrors the TabArena
# OVERVIEW_* / ABOUT_TEXT / CITATION_* structure but with BeyondArena specifics.
BEYOND_INTRODUCTION_TEXT = """
**BeyondArena** is the first unified, holistic benchmark for tabular data that goes **beyond the IID
assumption**: spanning IID, temporal, and grouped splits across a wide range of dataset sizes and
feature dimensionalities.
"""

BEYOND_OVERVIEW_DATASETS = """
BeyondArena is built on a curated collection of **142 datasets** that deliberately go **beyond the IID
assumption**. Datasets span three **split regimes**: **IID / random**, **temporal** (train on the
past, test on the future), and **grouped** (disjoint groups between train and test): across a wide
range of **sizes** (tiny → large) and **feature dimensionalities** (incl. text and high-cardinality
categorical columns).

**Subsets:** Use the tabs above the leaderboard to focus on a split regime, size bucket, or feature
subset. Every leaderboard is always computed on the recommended **core** protocol (each dataset's
first few splits, already enough for stable rankings).
"""
BEYOND_OVERVIEW_MODELS = """
Like TabArena, BeyondArena focuses on **model-specific pipelines**: each model is wrapped in a tested,
tuned real-world pipeline, evaluated with its **default** configuration, a **tuned** configuration,
and as an **ensemble of tuned** configurations. The benchmark spans tree-based models, deep-learning
models, and tabular **foundation models**.

**Verified models:** A ✔️ in the *Verified* column marks models whose implementation was confirmed by
the original authors or the maintainers. Treat unverified or very recent models with more caution.
"""
BEYOND_OVERVIEW_METRICS = """
**Metrics vs. aggregations.** Each model is scored on every dataset with a task-appropriate **metric**
(**ROC AUC** for binary classification, **log-loss** for multiclass, **RMSE** for regression). These
per-dataset scores are combined into a single leaderboard number by an **aggregation**. The
leaderboards are ranked by the **Elo** aggregation, alongside complementary aggregations (Score,
Improvability, Average & Harmonic Rank). Click any column in the key above the table for its
definition.

**Core protocol:** All results use BeyondArena's recommended **core** subset, a set of splits chosen to
yield stable rankings (see the appendix of the [paper](https://arxiv.org/abs/2606.30410) for how we computed it).

**Imputation:** Models that cannot run on all datasets (due to task or dataset-size constraints) have
their missing results imputed with a default RandomForest, which penalizes them for not running
everywhere. A `[X% IMPUTED]` tag marks affected models.
"""

# Shown in the expandable "What do the subsets mean?" panel next to the subset tabs.
BEYOND_SUBSETS_EXPLAINER = """
BeyondArena is sliced into **curated subsets** so you can see how methods hold up *beyond* the IID
assumption, and specifically on the kinds of data where an average hides big differences.
Pick a subset with the tabs below; **Full** is the whole benchmark. Every subset is evaluated on the
recommended **core** protocol.

**🔀 Split regime, the beyond-IID axis** (how the train/test splits are drawn)
- **IID**: random splits, the classic i.i.d. assumption (train and test come from the same distribution).
- **Temporal**: time-based splits: train on the past, test on the future (distribution shift over time).
- **Grouped**: disjoint groups between train and test (e.g. different users/sites), so no group leaks across the split.

**📏 Dataset size** (by number of training rows)
- **Tiny**: ≤ 1,000 rows &nbsp;·&nbsp; **Small**: 1,001–10,000 &nbsp;·&nbsp; **Medium**: 10,001–100,000 &nbsp;·&nbsp; **Large**: 100,001–1,000,000

**🧬 Features**
- **Low-dim**: ≤ 100 columns after preprocessing &nbsp;·&nbsp; **High-dim**: more than 100 columns.
- **Text**: datasets containing one or more text columns.
- **High-cardinality**: datasets containing one or more high-cardinality categorical columns.
"""

BEYOND_ABOUT_TEXT = r"""
BeyondArena is the second benchmark in the TabArena Ecosystem, and the first unified benchmark
for tabular data that goes beyond the IID assumption. It is built on the same experiment / runner /
evaluation code as [TabArena](https://tabarena.ai).

#### 📚 Paper
- The paper, [Beyond IID: How General Are Tabular Foundation Models, Really?](https://arxiv.org/abs/2606.30410), covers the methodology, datasets, and findings.

#### 📦 Datasets & Data Foundry
BeyondArena's [142 datasets](https://huggingface.co/datasets/TabArena/BeyondArena) are curated and
distributed through **Data Foundry**, a framework for curating tabular datasets introduced alongside
the benchmark. Datasets are downloaded and converted on demand.

#### 🧪 Benchmark your own method
BeyondArena uses the same API as TabArena; the only swap is the context (`BeyondArenaContext`). See
the [code examples](https://tabarena.ai/code) to compare your model against the cached baselines.

#### 📬 Contact
For most questions, please open an issue in the relevant GitHub repository or here on Hugging Face.
For anything else, reach out to **mail@tabarena.ai**.
"""

BEYOND_CITATION_BUTTON_LABEL = "If you use BeyondArena in your research please cite the following:"
BEYOND_CITATION_BUTTON_TEXT = r"""@misc{purucker2026beyondiid,
  title         = {Beyond IID: How General Are Tabular Foundation Models, Really?},
  author        = {Purucker, Lennart and Tschalzev, Andrej and Erickson, Nick and Blayer, Gioia and Holzm{\"u}ller, David and Arazi, Alan and Pfefferle, Alexander and Tajjar, Mustafa and Varoquaux, Ga{\"e}l and Hutter, Frank},
  year          = {2026},
  eprint        = {2606.30410},
  archivePrefix = {arXiv},
  primaryClass  = {cs.LG},
  url           = {https://arxiv.org/abs/2606.30410}
}
"""

RAMANBENCH_TAGLINE = "Benchmarking machine learning on Raman spectra."
RAMANBENCH_BLURB = """
Raman spectra are a **special kind of tabular data**: each spectrum is a fixed-length vector of intensity
measurements across wavenumbers, which makes them a natural fit for the tabular ML methods benchmarked across
the TabArena Ecosystem.

> ℹ️ **Please note:** RamanBench is developed and maintained independently, not by the TabArena team. We have
> reviewed it, endorse its methodology, and are glad to feature it as a trusted part of the TabArena Ecosystem.

**RamanBench** is a domain-specific benchmark for machine learning on Raman spectroscopy data. Raman spectroscopy
is a well-established, non-invasive technique for inferring the composition and molecular properties of materials:
a sample is excited with a monochromatic laser beam, and the small fraction of light that is inelastically
scattered by the vibrations of its molecular bonds shifts in energy, encoding information about the molecular
structure. These spectra are used across material identification, bioprocess monitoring, medical diagnostics,
pharmaceutical quality control, and chemical process analysis, and machine learning has become central to
automating their analysis, across material classification, disease detection, and the quantitative prediction of
chemical concentrations. RamanBench brings a dedicated, reproducible leaderboard to this domain; explore the full
benchmark on Hugging Face, or read the paper for the methodology and results.
"""

# --- "Time-series?" signpost page ------------------------------------------
# TabArena is tabular ML; time series is a neighbouring but distinct field with
# its own dedicated benchmarks. This page introduces the domain, explains how it
# differs from IID tabular ML, highlights the TimeCopilot "Impermanent" living
# leaderboard, and points to the main forecasting and classification/regression
# benchmarks (the time-series related work referenced from BeyondArena).
TIMESERIES_TAGLINE = "Tabular ML lives here; time series can be found elsewhere."

TIMESERIES_INTRO = """
**TabArena** and **BeyondArena** benchmark machine learning on **tabular data**: including tabular data with
*temporal* relationships (BeyondArena's **`temporal`** subset). Dedicated **time-series** modelling is the
neighbouring world, split into two families:

- **Forecasting**: extrapolate a series *forward* in time (rolling-window evaluation, forecast horizons,
  careful leakage control).
- **Classification & regression**: map a *whole* sequence to a label or a continuous target.

> ℹ️ **Note:** these benchmarks are maintained independently, not by the TabArena team.
"""

TIMESERIES_FORECASTING = """
#### 📈 Time-series forecasting benchmarks & leaderboards

- **[Impermanent](https://impermanent.timecopilot.dev/)** (TimeCopilot): the live, leakage-free weekly
  leaderboard for *temporal generalization*. [Paper](https://arxiv.org/abs/2603.08707).
- **[GIFT-Eval](https://huggingface.co/spaces/Salesforce/GIFT-Eval)** (Salesforce): a broad general-purpose
  benchmark: 23 datasets, ~144k series and 177M points across 7 domains and 10 frequencies.
  [Paper](https://arxiv.org/abs/2410.10393).
- **[fev-bench](https://huggingface.co/spaces/autogluon/fev-bench)** (AutoGluon / Amazon): 100 realistic
  forecasting tasks over 7 domains, 46 of them with covariates.
  [Paper](https://arxiv.org/abs/2509.26468).
- **[TIME](https://huggingface.co/spaces/Real-TSF/TIME-leaderboard)** (ICML 2026): a next-generation,
  leakage-controlled benchmark for zero-shot foundation models: 50 freshly collected, human-vetted datasets and
  98 forecasting tasks. [Paper](https://arxiv.org/abs/2602.12147).
"""

TIMESERIES_CLASSREG = """
#### 🏷️ Time-series classification & regression
Here the task is to label or score an *entire* sequence rather than extend it:

- **[UCR Time Series Archive](https://arxiv.org/abs/1810.07758)**: the standard *univariate* classification
  archive.
- **[UEA multivariate archive](https://arxiv.org/abs/1811.00075)**: its *multivariate* counterpart, recently
  extended by **["The Multiverse of Time Series ML"](https://arxiv.org/abs/2603.20352)** (2026).
- **[Time Series Extrinsic Regression (TSER)](http://tseregression.org/)**: the Monash/UEA/UCR archive for
  predicting a continuous target from a whole series. [Paper](https://arxiv.org/abs/2006.10996).
"""

TIMESERIES_CLOSING = """
Building a time-series benchmark you would like featured here, or curious whether tabular foundation models
transfer to your temporal data? We would love to hear about it: see the **➕ Your Benchmark?** tab.
"""

# --- "Your Benchmark?" invite page -----------------------------------------
# A welcoming call-to-action inviting the community to bring their own benchmark
# into the TabArena Ecosystem — either an existing one we endorse & double-check
# (like RamanBench) or a brand-new one we help shape.
YOUR_BENCHMARK_TAGLINE = (
    "Your benchmark could live right here. Let's build this out together."
)

YOUR_BENCHMARK_INTRO = """
The **TabArena Ecosystem** is more than a single leaderboard. It is growing into a home for *living,
trustworthy benchmarks* for machine learning on tabular and tabular-like data, each one reproducible
and clearly documented.

Maybe you already maintain a benchmark and want it to reach more people. Maybe you are just starting to
think about building one and could use a hand. Either way there is a place for it here, and we are happy
to help you get there. 🤝
"""

# Two side-by-side "paths" describing how a benchmark can join the ecosystem.
# (icon, heading, body) — rendered as cards in render_invite_page().
YOUR_BENCHMARK_PATHS = [
    (
        "🔬",
        "You already have a benchmark",
        "Wonderful! If you maintain a reproducible benchmark for a tabular (or tabular-like) ML problem, "
        "we would love to feature it. We will go through the methodology with you, double-check the "
        "results, and once we are confident in it, endorse it and add it to the ecosystem as a "
        "trusted, clearly attributed benchmark, exactly as we did with RamanBench. You stay the owner "
        "and maintainer; we help with quality, visibility, and a shared home.",
    ),
    (
        "🌱",
        "You're building a new one",
        "Even better to talk early. Designing a fair, reproducible benchmark is genuinely hard, and we "
        "have learned a lot building TabArena. Reach out and we can help with dataset curation, "
        "evaluation protocols, metrics, leaderboard tooling, and fitting cleanly into the wider "
        "ecosystem, so your benchmark stands on solid ground from day one.",
    ),
]

YOUR_BENCHMARK_FIT = """
#### ✨ What makes a good fit
- **Tabular at heart**: classic tabular data, or data that is naturally represented as fixed-length
  feature vectors (like Raman spectra).
- **Reproducible**: clear datasets, splits, metrics, and an evaluation protocol that others can re-run.
- **Open & well-documented**: ideally backed by a paper or write-up and public code and data.

Not sure whether your idea fits? **Reach out anyway**: we are glad to think it through with you, and we
genuinely enjoy meeting people building benchmarks for the community.
"""

YOUR_BENCHMARK_CONTACT = """
#### 📬 Get in touch
Drop us a line and tell us about your benchmark: what it covers, where the data comes from, and what you
are hoping to achieve. No formal proposal needed to start a conversation; an email is plenty. You can email
the TabArena team, or reach out to our primary contact, **Lennart Purucker**, directly.
"""

# (label, href, variant) — contact buttons rendered as new-tab anchors.
YOUR_BENCHMARK_LINKS = [
    (
        "✉️ Email the TabArena team ↗",
        "mailto:mail@tabarena.ai?subject=New%20benchmark%20for%20the%20TabArena%20Ecosystem",
        "primary",
    ),
    (
        "Primary contact: Lennart Purucker ↗",
        "https://github.com/LennartPurucker",
        "secondary",
    ),
]

VERSION_HISTORY_BUTTON_TEXT = """
**Current Version: TabArena-v0.1.8.2**

The following details updates to the leaderboard (date format is YYYY/MM/DD):

* 2026/08/17-v0.1.8.2:
    * The *Performance across leaderboards* table now has a row per model variant, so default,
      tuned and tuned + ensembled each get their own line and the cost of tuning is on the page.
      Its new *One per model* toggle collapses each method to its best variant, as the win-rate
      matrix's button of the same name does.
    * Fixed the *Fit (s/1K)* and *Infer (s/1K)* columns of that table, which reported the cheapest
      variant of each model rather than the variant on the row. A row labelled
      *(tuned + ensembled)* showed its default's fit time, roughly 200x too low, because tuning
      fits 200 configurations where the default fits one.
* 2026/08/10-v0.1.8.1:
    * Updated verified model: ChimeraBoost, now at version 0.30.0.
* 2026/08/06-v0.1.8:
    * New *Per-dataset results* section: the benchmark one dataset at a time. Pick a contender
      and each row reports its rank and its gap to the best method on that dataset, with a ★
      marking where it landed among the whole field. Sort by any column, search or filter the
      list, then select a dataset for its own tuning trajectories and its full ranking; ← and
      → step through the list.
    * The full leaderboard table and the per-dataset browser are collapsed by default, so the
      page opens on the figures; the contents row above them opens either one. The two
      reference panels about the site itself now sit under an *Appendix* heading.
    * Systems are now their own class of entrant rather than a "reference pipeline" alongside
      the models. A system is a whole pipeline that picks, tunes and ensembles models inside
      its own budget: AutoGluon, TabFM+, an agent, a hosted API.
    * New *Who's competing?* control at the top of the page. Every leaderboard number is
      relative to the field (Elo is a pairwise rating, Improvability is the gap to the best
      entrant), so each setting is a separate published evaluation rather than a row filter.
      Models-only is the default, and it is now genuinely models-only: previously AutoGluon
      sat in the Elo pool while the figures hid it.
    * New *I care about* control, which leads with the figure that answers your question:
      best quality, fastest to train, or fastest to predict.
    * Systems carry tags for what you may need to rule out: 🤖 with LLMs and 🔒 closed-source
      API. See the new "Systems" info panel.
    * Add new verified systems: AutoGluon 1.6 (extreme, 4h) and AutoGluon 1.6
      (noncommercial, 4h). The noncommercial preset is extreme plus TabPFN-3, whose license
      does not permit commercial use.
    * Add new verified system: TabFM+. It ran before the July rerun that stopped reloading
      models from disk around inference, so its inference time reads high next to the models
      it sits beside on the Pareto front.
    * The win-rate matrix carries every tuning variant again, so you can compare a tuned
      model against another model's default. It still opens on one row per model.
    * The jump menu, the conflict-of-interest badge and the selection summary stay on screen
      on huggingface.co, and the conflict-of-interest popup opens where you are reading
      instead of sending you back to the top of the page.
    * An AI assistant connected to this Space now gets tool descriptions that say what
      TabArena measures and which questions each tool answers, so it can tell that a question
      about tabular models belongs here. The entrant pool is exposed as an argument too.
* 2026/08/03-v0.1.7.1:
    * Add new verified model: EXAONE-Tabular (classification only; its regression results are imputed)
* 2026/07/31-v0.1.7:
    * The leaderboard can now be queried by an AI assistant: this Space is an MCP server with
      tools for the TabArena and BeyondArena leaderboards and for the accuracy-versus-time
      Pareto frontier. Setup instructions are under "Agentic Use & Interpretation".
    * Every published leaderboard is also readable as a plain CSV from the Space repo, so
      scripts can use the same numbers the tables show.
    * The full leaderboard table is now interactive: every column sorts, headers explain what
      they measure, and you can filter by model family, model, or variant, then download the
      result as a CSV.
    * New interactive win-rate matrix and Leaderboard Overview, alongside the existing Pareto
      and tuning-trajectory explorers.
    * Every figure opens in paper view (white background, chart and legend only) and can be
      downloaded as SVG, PDF, or PNG. "Edit view" opens the controls, and one click switches
      to the static figure.
    * Figures and subset selectors were restyled so it is clearer which controls belong
      together and where each figure begins.
    * Numbers now use a "." decimal separator whatever your browser locale is, so the tables
      and figures agree.
* 2026/07/21-v0.1.6:
    * Redesigned Pareto-front and tuning-trajectory figures: model-family colors, with the Pareto
      front and highlighted methods in focus while all other methods are greyed out.
    * New interactive Pareto explorers per subset: click methods or model families to highlight
      them, switch the y-axis between Improvability and Elo, and hover any point for exact values;
      partially imputed methods are marked with a dashed ring.
* 2026/07/21-v0.1.5.5:
    * Add new verified model: Nori-30M
* 2026/07/21-v0.1.5.4:
    * Add new unverified model: TabDPT-Turbo
    * Updated existing models with improved train/inference time measurement (untimed environment
      warm-up + persisted inference): CatBoost, ChimeraBoost, EBM, ExtraTrees, Nori, TabFM,
      TabICLv2, TabPFN-3, TabSwift
* 2026/07/10-v0.1.5.3:
    * Add new unverified model: TabSwift
* 2026/07/08-v0.1.5.2:
    * Add new verified model: TabFM
* 2026/06/30-v0.1.5.1:
    * Add new verified models: Nori, ChimeraBoost
* 2026/06/22-v0.1.5:
    * New leaderboard UI: top-level tabs for multiple leaderboards, a cross-subset Elo overview, imputation
      and TabArena-Lite as toggles, an interactive metric reference, and an agentic-use guide.
* 2026/06/02-v0.1.4:
    * Add new verified models: TabPFN-3, iLTM (only 25 configs)
    * Add new unverified model: OrionMSP
    * Finish model integration: LimiX now runs on all datasets.
* 2026/03/25-v0.1.3.1:
    * Add new verified model: TabPFN-2.6
* 2026/03/24-v0.1.3: 
    * Add new verified models: TabICLv2, TabSTAR, PerpetualBooster.
    * Add new verified reference pipeline: AutoGluon 1.5 (extreme, 4h).
    * Added Binary and Multiclass task views.
    * Removed TabPFNv2-data view in results as most recent tabular foundation models work on all tasks on TabArena.
    * Removed AutoGluon 1.4 (extreme, 4h) from results as it is replaced by AutoGluon 1.5 (extreme, 4h).
* 2025/12/11-v0.1.2.2: 
    * Add new unverified model: SAP-RPT-OSS (a.k.a.: ConTextTab, sap-rpt-1-oss)
* 2025/11/27-v0.1.2.1: 
    * Make tuning trajectories start from the default configuration.
    * UI improvements and more user-friendly explanations.
* 2025/11/22-v0.1.2: Add newest version of TabArena LB for NeurIPS 2025
    * New UI and new leaderboard subsets for different dataset sizes, tasks, and imputation + general polish. 
    * Some metrics have been refactored and made more stable (see GitHub for details).
    * Updated Reference Pipeline to include AutoGluon v1.4 with the extreme preset.
    * Updated existing models: RealMLP, TabDPT, EBM
    * Add new verified models: Mitra, xRFM, RealTabPFN-v2.5
    * Add new unverified models: TabFlex, BetaTabPFN, LimiX
* 2025/06/13-v0.1.1: Add data for all subsets and re-runs on GPU; Add leaderboards for subsets;
 new overview; add Figures to LBs.
* 2025/05-v0.1.0: Initialization of the TabArena-v0.1 leaderboard.

Old Leaderboards (with major changes) can be found at:
* Tabarena-v0.1 and TabArena-v0.1.1: https://huggingface.co/spaces/TabArena-Legacy/TabArena-v0.1.1
* Tabarena-v0.1.2.2: https://huggingface.co/spaces/TabArena-Legacy/TabArena-v0.1.2
* Tabarena-v0.1.3.1: https://huggingface.co/spaces/TabArena-Legacy/TabArena-v0.1.3
"""
