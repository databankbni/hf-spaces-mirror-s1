# The Beast — agent guide

MLB Monte Carlo simulator with a live web UI. Python (FastAPI) backend,
SvelteKit 5 frontend compiled into a static bundle the API serves itself,
deployed as a Docker image to a Hugging Face Space.

Read this before changing anything. The **Invariants** section is the part that
will cost you if you skip it — most of those rules exist because breaking them
produced a bug that looked like working software.

---

## Commands

Everything below was run and verified in this repo.

```bash
# Setup
pip install -e ".[api,dev]"          # runtime + FastAPI + pytest
cd web && npm install && cd ..       # frontend

# Test — 703 tests, about two minutes
python -m pytest -q
python -m pytest tests/test_pitch_sequence.py -q      # one file
python -m pytest -q -k NextAtBat                      # one class

# Frontend gates — both must be clean before you commit
npm --prefix web run check           # svelte-check: 0 errors, 0 warnings
npm --prefix web run build           # static bundle into web/build

# Run the whole app on one port
npm --prefix web run build
THEBEAST_DB_PATH=data/thebeast.db uvicorn thebeast.api.main:app --port 8080

# Frontend development, with hot reload
uvicorn thebeast.api.main:app --port 8000    # terminal 1
npm --prefix web run dev                     # terminal 2, proxies /api → :8000
```

`mypy` is configured in `pyproject.toml` under `[tool.mypy]` with `strict`, but
it is not installed here and the codebase has never been checked against it.
Treat it as aspirational, not a gate — do not claim a change is mypy-clean
without running it.

---

## Repo map

```
thebeast/
  api/main.py          ~1900 lines. Every HTTP endpoint. The biggest file.
  simulator/           The Monte Carlo engine: state, outcomes, aggregation.
  matchup/             Log5 batter-vs-pitcher model + park/weather context.
  pipeline.py          Wires repo → DNA → simulation. `_game_context` lives here.
  simcache.py          Shared cache so one slate is simulated once, not per page.
  slate.py             Background warm-up: simulating a whole day's games.
  betting/
    best_bets.py       Ranked plays. Simulates first, prices second.
    board.py           A *view* over best_bets — not a second pricing.
  data/
    sources/           One module per external feed.
    repository.py      SQLite. Statlines, schedules, lineups, park factors.
    ingest.py          Statcast → statlines. Has a min-PA floor; see Gotchas.
  pitch_sequence.py    Count-state Markov chain: how long an at-bat runs.
  next_at_bat.py       Joins live feed + profiles + Log5 for the live panel.
  accuracy.py          Grades finished games against what was predicted.
web/src/
  lib/api.ts           Typed client. Mirrors the API's shapes.
  routes/matchups/     The slate page and the per-game page (3,600 lines).
tests/                 703 tests. Named as claims, not as function names.
```

---

## Invariants

These are load-bearing. Each one is here because violating it produced
something that looked right and wasn't.

**Simulate first, price second.** `build_best_bets` simulates every game before
it looks at a single price. The ranking must never depend on which feed
answered first, and the run backing a listed bet must be the identical cached
run behind that game's matchup card — not a second opinion of it.

**One prop source, never a mix.** PrizePicks is the only prop feed. There is
deliberately no fallback to another book: a board that silently switched
sources would show lines whose provenance depended on which endpoint answered.

**PrizePicks posts no odds.** It is DFS pick'em — the payout is on the slip, not
the pick. Every "needs X%" on the board is a break-even *we chose* (57.7%, from
a 2-pick power play at 3x), not a quoted price. That assumption is stated on
the board, in the API payload (`pricing_note`), and in the chat tool's reply.
If you touch it, it stays stated.

**The pitch model is fitted to Log5, not independent of it.** `pitch_sequence`
solves two parameters until its strikeout and walk rates reproduce what the
Log5 matchup model already says. 95.5% of real matchups fit exactly; the rest
are flagged `fit_capped`. A pitch panel that disagreed with the matchup card
beside it would put two contradictory claims on one screen.

**Never report 0% or 100% from a Monte Carlo.** Probabilities are
Laplace-smoothed, `(k+1)/(n+2)`. 2,000 sims with no failures does not mean
certainty, and un-smoothed p=1 makes Kelly stake pin to the cap on a hopeless
price.

**Count what you drop, by reason.** Every filter that discards a prop, a
player or a market increments a named counter that reaches the UI. This exists
because "the app shows this player and you don't" was once unanswerable without
reading the parser — it cost about a week and three wrong explanations.

**Label anything that isn't measured.** League-average stand-ins, derived
break-evens, assumed profiles: all of them ship with a field saying so
(`batter_profile`, `arsenal_source`, `pricing_note`) *and* visible text. A
default that looks identical to real data is the failure mode to avoid.

---

## Environment realities

**No outbound network in the dev sandbox.** An egress proxy refuses everything
except a small allowlist. `statsapi.mlb.com`, `api.prizepicks.com` and
`baseballsavant.com` are all blocked here and all work in production. Practical
consequences:

- You cannot verify any external parser locally. Write it defensively and add
  a probe endpoint (`/api/props-probe`, `/api/nfl/props/probe`) that reports
  what actually arrived, then check it against the deployed app.
- **Tests must never hit the network.** Injecting `None` for an optional live
  argument sometimes means "go fetch it" — `next_at_bat.build` takes a
  `_FETCH` sentinel precisely so `boxscore=None` means "there isn't one". A
  test suite that reaches out is slow and flaky; this was a real bug.

