# HDTetris — high-score engine, watchdog, and strategy lab

HDTetris uses a hybrid policy: a stable expert board evaluator, a migrated neural value model, and selective expectiminimax over the stochastic 7-bag piece stream. The objective is sustained survival and repeatable high scores rather than a lucky isolated game.

## Search engine

```
current piece ──► all legal placements (10-bit bitboard)
                       │
                       ├─ full-width shallow ranking + neural value
                       │
                       └─ top root beam ─► max node (known next piece)
                                             └─ chance node (piece distribution)
                                                   └─ cached column-pruned max nodes
                                                         └─ expert/neural leaf value
```

- Search supports depth **2 through 5** (`LOOKAHEAD`), defaulting to depth 5. Depth is adaptive: three consecutive steps over `DEPTH_SLOW_MS` (800 ms) back off to depth 4, and ten consecutive steps under `DEPTH_FAST_MS` (350 ms) re-enter depth 5, so the strongest lookahead is used whenever the Space CPU budget allows it.
- Depth 5 uses a deterministic rotating stratified chance sample at the deepest chance layers (`DEPTH5_CHANCE_WIDTH=4`) while retaining the full seven-piece expectation at upper layers. This keeps stochastic lookahead meaningful without multiplying seven branches at every leaf.
- Transposition caching is scoped to each move and keyed by `(bitboard, piece type, depth, strategy)`. Shifted rotation masks, row-bit positions, and transposed column masks are cached; exact drops use column bit queries, deeper branches use the cheap bitboard score, and full 21-feature extraction is reserved for final leaves.
- The benchmark/health loop never changes the production search settings. Normal depth-5 moves were measured at roughly **320–480 ms** locally after exact bitboard-drop optimization; the Space's depth-4 steps remain in the low hundreds of milliseconds.
- A fair 7-bag generator removes impossible piece droughts and makes comparisons more consistent.
- The neural value network is 96-wide and migrates overlapping weights from the old 64-wide checkpoint without resetting its generation.
- The strategy population contains CHAMPION, SURVIVAL, TETRIS_SETUP, FLAT_STACK, and WELL_BUILDER. The champion is always available as a safe fallback; specialists are deliberately probed and mutated only after real games.
- Prioritized replay remains enabled with a 100k buffer, clipped gradients, and target-network synchronization.

The deployed run inherited the previous best of **987,910 points / 7,315 lines** and reached generation 2,338 with the new model version.

## Frontend playback & play-mode fixes

- **Real-time AI falling animation**: SSE only carries final placed boards, so the live view diffs each frame against the previous one and re-enacts the newly placed piece dropping in from above (~150 ms eased drop). Line clears still snap instantly with particles at the cleared rows.
- **Simulation glitch fix**: the best-game archive is strided/compacted to stay small, so consecutive frames can differ by several pieces, and line clears shift cells down. The old code animated all of those as one unit, producing glitched block clusters. Now a drop is animated only when the diff is exactly one clean 4-cell tetromino; every other transition snaps to the frame instantly (block-by-block, no clusters). `MAX_REPLAY_FRAMES` raised so future best games retain more placements.
- **Full-replay preservation verified**: the live 3M-point game (gen 2823, 2,999,080 pts) was recorded under an older build with a smaller frame cap, so its archive is strided (4,880 frames for ~7,800 placements; lines-jumps of 7–22 prove frames skip placements) — the full replay is **not** recoverable retroactively. The pipeline is fixed going forward: `MAX_REPLAY_FRAMES` raised to 60,000 AND landed frames are now stored packed (one digit per cell) in memory and on disk, so a ~3M game (≈24k placements) fits fully per-placement (~15MB packed) and the sim can play it block-by-block.
- **Per-move replay scrubber**: ⏮/⏭ buttons (and Left/Right arrows in sim mode) step the simulation forward/backward **one placement at a time**. Forward steps animate the next piece dropping in and then pause; backward steps lift the last placed piece back out (reverse of the falling animation). Line-clear or strided transitions snap instantly. Verified: stepping forward through all 4,579 frames then back returns to frame 0 with 0 board mismatches.
- **Play mode**: a proper GAME OVER overlay shows score + personal best with a PLAY AGAIN button (Enter also restarts). Previously the restart guard (`!pPiece`) froze the game after losing. Restored saves are validated: topped-out boards (cells in the top two rows) or boards where the next piece can't spawn are discarded so a broken/lost save can never trap the player in an instant game-over loop.
- **Audio**: the WebAudio context is unlocked on the first pointer/key interaction instead of waiting for the first sound, so sound works the moment the page is used.
- **Pause**: Space/Shift toggles the PAUSED overlay as before; game-over overlay is separate and never conflicts.

## Durable persistence and watchdog

Hugging Face model repo: `hyperhrishihd/HDTetrisAI-checkpoints`.

Every episode is inserted locally with a stable `episode_id` and queued to `episodes/<episode_id>.json`. Full checkpoints upload the model, packed best replay, complete SQLite database, and `history_manifest.json` every 120 seconds. GitHub receives compressed fallback copies because its Contents API has a practical 1 MB limit.

