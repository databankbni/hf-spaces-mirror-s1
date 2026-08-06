# Diamond Analytics Predictor — Specification

> Spec-Driven Development following [github/spec-kit](https://github.com/github/spec-kit/blob/main/spec-driven.md).  
> The specification is the primary artifact. Code is its expression.

---

## Constitution

These principles are immutable. Every implementation plan must pass all Phase -1 gates before any code is written.

| Article | Principle |
|---------|-----------|
| I | Every domain component is an independent Python submodule with no circular imports. |
| II | Every submodule exposes a CLI entry point (`python -m thebeast.<module>`) for observability and manual debugging. |
| III | **Test-first**: no implementation file is created until at least one failing integration test exists for it. |
| IV | Integration tests use real data fixtures (2021–2024 Statcast snapshots checked into the repo). Mock only external HTTP calls. |
| V | Storage is accessed through a `Repository` interface. SQLite is the default implementation; alternate backends are plugged in without changing callers. |
| VI | Open uncertainties (marked `?`) must be resolved and removed before the feature they belong to is implemented. |

---

## Design Lineage

This project is the MLB successor to **mrsim** (`~/src/mrsim`), a working NFL simulator. The architecture is a direct port of mrsim's proven patterns to baseball semantics. Where mrsim has an established solution, we adopt it; where baseball differs fundamentally from NFL, we document the delta.

| mrsim concept | thebeast analog | Notes |
|---------------|-----------------|-------|
| `TeamDNA` | `BatterDNA`, `PitcherDNA` | Same "statistical fingerprint" pattern; baseball splits the profile by player rather than team |
| `GameState` | `InningState` | 24 base-out states replace mrsim's down/distance/clock |
| `PlayOutcome` | `PAOutcome` | Discrete outcome enum (1B/2B/3B/HR/BB/HBP/K/IPO) replaces play-type + yards |
| `PipelineKnobs` | `SimulationKnobs` | Same dataclass-of-dataclasses pattern; all tunable constants in one place |
| `GameContext` | `GameContext` | Identical concept; weather, park, pitcher for the game vs. wind, roof, rest |
| `MonteCarloRaw` / `MonteCarloResult` | `GameSimulationRaw` / `GameSimulationResult` | Same raw-vs-aggregated split; raw carries numpy arrays for histograms |
| `run_games` + `aggregate` | `run_innings` + `aggregate` | Same two-step pipeline: loop then summarize |
| `synthetic_team` | `synthetic_batter`, `synthetic_pitcher` | League-average synthetic profiles for tests that don't touch the network |
| `BacktestKnobs` + `run_backtest` | `BacktestKnobs` + `run_backtest` | Walk-forward backtest with exponential decay of prior-season data; Vegas comparison baked in |
| `prior_weight(week, halflife)` | `prior_weight(date, halflife_days)` | Same exponential decay function; baseball uses calendar days instead of weeks |
| `sample_drive_form` (Cholesky) | `sample_batting_form` (Cholesky) | Per-inning correlated form multiplier for batting-order correlation |
| Representative-game replay | Same | After batch, replay the game closest to mean outcome with logging on |

---

## Feature Catalog

| ID | Feature | Status | Module |
|----|---------|--------|--------|
| F-001 | Data Ingestion | `draft` | `thebeast.data` |
| F-002 | Game State Simulator | `draft` | `thebeast.simulator` |
| F-003 | Matchup Model | `draft` | `thebeast.matchup` |
| F-004 | Betting Analysis | `draft` | `thebeast.betting` |
| F-005 | CLI Interface | `draft` | `thebeast.cli` |
| F-006 | REST API | `draft` | `thebeast.api` |

**Build order (constitutionally enforced):** F-001 → F-002 → F-003 → F-004 → F-005 → F-006

---

## User Stories

```
US-001  As a quantitative analyst, I want to run a full game simulation from the CLI
        so that I can get win probabilities and run distributions before game time.

US-002  As a data scientist, I want to import thebeast as a Python library
        so that I can call simulation functions inside Jupyter notebooks.

US-003  As a web application, I want to hit a REST endpoint with a game ID
        so that I receive a JSON payload with simulation results and Kelly bet sizes.

US-004  As an analyst, I want the system to automatically fetch confirmed lineups
        so that late roster changes are reflected without manual intervention.

US-005  As an analyst, I want simulation predictions calibrated against the 2024
        Vegas closing line so that I can trust the probabilities are meaningful.
```

---

## System Architecture

### Package Structure

```
thebeast/                  # single pip-installable package
├── data/                  # F-001 — ingestion, storage, caching
│   ├── __main__.py        # CLI entry: python -m thebeast.data
│   ├── repository.py      # Repository interface + SQLite impl
│   ├── sources/
│   │   ├── statcast.py    # pybaseball wrapper
│   │   ├── schedules.py   # MLB schedule + lineup fetcher
│   │   └── projections.py # Steamer/ZiPS fetcher
│   └── models.py          # Data transfer objects (LineupCard, GameSchedule, etc.)
├── simulator/             # F-002 — Markov game engine (mirrors mrsim structure)
│   ├── __main__.py
│   ├── state.py           # InningState (← mrsim state.py)
│   ├── outcome.py         # PAOutcome, sample_batting_form (← mrsim outcome.py)
│   ├── engine.py          # simulate_game (← mrsim simulator.py)
│   ├── aggregate.py       # run_games, aggregate, GameSimulationRaw/Result (← mrsim aggregate.py)
│   ├── backtest.py        # run_backtest, BacktestKnobs, BacktestResult (← mrsim backtest.py)
│   ├── advancement.py     # RunnerAdvancementMatrix from Retrosheet
│   └── config.py          # SimulationKnobs, BacktestKnobs (← mrsim config.py)
├── matchup/               # F-003 — Bayesian Log5 model + DNA fingerprints
│   ├── __main__.py
│   ├── dna.py             # BatterDNA, PitcherDNA, LeagueAverages, build_*_dna (← mrsim team.py)
│   ├── log5.py            # PAOutcomeDistribution, pa_distribution() (← mrsim outcome.py)
│   ├── context.py         # GameContext, adjust_dna (← mrsim context.py)
│   └── calibration.py     # isotonic regression (← mrsim backtest brier logic)
├── betting/               # F-004 — edge detection + Kelly
│   ├── __main__.py
│   ├── edge.py
│   ├── kelly.py
│   └── models.py
├── cli/                   # F-005 — Click command group (← mrsim cli.py)
│   └── main.py
└── api/                   # F-006 — FastAPI server (← mrsim api/)
    ├── main.py
    ├── schemas.py
    └── cache.py
```

### Data Flow

```
[External sources]
  Statcast / pybaseball ──┐
  MLB schedule API ───────┤──▶ thebeast.data ──▶ SQLite (Repository)
  FanGraphs/Steamer/ZiPS ─┘                              │
                                                          ▼
                                              thebeast.matchup
                                         (PAOutcomeDistribution per batter-pitcher)
                                                          │
                                                          ▼
                                              thebeast.simulator
                                         (GameSimulationResult: run dist, win prob)
                                                          │
                                                          ▼
                                              thebeast.betting
                                         (BettingEdge: kelly size, edge %)
                                                          │
                                              ┌───────────┴───────────┐
                                              ▼                       ▼
                                         thebeast.cli           thebeast.api
```

### Deployment

- Docker image. Single `Dockerfile` at repo root.
- Data volume mounted at `/data/thebeast.db`.
- Environment variables: `THEBEAST_DB_PATH`, `THEBEAST_LOG_LEVEL`.

---

## Feature Specifications

---

### F-001 — Data Ingestion (`thebeast.data`)

**Summary:** Fetches and persists game schedules, confirmed lineups, Statcast batter/pitcher statlines, and projection-system baselines. Exposes a `Repository` interface so the rest of the system never touches the database directly.

**Inputs (external):**
- `pybaseball.statcast()` — Statcast pitch-level data
- MLB Stats API — daily schedules and lineup confirmations
- Steamer/ZiPS projection CSVs — pre-season true-talent estimates

**Outputs (public interface):**

```python
@dataclass
class BatterStatline:
    player_id: int
    season: int
    pa: int
    bb_pct: float       # walk rate
    k_pct: float        # strikeout rate
    woba: float
    xwoba: float        # expected wOBA (Statcast)
    iso: float          # isolated power
    babip: float
    platoon_split: dict[str, float]  # keyed by "vL" / "vR"

@dataclass
class PitcherStatline:
    player_id: int
    season: int
    role: Literal["starter", "reliever"]
    bb_pct: float
    k_pct: float
    hr_per_9: float
    xfip: float
    platoon_split: dict[str, float]

@dataclass
class LineupCard:
    game_id: str
    team_id: str
    batting_order: list[int]   # player_ids, positions 1-9
    starter_id: int
    bullpen_ids: list[int]
    confirmed: bool
    confirmed_at: datetime | None

@dataclass
class GameSchedule:
    game_id: str
    date: date
    home_team_id: str
    away_team_id: str
    venue_id: str
    first_pitch: datetime

@dataclass
class ParkFactor:
    venue_id: str
    season: int
    # ? — method for deriving these values is an open uncertainty (see U-004)
    runs_factor: float
    hr_factor: float
    hits_factor: float

@dataclass
class WeatherConditions:
    game_id: str
    temperature_f: float
    wind_mph: float
    wind_direction_deg: float
    humidity_pct: float
```

**Repository interface:**

```python
class GameRepository(Protocol):
    def save_batter(self, b: BatterStatline) -> None: ...
    def get_batter(self, player_id: int, season: int) -> BatterStatline | None: ...
    def save_pitcher(self, p: PitcherStatline) -> None: ...
    def get_pitcher(self, player_id: int, season: int) -> PitcherStatline | None: ...
    def save_lineup(self, l: LineupCard) -> None: ...
    def get_lineup(self, game_id: str, team_id: str) -> LineupCard | None: ...
    def save_schedule(self, s: GameSchedule) -> None: ...
    def get_schedule(self, date: date) -> list[GameSchedule]: ...
```

**Acceptance criteria:**
- [ ] `python -m thebeast.data fetch --date 2024-04-01` completes without error and writes records to SQLite.
- [ ] Re-running the same fetch command is idempotent (no duplicate rows).
- [ ] `get_lineup` returns `None` before lineup confirmation and the confirmed card after.
- [ ] Statcast data for 2021–2024 seasons can be fetched and stored in under 10 minutes on first run.
- [ ] All public dataclasses are fully typed and pass `mypy --strict`.

**Open uncertainties:**
- `U-004`: Park factor computation method — see Open Uncertainties Register.

---

### F-002 — Game State Simulator (`thebeast.simulator`)

**Summary:** Runs a 24-state Markov Monte Carlo simulation of a 9-inning MLB game. Directly mirrors mrsim's architecture: `InningState` ↔ `GameState`, `PAOutcome` ↔ `PlayOutcome`, `simulate_game` ↔ `simulate_game`, `run_games` + `aggregate` ↔ same.

**`InningState` (analogous to mrsim `GameState`):**

```python
# runners_bitmap: bits 0/1/2 = 1B/2B/3B occupied
# outs: 0, 1, 2 (inning ends at 3)
# inning: 1-9; half: "top" | "bottom"
# 24 distinct states = (runners_bitmap 0-7) × (outs 0-2)

@dataclass
class InningState:
    home: str
    away: str
    possession: str            # team currently batting
    inning: int = 1
    half: Literal["top", "bottom"] = "top"
    outs: int = 0
    runners_bitmap: int = 0    # bit 0=1B, bit 1=2B, bit 2=3B
    score: dict[str, int] = field(default_factory=dict)
    batting_position: dict[str, int] = field(default_factory=dict)  # per team, 0-8
    game_over: bool = False

    @property
    def defense(self) -> str: ...
    def advance_runners(self, outcome: PAOutcomeEnum,
                        matrix: RunnerAdvancementMatrix) -> int: ...
    def record_out(self) -> None: ...
    def next_half_inning(self) -> None: ...
```

**`PAOutcome` (analogous to mrsim `PlayOutcome`):**

```python
@dataclass
class PAOutcome:
    outcome: PAOutcomeEnum     # 1B | 2B | 3B | HR | BB | HBP | K | IPO
    runs_scored: int = 0
    # Structured attribution (mirrors mrsim's passer/rusher/receiver flags)
    batter_id: int = 0
    pitcher_id: int = 0
    # For play-log replay (like mrsim's `representative` game)
    label: str = ""

PAOutcomeEnum = Literal["1B", "2B", "3B", "HR", "BB", "HBP", "K", "IPO"]
```

**`simulate_game` (same signature convention as mrsim):**

```python
def simulate_game(
    home_lineup: LineupCard,
    away_lineup: LineupCard,
    pa_distributions: dict[tuple[int, int], PAOutcomeDistribution],
    advancement: RunnerAdvancementMatrix,
    rng: np.random.Generator | None = None,
    knobs: SimulationKnobs | None = None,
    log: bool = False,        # same log flag as mrsim — enables play-by-play
) -> GameResult: ...
```

**`sample_batting_form` (analogous to mrsim `sample_drive_form`):**

```python
# Per-inning correlated form multiplier for batting order correlation.
# Cholesky 2x2: if leadoff batter has a hot inning, subsequent batters
# see a correlated HR-probability lift. ρ default from SimulationKnobs.
_L = np.array([[1.0, 0.0], [rho, np.sqrt(1 - rho**2)]])

def sample_batting_form(rng: np.random.Generator,
                        rho: float = 0.30) -> tuple[float, float]:
    """Return (contact_form, power_form) multipliers, correlated via Cholesky."""
```

**`run_games` + `aggregate` (identical separation as mrsim):**

```python
@dataclass
class GameSimulationRaw:
    """Raw per-game arrays (analogous to mrsim MonteCarloRaw)."""
    home_runs: np.ndarray      # int32[n]
    away_runs: np.ndarray      # int32[n]
    totals: np.ndarray         # int32[n]
    extra_inning_flags: np.ndarray  # bool[n]
    sample: list[GameResult]   # first few for inspection
    home_players: list[dict]   # projected per-game stat lines (mean over trials)
    away_players: list[dict]
    representative: GameResult | None  # replay of closest-to-mean game with log=True

@dataclass
class GameSimulationResult:
    """Aggregated result (analogous to mrsim MonteCarloResult)."""
    game_id: str
    home: str
    away: str
    n: int
    home_win_probability: float
    home_run_mean: float
    home_run_median: float
    home_run_p10: float
    home_run_p90: float
    away_run_mean: float
    away_run_median: float
    away_run_p10: float
    away_run_p90: float
    total_mean: float
    total_median: float
    total_p10: float
    total_p90: float
    extra_inning_pct: float
    spread_mean: float    # home - away
    player_lines: list[dict]

def run_games(home_lineup, away_lineup, pa_distributions, advancement,
              n: int, seed: int | None = None,
              representative: bool = False,
              knobs: SimulationKnobs | None = None) -> GameSimulationRaw: ...

def aggregate(game_id: str, home: str, away: str,
              raw: GameSimulationRaw) -> GameSimulationResult: ...
```

**`BacktestKnobs` + `run_backtest` (walk-forward, identical to mrsim pattern):**

```python
@dataclass
class BacktestKnobs:
    train_seasons: list[int] = field(default_factory=lambda: [2021, 2022, 2023])
    holdout_season: int = 2024
    n_sims: int = 200                  # fewer per game than live (speed)
    decay_halflife_days: float = 42.0  # prior-season weight decay (6 weeks analog)
    pipeline: SimulationKnobs = field(default_factory=SimulationKnobs)

def prior_weight(days_into_season: int, halflife_days: float) -> float:
    """Exponential decay of prior-season plays. Same formula as mrsim."""
    return float(0.5 ** (days_into_season / halflife_days))

def run_backtest(knobs: BacktestKnobs | None = None, ...) -> BacktestResult: ...

@dataclass
class BacktestResult:
    """Mirrors mrsim BacktestResult; adds Vegas log-loss comparison."""
    n_games: int
    brier: float
    model_log_loss: float
    vegas_log_loss: float          # primary MVP gate: model < vegas
    beats_vegas: bool              # model_log_loss < vegas_log_loss
    calibration_max_decile_err: float
    games: list[GameRow]
    elapsed_seconds: float
```

**Simulation invariants:**
- States: `(runners_bitmap, outs)` — 8 × 3 = 24 states.
- Each half-inning starts at `(0b000, 0)`; ends when `outs == 3`.
- Game is 9 innings; extra innings not in scope for MVP (flag as `extra_inning_flags`).
- Pitching changes: simple heuristic for MVP — starter through fixed innings, single aggregate reliever profile (U-005).
- Cholesky correlation: per-inning `sample_batting_form` multiplier; ρ from `SimulationKnobs.cholesky_rho` (U-006 resolved to this heuristic for MVP).

**Acceptance criteria:**
- [ ] `python -m thebeast.simulator run --game-id <id> --iterations 5000` outputs `GameSimulationResult` JSON in under 60 s on a 2-core machine.
- [ ] Symmetric test: 10,000 simulated games with two identical `synthetic_batter` lineups → home win probability `50% ± 0.5%`.
- [ ] Run distribution for league-average lineups passes KS test against Poisson(4.5) null at α=0.05.
- [ ] `n_iterations=1` produces a valid deterministic game trace.
- [ ] Backtest on 2024 holdout: `model_log_loss < vegas_log_loss` (primary MVP gate).

**Open uncertainties:**
- `U-002`: Runner advancement matrix dimensions and source — see Open Uncertainties Register.
- `U-005`: Starter pitch-count/inning threshold for bullpen transition.
- `U-006`: Resolved to per-inning Cholesky heuristic (ρ=0.30) for MVP; tune post-MVP.

---

### F-003 — Matchup Model (`thebeast.matchup`)

**Summary:** Builds compact statistical fingerprints (`BatterDNA`, `PitcherDNA`) from Statcast data — the baseball analog of mrsim's `TeamDNA` — then combines them via the Bayesian Hierarchical Log5 model to produce a `PAOutcomeDistribution` for any batter-pitcher pair. Also owns calibration (isotonic regression).

**Core fingerprint types (analogous to mrsim `TeamDNA`):**

```python
@dataclass
class BatterDNA:
    """Statistical fingerprint built from Statcast PA-level data.

    Rates are shrunk toward league average when PA count is low.
    Separate vL/vR rates are stored as {Handedness: float} dicts.
    """
    player_id: int
    season: int
    pa: int                    # sample size (used for shrinkage weight)
    # Eight outcome rates (sum to ~1.0 before shrinkage)
    single_rate: float
    double_rate: float
    triple_rate: float
    hr_rate: float
    bb_rate: float
    hbp_rate: float
    k_rate: float
    ipo_rate: float
    # Platoon splits stored as multipliers relative to batter's overall rate.
    # apply: rate_vL = rate_overall × platoon_mult["vL"]
    platoon_mult: dict[str, float]   # keys: "vL", "vR"
    # Derived (from Statcast, not Log5): for quality calibration only.
    xwoba: float
    exit_velo_mean: float

@dataclass
class PitcherDNA:
    """Statistical fingerprint for a pitcher (starter or reliever)."""
    player_id: int
    season: int
    bf: int                    # batters faced (sample size for shrinkage)
    role: Literal["starter", "reliever"]
    # Eight allowed-outcome rates
    single_allowed: float
    double_allowed: float
    triple_allowed: float
    hr_allowed: float
    bb_allowed: float
    hbp_allowed: float
    k_rate: float
    ipo_rate: float
    platoon_mult: dict[str, float]
    xfip: float

@dataclass
class LeagueAverages:
    """League-average outcome rates for the Log5 denominator.
    
    Rebuilt from training data each season; stored in the Repository.
    """
    season: int
    single_rate: float
    double_rate: float
    triple_rate: float
    hr_rate: float
    bb_rate: float
    hbp_rate: float
    k_rate: float
    ipo_rate: float
```

**Builder functions (analogous to mrsim `build_team_dna`):**

```python
def build_batter_dna(player_id: int, season: int, statcast: pd.DataFrame,
                     league: LeagueAverages, shrink_pa: int = 200) -> BatterDNA: ...

def build_pitcher_dna(player_id: int, season: int, statcast: pd.DataFrame,
                      league: LeagueAverages, shrink_bf: int = 300) -> PitcherDNA: ...

def synthetic_batter(hand: str = "R") -> BatterDNA: ...   # league-average, for tests
def synthetic_pitcher(role: str = "starter") -> PitcherDNA: ...
```

**`GameContext` (identical to mrsim pattern):**

```python
@dataclass
class GameContext:
    """Per-game context applied to DNA before simulation."""
    game_id: str
    venue_id: str
    temperature_f: float | None = None
    wind_mph: float | None = None
    wind_direction_deg: float | None = None
    roof: Literal["dome", "open", "outdoors"] | None = None
    # Filled from Park Factor lookup
    hr_factor: float = 1.0
    runs_factor: float = 1.0
```

**Matchup output:**

```python
@dataclass
class PAOutcomeDistribution:
    batter_id: int
    pitcher_id: int
    # probabilities must sum to 1.0
    single: float
    double: float
    triple: float
    home_run: float
    walk: float
    hit_by_pitch: float
    strikeout: float
    in_play_out: float
```

**Model specification (Log5, same structure as mrsim's multiplicative rate blending):**

For outcome class `o`, apply platoon adjustment first, then combine:

```
b_adj_o = b_o × platoon_mult[pitcher_hand]
p_adj_o = p_o × platoon_mult[batter_hand]

raw_o = (b_adj_o × p_adj_o / L_o)
P(o) = raw_o / Σ_k raw_k
```

Park + weather: `P(hr) *= context.hr_factor`, then renormalize.

Shrinkage: `b_o_shrunk = (b_o × PA + L_o × shrink_pa) / (PA + shrink_pa)`.

**Calibration:**
Fit isotonic regression on 2021–2023 Statcast win probabilities vs outcomes. Serialized and stored in the Repository; loaded at inference time.

**`SimulationKnobs` (analogous to mrsim `PipelineKnobs`):**

```python
@dataclass
class WindKnobs:
    threshold_mph: float = 8.0
    cap_mph: float = 20.0
    hr_penalty: float = 0.12    # fraction lost at cap wind (headwind)
    hr_bonus: float = 0.10      # fraction gained (tailwind)

@dataclass
class SimulationKnobs:
    n_iterations: int = 5000
    home_field_advantage: float = 1.02   # small HR boost for home team
    use_context: bool = True             # apply park + weather adjustments
    use_platoon: bool = True             # apply platoon splits
    use_cholesky: bool = True            # apply batting-order correlation
    cholesky_rho: float = 0.30          # pass-rush correlation analog
    wind: WindKnobs = field(default_factory=WindKnobs)
    shrink_pa: int = 200
    shrink_bf: int = 300

    def as_dict(self) -> dict: ...
```

**Acceptance criteria:**
- [ ] `PAOutcomeDistribution` probabilities sum to `1.0 ± 1e-6` for all inputs.
- [ ] Model passes chi-squared goodness-of-fit test against 2021–2023 Statcast PA outcomes at α=0.05.
- [ ] Calibration curve on 2024 holdout: each decile's actual win rate within ±2%.
- [ ] `synthetic_batter()` and `synthetic_pitcher()` produce valid distributions without any database access.
- [ ] `python -m thebeast.matchup predict --batter <id> --pitcher <id>` returns a JSON distribution.

**Open uncertainties:**
- `U-001`: Log5 shrinkage weights — see Open Uncertainties Register.
- `U-003`: ABS strike zone impact — see Open Uncertainties Register.
- `U-004`: Park factor computation method — see Open Uncertainties Register.

---

### F-004 — Betting Analysis (`thebeast.betting`)

**Summary:** Compares simulated win probabilities to sportsbook market odds, identifies edges, and recommends Quarter-Kelly or Half-Kelly wager sizes. Owns calibration validation against the closing line.

**Inputs:**
- `GameSimulationResult` (from F-002)
- Market odds as American moneyline integers (e.g., `-150`, `+130`)
- `kelly_fraction: float` — `0.25` (Quarter-Kelly) or `0.5` (Half-Kelly)

**Outputs:**

```python
@dataclass
class MarketOdds:
    game_id: str
    home_ml: int   # American moneyline
    away_ml: int
    total_line: float   # over/under total
    over_ml: int
    under_ml: int

@dataclass
class BettingEdge:
    game_id: str
    market: Literal["home_ml", "away_ml", "over", "under"]
    model_probability: float
    implied_probability: float  # derived from market odds
    edge: float                 # model_prob - implied_prob
    kelly_fraction: float
    recommended_stake_pct: float   # as fraction of bankroll
    expected_value: float
    confidence_interval_95: tuple[float, float]
```

**Edge calculation:**

```
implied_prob = 1 / (1 + abs(ml)/100)   if ml > 0
implied_prob = abs(ml) / (abs(ml)+100) if ml < 0

kelly_stake = kelly_fraction × (edge / (1 - implied_prob))
```

**Acceptance criteria:**
- [ ] On 2024 holdout data, model log-loss is lower than sportsbook closing-line implied-probability log-loss (primary MVP acceptance criterion).
- [ ] `recommended_stake_pct` is `0.0` when `edge ≤ 0`.
- [ ] `recommended_stake_pct` never exceeds `kelly_fraction` (hard cap on overbetting).
- [ ] `python -m thebeast.betting analyze --game-id <id> --home-ml -150 --away-ml +130` outputs `BettingEdge` JSON.
- [ ] Bankroll management: betting according to recommended stakes on 2024 holdout produces positive ROI in backtesting.

---

### F-005 — CLI Interface (`thebeast.cli`)

**Summary:** A Click-based command group that exposes the full pipeline end-to-end. Targets interactive use by analysts on the command line.

**Commands:**

```
thebeast fetch --date YYYY-MM-DD            # F-001: fetch + store data
thebeast simulate --game-id ID [--n INT]    # F-002+F-003: run simulation
thebeast bet --game-id ID [--kelly FLOAT]   # F-004: edge + stake sizing
thebeast run --date YYYY-MM-DD              # full pipeline for all games on date
```

**Acceptance criteria:**
- [ ] All commands print structured JSON with `--json` flag and human-readable tables by default.
- [ ] `--help` documents all flags.
- [ ] Non-zero exit code on any runtime error; error message to stderr, not stdout.
- [ ] `thebeast run --date 2024-04-01` completes for all games on that date.

---

### F-006 — REST API (`thebeast.api`)

**Summary:** FastAPI server exposing F-001 through F-004 via HTTP. Intended for web frontend consumption.

**Endpoints:**

```
GET  /health
GET  /games?date=YYYY-MM-DD              → list[GameSchedule]
POST /simulate   body: {game_id, n}     → GameSimulationResult
POST /bet        body: {game_id, odds}  → list[BettingEdge]
GET  /lineups?game_id=ID                → {home: LineupCard, away: LineupCard}
```

**Acceptance criteria:**
- [ ] All endpoints return `application/json`.
- [ ] `/simulate` responds in under 90 seconds for 5,000 iterations.
- [ ] OpenAPI schema auto-generated at `/docs`.
- [ ] Returns HTTP 422 with field-level validation errors on malformed input.

---

## MVP Acceptance Criterion

> **Definition of Done for MVP (F-001 through F-004):**
> On the 2024 regular season holdout, the model's win probability log-loss is strictly lower than the log-loss of the Vegas closing-line implied probabilities for the same games.

Secondary gate: calibration curve within ±2% across deciles (required before F-004 is implemented).

---

## Testing Strategy

**Fixtures:** Statcast sample data for 2021–2024 (≥ 10,000 PAs per season) checked into `tests/fixtures/`. Fetched once via `make fixtures`.

**Test layers:**

| Layer | Scope | Tooling |
|-------|-------|---------|
| Unit | Pure functions: Log5 math, Kelly formula, state transitions | `pytest` |
| Integration | Each module end-to-end with real fixture data | `pytest` |
| Backtest | Model accuracy on 2021–2023 train / 2024 holdout | `pytest` + custom reporter |
| CLI smoke | All CLI commands run without error | `pytest` + `click.testing.CliRunner` |
| API contract | All endpoints return correct schemas | `pytest` + `httpx` |

**Constitutional gate:** `pytest` must pass before any PR is merged. No `unittest.mock.patch` of internal functions — only of `requests` / `httpx` HTTP calls.

---

## Open Uncertainties Register

> All `?` items must be resolved (moved to a decision, with rationale) before implementation of the feature that depends on them begins.

| ID | Uncertainty | Blocking | Research action |
|----|------------|---------|-----------------|
| U-001 | **Log5 shrinkage weights**: What PA sample size threshold triggers shrinkage toward league average? What prior variance is used? Does the model use a hierarchical Dirichlet-Multinomial? | F-003 | Research agent: review Tango's original Log5 derivation and FanGraphs' wOBA weights; propose specific priors. |
| U-002 | **Runner advancement matrices**: Exact dimensions (base state × outcome class), number of historical seasons (2015–2024? 2021–2024?), whether to include platoon splits or handedness. | F-002 | Pull Retrosheet event files for 2021–2024; compute empirical transition frequencies; document matrix shape. |
| U-003 | **ABS strike zone model**: The Automated Ball-Strike system changes BB% and K% distributions. No data source or adjustment model is specified. Is this in-scope for MVP? | F-003 | Decision needed: either descope ABS for MVP (mark as post-MVP) or identify a data source (e.g., Baseball Savant ABS zone data). |
| U-004 | **Park factor computation**: FanGraphs lookup vs. multi-year regression from Retrosheet? How many seasons? How to handle new stadiums? | F-001, F-003 | Research agent: compare FanGraphs park factor methodology with 3-year regression approach; document chosen method. |
| U-005 | **Pitcher transition model**: When does the starter leave? Is it a pitch-count threshold, a per-PA out-rate model, or a fixed inning count? How are relievers sequenced from the bullpen? | F-002 | Descope to a simple heuristic for MVP (e.g., starter through 5–6 innings, then single aggregate reliever) and document this as a known simplification. |
| U-006 | ~~**Cholesky correlation matrix**~~ | F-002 | **Resolved**: Use per-inning 2×2 Cholesky form multiplier (ρ=0.30, same as mrsim's `sample_drive_form`) applied as `(contact_form, power_form)` scalars. Full per-position correlation matrix is post-MVP. |

---

## Data Sources

| Source | Data | Access method | Cadence |
|--------|------|---------------|---------|
| Statcast / Baseball Savant | Pitch-level batter/pitcher metrics | `pybaseball.statcast()` | Season bulk + daily |
| MLB Stats API | Schedules, confirmed lineups | REST API (unauthenticated) | Daily (3 hours pre-game) |
| Retrosheet | Play-by-play, runner advancement | Bulk event file download | Annual (historical only) |
| FanGraphs / Steamer / ZiPS | Pre-season projections | CSV download | Pre-season + weekly |

---

## Phasing

| Phase | Features | Exit criterion |
|-------|---------|---------------|
| 0 — Foundation | F-001 (data ingestion + SQLite) | All F-001 acceptance criteria pass; 2021–2024 data loadable. |
| 1 — Simulation | F-002 (simulator with stub matchup) | Simulator runs 5,000 iterations in < 60 s; convergence test passes. |
| 2 — Accuracy | F-003 (matchup model + calibration) | Calibration ±2% on 2024 holdout; chi-squared test passes. |
| 3 — MVP | F-004 (betting engine) | Log-loss beats Vegas closing line on 2024 holdout. |
| 4 — Interface | F-005 (CLI), F-006 (API) | All CLI/API acceptance criteria pass. |