**The bundled database is a stale snapshot.** `data/thebeast.db` holds 2026
statlines ingested around early July: the PA leader sits on 400 against the
~520 an August regular would have. Combined with the ingest's minimum-PA floor
(stored data bottoms out at 30 PA), **about 21% of lineup slots belong to a
hitter with no profile** — measured at 482 of 2,304 over a fortnight. Those now
fall back to a labelled league profile rather than an empty panel. Re-ingesting
raises the ceiling but never eliminates it: a debutant has no record to ingest.

The committed schedule ends 2026-07-01. Production fetches schedules and
lineups live from MLB, so it is current; only the statlines are frozen.

**Running the tests dirties `data/thebeast.db`, harmlessly.** Several tests
construct `SQLiteRepository()` with no path, and `_default_db_path()` falls back
to `./data/thebeast.db` when it exists — so the suite opens the committed
database and SQLite rewrites pages even where nothing is inserted. Verified:
`accuracy_games` holds 486 rows before a full run and 486 after, but the file's
checksum changes. Expect `git status` to show the database modified after every
test run; that diff is noise and can be discarded with
`git checkout -- data/thebeast.db`.

What is *not* noise is a change in row counts. The daily grading job writes real
scored games into the same table, and those are worth committing. Check before
discarding:

```bash
python -c "import sqlite3;print(sqlite3.connect('data/thebeast.db').execute(
  'SELECT COUNT(*) FROM accuracy_games').fetchone()[0])"
```

---

## Known unverified, and open threads

Stated plainly so you don't rediscover them or, worse, assume they're settled.

**The PrizePicks parser has never seen a real response.** Every field name in
`data/sources/prizepicks.py` and `prizepicks_nfl.py` comes from other people's
open-source readers of that endpoint, not from a response anyone here has
observed — the sandbox can't reach it. The probe endpoints exist to settle it
from production in one request. If the board is empty, check
`/api/props-probe` before touching the parser: it reports the market
vocabulary the feed actually carries, which is the thing most likely to differ.

**PrizePicks is an undocumented app endpoint, not a product.** No key, no
login, no version, no promises, and plausibly against their terms. It can stop
working without notice. `SharpAPI-brief.pdf` in the repo root evaluates
SharpAPI as a replacement — a real product with a free tier and actual
sportsbook prices, which would remove the invented break-even entirely.

**League ids are asked for, not assumed.** `MLB_LEAGUE_ID = 2` is a fallback;
the source queries `/leagues` by name first, because a stale id returns an
empty page that looks exactly like an empty slate.

**Statlines want re-ingesting.** See Environment realities. The ingest needs
Statcast network access, so it has to run somewhere with egress — not here.
Lowering `min_pa` would pull in more players at the cost of profiles built on
almost no sample, which has its own failure mode.

**Two removed features are one revert away.** The slate page had Trends, Model
accuracy, The week ahead, a ranked Best bets panel and a chat assistant. The UI
was removed on request (`cfce8e9`, `c41cd2f`); every backend endpoint,
module and test behind them still works, so rebuilding is re-adding markup
rather than reconstructing analysis.

---

## Deploy

Push to `main`. `.github/workflows/deploy-hf.yml` mirrors the repo to a Hugging
Face Docker Space, which rebuilds asynchronously. Requires `HF_TOKEN` (secret)
plus `HF_USERNAME` and `HF_SPACE` (variables); without the token the workflow
no-ops rather than failing.

Two scheduled jobs run against production data:

- `accuracy-report.yml` — daily at 12:00 UTC, grades yesterday's finished games.
- `refresh-best-bets.yml` — every three hours, re-prices the board.

The Space's filesystem is ephemeral. Anything worth keeping is committed.

---

## Conventions

**Comments say why, not what.** The codebase is heavily commented and the
comments carry reasoning — which alternative was rejected, what broke before,
which number is a decision rather than a measurement. Match that. A comment
restating the line beneath it is noise; a comment explaining why the obvious
approach fails is the point.

**Tests are named as claims.** `test_the_headline_is_the_mean_of_the_distribution`,
not `test_forecast_2`. Docstrings say what would break in production if the
assertion failed. Several tests deliberately pin a *known residual* with the
bias written down rather than widening a tolerance to hide it — for example,
pitches per plate appearance runs about 3.7 against a real 3.9, and the test
says so.

**Numbers get validated against reality where reality is knowable.** The pitch
chain was checked against MLB's real per-pitch mix (ball 36%, called strike
17%, swinging strike 11%, foul 18%, in play 17.5%) even though it was only ever
fitted to strikeout and walk rates. Agreement there is evidence the mechanism
is right rather than a tautology. Do the same for anything new.

**Frontend must be clean.** `npm --prefix web run check` reports zero unused CSS
selectors today. If you delete markup, delete its styles — but only drop a CSS
rule when *every* selector in it is dead, or a shared rule takes a live
section's styling with it.

---

## Not used

The `.beads/` directory and its issue tracker are **not in use**. `bd` is not
installed, the git hooks in `.beads/hooks/` are not linked into `.git/hooks/`,
and nothing in the current workflow depends on them. Earlier versions of this
file and of `CLAUDE.md` were mostly beads instructions; ignore any you find
elsewhere. Use whatever task tracking your own harness provides.
