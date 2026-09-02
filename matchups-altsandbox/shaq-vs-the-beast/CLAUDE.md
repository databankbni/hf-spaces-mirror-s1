# Project instructions

**Read [AGENTS.md](AGENTS.md).** It is the single source of truth for this
project: commands, repo map, the invariants that will cost you if you break
them, and the environment's real constraints (no outbound network in dev, a
stale bundled database).

This file exists so that whichever agent reads first lands in the same place.
Do not duplicate guidance here — a second copy drifts from the first, and then
two agents are working from different rules.

## Session completion

Work is not complete until `git push` succeeds.

```bash
python -m pytest -q                  # 703 tests
npm --prefix web run check           # 0 errors, 0 warnings
npm --prefix web run build
git pull --rebase && git push
```

The deployed app writes graded-game records back to `main` on a schedule, so
`git pull --rebase` before pushing is routine rather than exceptional.