Each successful HF checkpoint also publishes:

- `health/dqn_model_<generation>.pth`
- `health/best_game_<generation>.json`
- `health/manifest.json` (written last, only after both files validate)

The watchdog runs every 60 seconds. It monitors step heartbeats, errors, local history counts, and the remote health manifest. It merges a larger remote archive if local history shrinks and restores the latest validated health model/replay/database if training stalls for five minutes. Restores happen under the engine lock so the training thread cannot observe a half-loaded model.

Startup and upload are merge-only: a short/stale Space database cannot erase the complete archive. The recovered archive includes every generation from 0 through the latest synced Space generation.

Best replays are packed to one color digit per cell before persistence. The browser decodes packed and legacy frames, reducing large million-point replays dramatically while retaining visual playback.

## 10,000-seed strategy benchmark

`benchmark.py` is a reproducible, training-free gate. It runs every strategy over the same deterministic 7-bag seeds, records mean/median/P95/max score, lines, moves, and top-out rate, and writes `benchmark_latest.json` atomically. Its dedicated immutable-bitboard loop uses a six-candidate column-pruned beam (`BENCHMARK_BEAM`) and the dominant expert signals without PyTorch, replay, feature extraction, or future search, so the 10,000-seed gate does not change the production policy or consume training state.

- CLI: `python benchmark.py --seeds 10000 --max-moves 80 --workers 5`
- Dashboard: `/benchmark`
- API: `GET /benchmark/status`, `GET|POST /benchmark/run?seeds=10000&max_moves=80`
- The gate passes when CHAMPION remains within the configured median/mean tolerance of the best specialist and does not have an excessive top-out rate.
- Benchmark output is ignored locally and is never treated as a training checkpoint.

## Replay and UI behavior

- Simulation starts at 1x human pace with smooth eased playback: every placement animates the new piece dropping into place instead of a choppy per-frame slideshow, with 2x/5x/10x/20x controls.
- Clear events carry exact cleared-row indices. Particles spawn on completed rows, not in the middle of the board.
- AI replay and human play trigger line-clear audio, particles, and screen shake.
- Canvas rendering avoids per-cell shadow blur and uses a bounded particle pool for smooth high-speed playback.
- Human play retains local-browser save/resume and Space/Shift pause behavior, and each finished round is recorded to a local human history.
- The Logs modal shows HUMAN LOGS by default while in Play mode (with a button to switch to the full AI training archive), and AI training logs otherwise.
- `/history?limit=0` returns the complete archive with strategy, depth, timing, and episode IDs.

## Space environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `HF_TOKEN` | empty | Primary checkpoint/history store |
| `HF_REPO` | `hyperhrishihd/HDTetrisAI-checkpoints` | HF model repo |
| `GITHUB_TOKEN` | empty | Compressed fallback mirror and keep-alive workflow |
| `SYNC_INTERVAL_SECONDS` | `120` | Full checkpoint interval; episode events are queued immediately |
| `HISTORY_MAX_ROWS` | `0` | 0 keeps complete history |
| `LOOKAHEAD` | `5` | Production selective expectiminimax depth; backs off to 4 adaptively |
| `DEPTH_SLOW_MS` | `800` | Step ms above this backs depth off to 4 after 3 slow steps |
| `DEPTH_FAST_MS` | `350` | Step ms below this re-enters depth 5 after 10 fast steps |
| `LOOKAHEAD_K` | `2` | Root candidates refined deeply |
| `LOOKAHEAD_B` | `1` | Deeper column-pruned beam |
| `LOOKAHEAD_C` | `1` | Final candidates retained per chance type |
| `DEPTH5_CHANCE_WIDTH` | `4` | Stratified depth-5 chance width |
| `BENCHMARK_BEAM` | `6` | Candidate beam for the training-free strategy gate |
| `MODEL_HIDDEN_DIM` | `96` | Neural hidden width; old 64-wide checkpoints migrate |
| `TORCH_THREADS` | `2` | Bounded CPU inference/training threads |
| `WATCHDOG_INTERVAL_SECONDS` | `60` | Health-check interval |
| `WATCHDOG_STALL_SECONDS` | `300` | No-step duration before healthy restore |
| `WATCHDOG_FAILURE_LIMIT` | `3` | Consecutive training errors before restore |
| `HEALTH_SNAPSHOT_KEEP` | `8` | Reserved health-retention setting |

## Verification before deployment

- Compile `app.py` and `benchmark.py`; extract the inline browser script and run `node --check`.
- Boot with threads disabled; verify model reload, full history range, packed replay, and all routes.
- Measure depth 5 and run a small fixed-seed strategy benchmark.
- Run the 10,000-seed benchmark gate before production promotion when CPU time permits.
- Exercise `/state`, `/stream`, `/best_game`, `/history?limit=0`, `/benchmark`, and `/benchmark/status`.
- Poll the Space until `RUNNING`; verify depth, watchdog status, healthy generation, history count, title, and checkpoint health manifest.
