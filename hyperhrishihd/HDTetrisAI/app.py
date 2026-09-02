import random
import json
import os
import time
import sqlite3
import threading
import traceback
import base64
import io
import gzip
import math
import queue
import uuid
import requests
from flask import Flask, render_template_string, jsonify, Response, request

# --- PYTORCH & DEEP Q-LEARNING DEPENDENCIES ---
import torch
import torch.nn as nn
import torch.optim as optim
from collections import deque

# Tiny CPU batches are faster and more predictable with a bounded thread pool.
try:
    torch.set_num_threads(max(1, min(4, int(os.environ.get("TORCH_THREADS", "2")))))
    torch.set_num_interop_threads(1)
except Exception:
    pass

# --- CONFIGURATION & DATABASE ---
BASE_DIR = os.path.dirname(os.path.realpath(__file__))
DB_FILE = os.path.join(BASE_DIR, "ai_evolution.db")
MODEL_FILE = os.path.join(BASE_DIR, "dqn_model.pth")
GITHUB_REPO = "HyperHrishi-HD/HDTetrisAI"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# --- DURABLE PERSISTENCE CONFIG ---
# Hugging Face Hub (primary store; LFS-backed, no 1 MB file limit).
HF_REPO = os.environ.get("HF_REPO", "hyperhrishihd/HDTetrisAI-checkpoints")
HF_TOKEN = os.environ.get("HF_TOKEN", "")
try:
    from huggingface_hub import HfApi, hf_hub_download
    _HF_AVAILABLE = True
except ImportError:
    _HF_AVAILABLE = False

# Checkpoints are periodic; individual episodes are queued and uploaded separately so
# an interrupted Space never erases the history accumulated since the last full DB sync.
SYNC_INTERVAL_SECONDS = max(30, int(os.environ.get("SYNC_INTERVAL_SECONDS", "120")))
HISTORY_MAX_ROWS = int(os.environ.get("HISTORY_MAX_ROWS", "0"))  # 0 = keep every episode
HISTORY_EVENT_SYNC = os.environ.get("HISTORY_EVENT_SYNC", "1") != "0"

# Search is a true selective expectiminimax: the root is fully considered, then the
# best root beam is searched through chance nodes. All deeper candidates are ranked by
# cheap column/bitboard heuristics before neural evaluation.
LOOKAHEAD = max(2, min(5, int(os.environ.get("LOOKAHEAD", "5"))))
LOOKAHEAD_K = max(2, int(os.environ.get("LOOKAHEAD_K", "2")))  # root beam for deep search
LOOKAHEAD_B = max(1, int(os.environ.get("LOOKAHEAD_B", "1")))  # beam at chance branches
LOOKAHEAD_C = max(1, int(os.environ.get("LOOKAHEAD_C", "1")))  # final candidates/type
MODEL_HIDDEN_DIM = max(64, int(os.environ.get("MODEL_HIDDEN_DIM", "96")))
MODEL_VALUE_BLEND = float(os.environ.get("MODEL_VALUE_BLEND", "0.12"))
SEARCH_DISCOUNT = float(os.environ.get("SEARCH_DISCOUNT", "0.96"))
# Full per-placement replays are preserved up to this many frames so the sim can
# play block-by-block (a 3M-point game is ~24k placements; 60k covers ~15M points).
# Frames are packed (one digit per cell) in memory and on disk, so this stays small:
# 60k packed frames is only ~15MB, and the in-memory history is the same compact form.
MAX_REPLAY_FRAMES = max(1000, int(os.environ.get("MAX_REPLAY_FRAMES", "60000")))
SEARCH_CACHE_LIMIT = max(128, int(os.environ.get("SEARCH_CACHE_LIMIT", "4096")))
DEPTH5_CHANCE_WIDTH = max(3, min(7, int(os.environ.get("DEPTH5_CHANCE_WIDTH", "4"))))
# Adaptive-depth thresholds: step ms above DEPTH_SLOW_MS backs depth off to 4 after
# three consecutive slow steps; consistently faster than DEPTH_FAST_MS re-enters 5.
DEPTH_SLOW_MS = float(os.environ.get("DEPTH_SLOW_MS", "800.0"))
DEPTH_FAST_MS = float(os.environ.get("DEPTH_FAST_MS", "350.0"))
DEEP_LEAF_NEURAL = os.environ.get("DEEP_LEAF_NEURAL", "0") == "1"
# Benchmark workers must be training-free and must not contact or merge remote checkpoints.
BENCHMARK_ONLY = os.environ.get("HDTETRIS_BENCHMARK_ONLY", "0") == "1"
WATCHDOG_INTERVAL_SECONDS = max(20, int(os.environ.get("WATCHDOG_INTERVAL_SECONDS", "60")))
WATCHDOG_STALL_SECONDS = max(120, int(os.environ.get("WATCHDOG_STALL_SECONDS", "300")))
WATCHDOG_FAILURE_LIMIT = max(1, int(os.environ.get("WATCHDOG_FAILURE_LIMIT", "3")))
WATCHDOG_HISTORY_GRACE = max(0, int(os.environ.get("WATCHDOG_HISTORY_GRACE", "2")))
HEALTH_SNAPSHOT_KEEP = max(3, int(os.environ.get("HEALTH_SNAPSHOT_KEEP", "8")))
BENCHMARK_FILE = os.path.join(BASE_DIR, "benchmark_latest.json")

def init_db():
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10.0)
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute('''CREATE TABLE IF NOT EXISTS history
                         (generation INTEGER, candidate INTEGER, score INTEGER, lines INTEGER,
                          weights TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                          episode_id TEXT, strategy TEXT, search_depth INTEGER, step_ms REAL)''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS best_game
                         (id INTEGER PRIMARY KEY, score INTEGER, lines INTEGER,
                          generation INTEGER, frames TEXT)''')

        # Add columns to databases created by older Space builds without deleting any
        # rows. A stable episode_id makes merging HF/GitHub snapshots idempotent.
        for column, definition in (
            ("episode_id", "TEXT"), ("strategy", "TEXT"),
            ("search_depth", "INTEGER"), ("step_ms", "REAL")
        ):
            try:
                cursor.execute(f"ALTER TABLE history ADD COLUMN {column} {definition}")
            except sqlite3.OperationalError:
                pass
        cursor.execute("UPDATE history SET episode_id = 'legacy-' || rowid WHERE episode_id IS NULL OR episode_id = ''")
        cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_episode_id ON history (episode_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_score ON history (score DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_gen ON history (generation)')

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database Init Error: {e}")

# --- TETRIS CONSTANTS ---
GRID_W, GRID_H = 10, 20
_FULL_ROW_MASK = (1 << GRID_W) - 1
_ROW_BIT_POSITIONS = tuple(
    tuple(x for x in range(GRID_W) if mask & (1 << x))
    for mask in range(1 << GRID_W)
)

SHAPES = [
    [[1, 1, 1, 1]],                 # I
    [[1, 1], [1, 1]],               # O
    [[0, 1, 0], [1, 1, 1]],         # T
    [[0, 1, 1], [1, 1, 0]],         # S
    [[1, 1, 0], [0, 1, 1]],         # Z
    [[1, 0, 0], [1, 1, 1]],         # J
    [[0, 0, 1], [1, 1, 1]]          # L
]

# Vibrant Cyberpunk Neon Color Palette
SHAPE_COLORS = [
    (0, 243, 255),   # Neon Cyan (I)
    (255, 234, 0),   # Neon Yellow (O)
    (157, 0, 255),   # Neon Purple (T)
    (0, 255, 102),   # Neon Green (S)
    (255, 0, 127),   # Neon Pink/Red (Z)
    (0, 102, 255),   # Neon Blue (J)
    (255, 128, 0)    # Neon Orange (L)
]

_COLOR_TO_INDEX = {tuple(color): index + 1 for index, color in enumerate(SHAPE_COLORS)}
def _pack_grid(grid):
    """Encode a 20x10 color grid to one digit per cell (0 = empty, 1-7 = piece)."""
    rows = []
    for row in grid:
        cells = []
        for cell in row:
            if isinstance(cell, (list, tuple)) and any(cell):
                cells.append(str(_COLOR_TO_INDEX.get(tuple(cell), 1)))
            else:
                cells.append('0')
        rows.append(''.join(cells))
    return rows

def pack_replay_frames(frames):
    """Pack replay grids to one byte-like digit per cell before durable upload.
    This keeps an 18k-frame million-point replay small enough for fast sync."""
    packed = []
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        if 'grid_packed' in frame and 'grid' not in frame:
            packed.append(frame)
            continue
        item = {key: value for key, value in frame.items() if key != 'grid'}
        grid = frame.get('grid', [])
        rows = []
        for row in grid:
            cells = []
            for cell in row:
                if isinstance(cell, (list, tuple)):
                    cells.append(str(_COLOR_TO_INDEX.get(tuple(cell), 1) if any(cell) else 0))
                else:
                    cells.append('0')
            rows.append(''.join(cells))
        item['grid_packed'] = rows
        packed.append(item)
    return packed

def rotate_matrix(shape):
    return [list(row) for row in zip(*shape[::-1])]

def get_unique_rotations(shape):
    rotations = []
    current = shape
    for _ in range(4):
        if current not in rotations:
            rotations.append(current)
        current = rotate_matrix(current)
    return rotations

# Immutable bit-row descriptions make thousands of simulated drops cheap. The public
# replay/UI still uses colored cell grids; only the search uses this representation.
_ROTATION_CACHE = {}
def get_rotation_data(shape):
    key = tuple(tuple(int(cell) for cell in row) for row in shape)
    if key not in _ROTATION_CACHE:
        data = []
        for rotation in get_unique_rotations([list(row) for row in key]):
            row_masks = tuple(sum((1 << x) for x, cell in enumerate(row) if cell)
                              for row in rotation)
            width = len(rotation[0])
            occupied_rows_by_column = tuple(
                tuple(row for row, mask in enumerate(row_masks)
                      if mask & (1 << column))
                for column in range(width)
            )
            data.append({
                'shape': rotation,
                'row_masks': row_masks,
                # Precompute every legal horizontal translation once. Search calls
                # collision checks hundreds of thousands of times at depth 5; a tuple
                # lookup is materially cheaper than a nested dict/setdefault path.
                'shifted_masks': tuple(
                    tuple(row_mask << x for row_mask in row_masks)
                    for x in range(GRID_W - width + 1)
                ),
                # Occupied local rows let _simulate_drop query the first board bit
                # below each cell directly, without scanning every vertical position.
                'occupied_rows_by_column': occupied_rows_by_column,
                'width': width,
                'height': len(rotation),
                'blocks': sum(sum(row) for row in rotation),
            })
        _ROTATION_CACHE[key] = tuple(data)
    return _ROTATION_CACHE[key]

# --- DEEP Q-NETWORK (DQN) ARCHITECTURE ---
# Feature count: 10 classic Dellacherie-style metrics + 4 extra board metrics + 7 piece one-hot.
FEATURE_COUNT = 21

class TetrisDQN(nn.Module):
    def __init__(self, input_dim=FEATURE_COUNT, hidden_dim=MODEL_HIDDEN_DIM):
        super(TetrisDQN, self).__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1)
        )
        
    def forward(self, x):
        return self.net(x)

class PrioritizedReplayBuffer:
    """Proportional prioritized experience replay (alpha=0.6, beta annealed to 1.0)."""
    def __init__(self, capacity=60000, alpha=0.6, beta=0.4):
        self.buffer = deque(maxlen=capacity)
        self.alpha = alpha
        self.beta = beta
        self.beta_inc = 0.0005
        self.max_priority = 1.0

    def push(self, state, reward, next_state, done):
        self.buffer.append((state, reward, next_state, done, self.max_priority))

    def sample(self, batch_size):
        if len(self.buffer) < batch_size:
            return None
        self.beta = min(1.0, self.beta + self.beta_inc)
        priorities = torch.tensor([e[4] for e in self.buffer], dtype=torch.float32) ** self.alpha
        probs = priorities / priorities.sum()
        indices = torch.multinomial(probs, batch_size, replacement=False)
        states, rewards, next_states, dones = [], [], [], []
        for i in indices.tolist():
            s, r, ns, d, _ = self.buffer[i]
            states.append(s); rewards.append(r); next_states.append(ns); dones.append(d)
        total = len(self.buffer)
        weights = (total * probs[indices]) ** (-self.beta)
        weights = weights / weights.max()
        return (torch.tensor(states, dtype=torch.float32),
                torch.tensor(rewards, dtype=torch.float32),
                torch.tensor(next_states, dtype=torch.float32),
                torch.tensor(dones, dtype=torch.float32),
                weights.detach().clone(),
                indices)

    def update_priorities(self, indices, td_errors):
        for i, td in zip(indices.tolist(), td_errors):
            p = float(abs(td)) + 1e-6
            self.buffer[i] = (self.buffer[i][0], self.buffer[i][1],
                              self.buffer[i][2], self.buffer[i][3], p)
            if p > self.max_priority:
                self.max_priority = p

    def __len__(self):
        return len(self.buffer)

# --- ADVANCED TETRIS DEEP Q-LEARNING & 2-PIECE LOOKAHEAD ENGINE ---
class TetrisDQNEngine:
    def __init__(self):
        self.grid_w, self.grid_h = GRID_W, GRID_H
        self.generation = 0
        
        self.all_time_best_score = 0
        self.all_time_best_lines = 0
        self.all_time_best_gen = 0
        self.all_time_best_game_memory = []
        
        self.current_game_history = []
        self.live_state = {}
        
        # PyTorch Model & Hyperparameters
        self.device = torch.device("cpu")
        self.model = TetrisDQN(input_dim=FEATURE_COUNT, hidden_dim=MODEL_HIDDEN_DIM).to(self.device)
        self.target_model = TetrisDQN(input_dim=FEATURE_COUNT, hidden_dim=MODEL_HIDDEN_DIM).to(self.device)
        self.target_model.load_state_dict(self.model.state_dict())

        self.optimizer = optim.Adam(self.model.parameters(), lr=0.0007)
        self.replay_buffer = PrioritizedReplayBuffer(capacity=100000)

        self.gamma = 0.99
        self.epsilon = 1.0
        self.epsilon_min = 0.005
        self.epsilon_decay = 0.999
        self.batch_size = 96
        self.train_step_count = 0
        self.training_updates = 0

        # The neural value is one signal. A small population of proven board-evaluation
        # strategies supplies a stable champion and lets the agent evolve risk tolerance
        # instead of forgetting a strong policy when exploration changes.
        self.strategy_population = self._default_strategy_population()
        self.active_strategy_id = 0
        self.strategy_games = 0
        self.strategy_champion_score = 0
        self.session_id = uuid.uuid4().hex[:12]
        self.piece_bag = []
        self.current_game_id = ""
        self.last_clears = 0
        self.last_clear_rows = []
        self.last_event_id = ""
        self.last_step_ms = 0.0
        self.control_lock = threading.RLock()
        # Adaptive search depth: start at the configured target and back off to
        # depth 4 only when measured step time shows the CPU budget can't sustain
        # depth 5, so the strongest lookahead is used whenever the Space allows it.
        self.target_depth = LOOKAHEAD
        self.effective_depth = LOOKAHEAD
        self.depth_slow_streak = 0
        self.depth_fast_streak = 0
        self.search_cache = {}
        self.last_step_started_at = time.time()
        self.last_step_completed_at = time.time()
        self.steps_completed = 0
        self.step_failures = 0
        self.last_error = ""
        self.last_healthy_generation = 0
        self.last_healthy_history_count = 0
        self.watchdog_status = "starting"
        self.last_watchdog_at = 0.0
        self.watchdog_restores = 0
        self.benchmark_mode = False
        self.strategy_override = None

        self.load_model()
        self.load_all_time_best()
        self.reset_game()

    def _default_strategy_population(self):
        # The first 14 weights correspond to the non one-hot features. Values are applied
        # to normalized board metrics, so the population remains stable as games get long.
        return [
            {"name": "CHAMPION", "weights": [-2.2, 1.1, -1.5, -0.8, -8.0, -0.25, -1.8, -1.0, -1.2, -1.6, -2.4, -0.8, -2.0, -0.15], "line_bonus": [0, 3, 12, 30, 72], "ema": 0.0, "games": 0},
            {"name": "SURVIVAL", "weights": [-3.0, 0.8, -1.8, -1.0, -12.0, -0.4, -3.0, -1.4, -1.5, -2.0, -3.5, -1.0, -3.0, -0.2], "line_bonus": [0, 2, 8, 20, 50], "ema": 0.0, "games": 0},
            {"name": "TETRIS_SETUP", "weights": [-1.5, 1.5, -1.2, -0.6, -6.0, -0.15, -1.2, -0.8, -0.9, -1.2, -1.7, -0.6, -1.5, 0.0], "line_bonus": [0, 4, 16, 45, 120], "ema": 0.0, "games": 0},
            {"name": "FLAT_STACK", "weights": [-2.5, 0.8, -2.0, -1.2, -7.0, -0.2, -1.5, -1.0, -1.8, -2.4, -3.2, -1.4, -2.5, -0.2], "line_bonus": [0, 2, 10, 28, 65], "ema": 0.0, "games": 0},
            {"name": "WELL_BUILDER", "weights": [-1.8, 1.0, -1.3, -0.7, -7.0, -0.1, -1.5, -0.8, -1.0, -1.3, -2.0, -0.7, -1.7, 0.4], "line_bonus": [0, 3, 14, 38, 95], "ema": 0.0, "games": 0}
        ]

    def _select_next_strategy(self):
        # Keep the champion as the safe default. Every 24th game deliberately probes one
        # specialist in round-robin order; specialists never replace the champion without
        # evidence, but they do get real games and can discover a better risk profile.
        if self.strategy_games and self.strategy_games % 24 == 0:
            return (self.strategy_games // 24) % len(self.strategy_population)
        return 0

    def _strategy_for_features(self, features):
        if self.strategy_override is not None:
            return int(self.strategy_override) % len(self.strategy_population)
        if features[10] >= 15 or features[4] >= 4:
            return 1  # survival mode when the stack is genuinely dangerous
        if features[10] <= 8 and features[5] >= 5:
            return 4  # preserve a useful well while the board is safe
        return self.active_strategy_id

    def load_model(self):
        if os.path.exists(MODEL_FILE):
            try:
                checkpoint = torch.load(MODEL_FILE, map_location=self.device)
                old_state = checkpoint['model_state']
                try:
                    self.model.load_state_dict(old_state)
                    self.target_model.load_state_dict(old_state)
                except Exception:
                    # Architecture upgrade: copy overlapping rows/columns into the wider
                    # network so the learned policy continues instead of restarting.
                    print("Architecture upgrade detected - migrating checkpoint weights")
                    new_state = self.model.state_dict()
                    for key, new_tensor in new_state.items():
                        if key not in old_state:
                            continue
                        old_tensor = old_state[key]
                        if old_tensor.shape == new_tensor.shape:
                            new_state[key] = old_tensor.clone()
                        elif 'weight' in key and old_tensor.ndim == 2:
                            n = min(old_tensor.shape[0], new_tensor.shape[0])
                            m = min(old_tensor.shape[1], new_tensor.shape[1])
                            new_state[key] = new_tensor.clone()
                            new_state[key][:n, :m] = old_tensor[:n, :m]
                        elif 'bias' in key:
                            n = min(old_tensor.shape[0], new_tensor.shape[0])
                            new_state[key] = new_tensor.clone()
                            new_state[key][:n] = old_tensor[:n]
                    self.model.load_state_dict(new_state)
                    self.target_model.load_state_dict(new_state)
                    print("Migrated checkpoint into new architecture")
                self.generation = checkpoint.get('generation', 0)
                self.epsilon = max(self.epsilon_min, min(1.0, checkpoint.get('epsilon', 0.05)))
                self.last_healthy_generation = self.generation
                saved_strategies = checkpoint.get('strategy_population')
                if isinstance(saved_strategies, list) and saved_strategies:
                    for i, saved in enumerate(saved_strategies[:len(self.strategy_population)]):
                        if isinstance(saved, dict) and isinstance(saved.get('weights'), list):
                            self.strategy_population[i].update(saved)
                self.active_strategy_id = int(checkpoint.get('active_strategy_id', 0)) % len(self.strategy_population)
                self.strategy_games = int(checkpoint.get('strategy_games', 0))
                self.strategy_champion_score = int(checkpoint.get('strategy_champion_score', 0))
                print(f"Successfully loaded DQN model from generation {self.generation}")
            except Exception as e:
                print(f"Error loading model checkpoint: {e}")

    def save_model(self):
        try:
            # Atomic write (temp + rename) so the sync thread never reads a half-written file.
            tmp_file = MODEL_FILE + ".tmp"
            checkpoint = {
                'model_version': 4,
                'model_state': self.model.state_dict(),
                'generation': self.generation,
                'epsilon': self.epsilon,
                'strategy_population': self.strategy_population,
                'active_strategy_id': self.active_strategy_id,
                'strategy_games': self.strategy_games,
                'strategy_champion_score': self.strategy_champion_score,
            }
            torch.save(checkpoint, tmp_file)
            with open(tmp_file, 'ab') as f:
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, MODEL_FILE)
        except Exception as e:
            print(f"Error saving model: {e}")

    def load_all_time_best(self):
        try:
            conn = sqlite3.connect(DB_FILE, timeout=5.0)
            cursor = conn.cursor()
            cursor.execute("SELECT score, lines, generation, frames FROM best_game ORDER BY score DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                self.all_time_best_score = row[0]
                self.all_time_best_lines = row[1]
                self.all_time_best_gen = row[2]
                self.all_time_best_game_memory = pack_replay_frames(json.loads(row[3]))
            conn.close()
        except Exception:
            pass

    def _compact_frames(self, frames):
        if len(frames) <= MAX_REPLAY_FRAMES:
            return list(frames)
        stride = max(1, math.ceil(len(frames) / MAX_REPLAY_FRAMES))
        compacted = list(frames[::stride])
        if frames[-1] is not compacted[-1]:
            compacted.append(frames[-1])
        return compacted

    def save_all_time_best(self, score, lines, gen, frames):
        try:
            conn = sqlite3.connect(DB_FILE, timeout=10.0)
            cursor = conn.cursor()
            frames_json = json.dumps(self._compact_frames(frames), separators=(',', ':'))
            cursor.execute("DELETE FROM best_game")
            cursor.execute("INSERT INTO best_game (score, lines, generation, frames) VALUES (?,?,?,?)",
                           (score, lines, gen, frames_json))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error saving best game: {e}")

    def reset_game(self):
        self.grid = [[(0,0,0) for _ in range(self.grid_w)] for _ in range(self.grid_h)]
        self.score = 0
        self.lines = 0
        self.active_strategy_id = self._select_next_strategy()
        self.current_game_id = f"{self.session_id}-{self.generation}-{uuid.uuid4().hex[:8]}"
        self.current_piece = self.new_piece()
        self.next_piece = self.new_piece()
        self.game_over = False
        self.current_game_history = []
        self.last_clears = 0
        self.last_clear_rows = []
        self.last_event_id = ""
        self.last_step_ms = 0.0
        self.update_live_state()

    def update_live_state(self):
        strategy = self.strategy_population[self.active_strategy_id]
        self.live_state = {
            'grid': [list(row) for row in self.grid],
            'piece': self.current_piece,
            'score': self.score,
            'lines': self.lines,
            'next': self.next_piece['shape'],
            'next_color': f"rgb{self.next_piece['color']}",
            'gen': self.generation,
            'cand': 1,
            'best_score': self.all_time_best_score,
            'epsilon': round(self.epsilon, 3),
            'clears': self.last_clears,
            'clear_rows': list(self.last_clear_rows),
            'event_id': self.last_event_id,
            'strategy': strategy.get('name', 'CHAMPION'),
            'search_depth': self.effective_depth,
            'step_ms': round(self.last_step_ms, 1),
            'steps_completed': self.steps_completed,
            'step_failures': self.step_failures,
            'last_error': self.last_error[-160:] if self.last_error else "",
            'watchdog': self.watchdog_status,
            'watchdog_restores': self.watchdog_restores,
            'healthy_generation': self.last_healthy_generation,
            'healthy_history_count': self.last_healthy_history_count
        }

    def new_piece(self):
        # A 7-bag makes the stochastic model match real Tetris and removes the long,
        # unfair droughts that made high scores inconsistent.
        if not self.piece_bag:
            self.piece_bag = list(range(len(SHAPES)))
            random.shuffle(self.piece_bag)
        idx = self.piece_bag.pop()
        return {'shape': SHAPES[idx], 'color': SHAPE_COLORS[idx], 'type': idx, 'x': 3, 'y': 0}

    def check_collision(self, grid, piece, adj_x=0, adj_y=0, shape=None):
        s = shape or piece['shape']
        for i, row in enumerate(s):
            for j, cell in enumerate(row):
                if cell:
                    x, y = piece['x'] + j + adj_x, piece['y'] + i + adj_y
                    if x < 0 or x >= self.grid_w or y >= self.grid_h:
                        return True
                    if y >= 0 and grid[y][x] != (0,0,0):
                        return True
        return False

    def _grid_to_masks(self, grid):
        if isinstance(grid, tuple) and (not grid or isinstance(grid[0], int)):
            return grid
        if grid and isinstance(grid[0], int):
            return tuple(int(row) for row in grid)
        return tuple(sum((1 << x) for x, cell in enumerate(row) if cell != (0, 0, 0))
                     for row in grid)

    def _masks_to_grid(self, masks, color):
        return [[color if (row_mask & (1 << x)) else (0, 0, 0)
                 for x in range(self.grid_w)] for row_mask in masks]

    def _extract_mask_features(self, masks, landing_y, piece_blocks, clears, piece_type=None):
        heights = [0] * self.grid_w
        holes = 0
        hole_depth = 0
        blockades = 0
        row_has_hole = [False] * self.grid_h
        for x in range(self.grid_w):
            found_top = False
            col_holes = 0
            for y, row_mask in enumerate(masks):
                occupied = (row_mask >> x) & 1
                if occupied:
                    if not found_top:
                        heights[x] = self.grid_h - y
                        found_top = True
                    if col_holes:
                        blockades += 1
                elif found_top:
                    holes += 1
                    col_holes += 1
                    row_has_hole[y] = True
                    hole_depth += y - (self.grid_h - heights[x])

        agg_height = sum(heights)
        bumpiness = sum(abs(heights[i] - heights[i + 1]) for i in range(self.grid_w - 1))
        row_trans = 0
        for row_mask in masks:
            for x in range(self.grid_w - 1):
                if ((row_mask >> x) & 1) != ((row_mask >> (x + 1)) & 1):
                    row_trans += 1
            if not (row_mask & 1):
                row_trans += 1
            if not (row_mask & (1 << (self.grid_w - 1))):
                row_trans += 1

        col_trans = 0
        for x in range(self.grid_w):
            for y in range(self.grid_h - 1):
                if ((masks[y] >> x) & 1) != ((masks[y + 1] >> x) & 1):
                    col_trans += 1
            if not (masks[-1] & (1 << x)):
                col_trans += 1

        well_sums = 0
        deepest_well = 0
        for x in range(self.grid_w):
            well_depth = 0
            for y, row_mask in enumerate(masks):
                left = x == 0 or (row_mask & (1 << (x - 1)))
                right = x == self.grid_w - 1 or (row_mask & (1 << (x + 1)))
                if not (row_mask & (1 << x)) and left and right:
                    well_depth += 1
                    well_sums += well_depth
                    deepest_well = max(deepest_well, well_depth)
                else:
                    well_depth = 0

        one_hot = [0] * len(SHAPES)
        if piece_type is not None and 0 <= piece_type < len(SHAPES):
            one_hot[piece_type] = 1
        mean_height = agg_height / self.grid_w
        return [
            self.grid_h - landing_y,
            clears * piece_blocks,
            row_trans,
            col_trans,
            holes,
            well_sums,
            hole_depth,
            blockades,
            bumpiness,
            agg_height,
            max(heights) if heights else 0,
            sum((h - mean_height) ** 2 for h in heights) / self.grid_w,
            sum(row_has_hole),
            deepest_well,
        ] + one_hot

    def extract_features(self, grid, landing_y, piece_blocks, clears, piece_type=None):
        return self._extract_mask_features(self._grid_to_masks(grid), landing_y,
                                           piece_blocks, clears, piece_type)

    def _expert_score(self, features, clears):
        """Stable hand-crafted champion score blended with the learned value.
        Normalization prevents a million-point game from changing move preferences."""
        strategy_id = self._strategy_for_features(features)
        strategy = self.strategy_population[strategy_id]
        scales = (20.0, 16.0, 40.0, 40.0, 20.0, 80.0, 200.0, 200.0,
                  20.0, 200.0, 20.0, 100.0, 20.0, 20.0)
        normalized = [features[i] / scales[i] for i in range(14)]
        score = sum(strategy['weights'][i] * normalized[i] for i in range(14))
        line_bonus = strategy.get('line_bonus', [0, 3, 12, 30, 72])
        score += line_bonus[min(4, max(0, int(clears)))]
        if features[10] >= 18:
            score -= 10.0 + (features[10] - 18) * 4.0
        if features[4] >= 6:
            score -= (features[4] - 5) * 3.0
        return score

    def _placement_reward(self, features, clears, game_over=False):
        line_score = [0, 100, 300, 500, 800][min(4, max(0, int(clears)))]
        reward = (line_score + clears * 5.0
                  - features[4] * 2.0
                  - features[10] * 0.35
                  - features[8] * 0.08
                  - features[9] * 0.025)
        return reward - (300.0 if game_over else 0.0)

    def _enumerate_placements(self, board, shape):
        """Every legal rotation/column at spawn, using immutable bit rows."""
        board = self._grid_to_masks(board)
        placements = []
        for info in get_rotation_data(shape):
            for x in range(self.grid_w - info['width'] + 1):
                if not self._mask_collision(board, info, x, 0):
                    placements.append((info, x))
        return placements

    def _shifted_row_masks(self, info, x):
        return info['shifted_masks'][x]

    def _mask_collision(self, board, info, x, y):
        if x < 0 or x + info['width'] > self.grid_w or y < 0 or y + info['height'] > self.grid_h:
            return True
        shifted = self._shifted_row_masks(info, x)
        for i, row_mask in enumerate(shifted):
            if board[y + i] & row_mask:
                return True
        return False

    def _column_masks(self, board):
        """Transpose 10-bit rows into cached 20-bit column masks."""
        board = self._grid_to_masks(board)
        cache_key = ('column-masks', board)
        cached = self.search_cache.get(cache_key)
        if cached is not None:
            return cached
        columns = [0] * self.grid_w
        for y, row_mask in enumerate(board):
            row_bit = 1 << y
            for column in _ROW_BIT_POSITIONS[row_mask]:
                columns[column] |= row_bit
        result = tuple(columns)
        if len(self.search_cache) < SEARCH_CACHE_LIMIT:
            self.search_cache[cache_key] = result
        return result

    def _simulate_drop(self, board, shape, x):
        """Drop a rotation and return (masks, clears, blocks, landing_y, cleared_rows)."""
        board = self._grid_to_masks(board)
        info = shape if isinstance(shape, dict) else next(
            item for item in get_rotation_data(shape)
            if item['shape'] == shape)
        # Query the first board bit below every occupied shape cell. Looking only at
        # the top block in a column is wrong for cells that start below an overhang;
        # shifted column masks retain exact top-down semantics while keeping the work
        # to at most four bit queries per affected column.
        y = self.grid_h - info['height']
        columns = self._column_masks(board)
        for local_column, local_rows in enumerate(info['occupied_rows_by_column']):
            column_mask = columns[x + local_column]
            for local_row in local_rows:
                below = column_mask >> (local_row + 1)
                if below:
                    y = min(y, (below & -below).bit_length() - 1)
        y = max(0, y)
        placed = list(board)
        for i, row_mask in enumerate(self._shifted_row_masks(info, x)):
            placed[y + i] |= row_mask
        full_mask = (1 << self.grid_w) - 1
        cleared_rows = [row for row, mask in enumerate(placed) if mask == full_mask]
        remaining = [mask for mask in placed if mask != full_mask]
        result = tuple([0] * len(cleared_rows) + remaining)
        return result, len(cleared_rows), info['blocks'], y, cleared_rows

    def _expand_piece(self, board, shape, piece_type, base_clears=0, want_boards=True):
        results = []
        for info, x in self._enumerate_placements(board, shape):
            b2, clears, blocks, y, clear_rows = self._simulate_drop(board, info, x)
            f2 = self.extract_features(b2, y, blocks, clears, piece_type)
            results.append({
                'x': x, 'shape': info['shape'], 'board': b2,
                'clears': clears, 'clear_rows': clear_rows,
                'features': f2, 'expert': self._expert_score(f2, clears),
                'reward': self._placement_reward(f2, clears), 'landing_y': y,
            })
        return results

    def _benchmark_score(self, board, clears, strategy_id):
        """Fast strategy proxy for the 10k-seed gate; no neural or feature scans."""
        board = self._grid_to_masks(board)
        columns = self._column_masks(board)
        heights = [self.grid_h - ((column & -column).bit_length() - 1) if column else 0
                   for column in columns]
        holes = sum(height - column.bit_count() for height, column in zip(heights, columns))
        agg = sum(heights)
        bump = sum(abs(heights[i] - heights[i + 1]) for i in range(self.grid_w - 1))
        strategy = self.strategy_population[strategy_id]
        weights = strategy['weights']
        lines = strategy.get('line_bonus', [0, 3, 12, 30, 72])[min(4, clears)]
        # The same dominant signals as _expert_score, deliberately avoiding the expensive
        # 21-feature extraction because this is a deployment regression gate, not training.
        value = (lines + weights[0] * (max(heights) / 20.0)
                 + weights[4] * (holes / 20.0)
                 + weights[8] * (bump / 20.0)
                 + weights[9] * (agg / 200.0)
                 + weights[10] * (max(heights) / 20.0))
        return value

    def _quick_score(self, board, clears=0):
        # Column tops plus row-mask lookup tables replace the old per-cell bitboard
        # transpose. This proxy is called for every pruned candidate at depth 5.
        board = self._grid_to_masks(board)
        columns = self._column_masks(board)
        heights = [self.grid_h - ((column & -column).bit_length() - 1) if column else 0
                   for column in columns]
        holes = sum(height - column.bit_count() for height, column in zip(heights, columns))
        bumpiness = sum(abs(heights[i] - heights[i + 1]) for i in range(self.grid_w - 1))
        return clears * 100.0 - holes * 8.0 - bumpiness * 1.5 - sum(heights) * 0.25 - max(heights) * 0.8

    def _cheap_pruned_placements(self, board, shape, piece_type, top_n, full_features=True):
        board = self._grid_to_masks(board)
        cache_key = (board, piece_type, top_n, bool(full_features))
        cached = self.search_cache.get(cache_key)
        if cached is not None:
            return [dict(candidate) for candidate in cached]

        scored = []
        for info, x in self._enumerate_placements(board, shape):
            b2, clears, blocks, y, clear_rows = self._simulate_drop(board, info, x)
            scored.append((self._quick_score(b2, clears), info, x, b2, clears, blocks, y, clear_rows))
        scored.sort(key=lambda item: item[0], reverse=True)
        out = []
        for quick, info, x, b2, clears, blocks, y, clear_rows in scored[:top_n]:
            if full_features:
                features = self.extract_features(b2, y, blocks, clears, piece_type)
                expert = self._expert_score(features, clears)
                reward = self._placement_reward(features, clears)
            else:
                # Deeper nodes only need a stable ordering signal. Full Dellacherie scans
                # are reserved for the final leaf, cutting depth-5 CPU without changing
                # the legal move set or the root evaluation.
                features = None
                expert = quick * 0.1
                reward = quick * 0.1
            out.append({
                'x': x, 'shape': info['shape'], 'board': b2, 'clears': clears,
                'clear_rows': clear_rows, 'features': features,
                'expert': expert, 'reward': reward, 'landing_y': y,
            })
        if len(self.search_cache) < SEARCH_CACHE_LIMIT:
            self.search_cache[cache_key] = [dict(candidate) for candidate in out]
        return out

    def _batch_model_values(self, candidates):
        if not candidates:
            return []
        # `no_grad` is intentionally used instead of `inference_mode`: older CPU
        # PyTorch builds can propagate inference tensors into the later replay loss.
        with torch.no_grad():
            batch = torch.as_tensor([candidate['features'] for candidate in candidates],
                                    dtype=torch.float32, device=self.device)
            values = self.model(batch).reshape(-1).detach().cpu().tolist()
        return [max(-1000.0, min(1000.0, float(value))) for value in values]

    def _value_candidates(self, candidates, include_model=True):
        model_values = self._batch_model_values(candidates) if include_model else [0.0] * len(candidates)
        for candidate, neural_value in zip(candidates, model_values):
            candidate['value'] = candidate['expert'] + MODEL_VALUE_BLEND * neural_value
        return candidates

    def _board_leaf_value(self, board):
        cache_key = (self._grid_to_masks(board), -1, 0, True)
        cached = self.search_cache.get(cache_key)
        if cached is not None:
            return cached
        features = self.extract_features(board, 0, 0, 0)
        candidate = {'features': features, 'expert': self._expert_score(features, 0)}
        value = self._value_candidates([candidate], include_model=DEEP_LEAF_NEURAL)[0]['value']
        if len(self.search_cache) < SEARCH_CACHE_LIMIT:
            self.search_cache[cache_key] = value
        return value

    def _max_expectiminimax(self, board, piece_type, depth):
        board = self._grid_to_masks(board)
        cache_key = (board, piece_type, depth, self.active_strategy_id)
        cached = self.search_cache.get(cache_key)
        if cached is not None and isinstance(cached, (int, float)):
            return cached
        if depth <= 0:
            return self._board_leaf_value(board)
        candidates = self._cheap_pruned_placements(
            board, SHAPES[piece_type], piece_type,
            LOOKAHEAD_C if depth == 1 else LOOKAHEAD_B,
            full_features=(depth == 1))
        if not candidates:
            return -10000.0
        if depth == 1:
            self._value_candidates(candidates, include_model=DEEP_LEAF_NEURAL)
        best = -10000.0
        for candidate in candidates:
            value = candidate['value'] if depth == 1 else candidate['expert']
            if depth > 1:
                value += SEARCH_DISCOUNT * self._chance_value(candidate['board'], depth - 1)
            best = max(best, value)
        if len(self.search_cache) < SEARCH_CACHE_LIMIT:
            self.search_cache[cache_key] = best
        return best

    def _chance_types(self, board, depth):
        all_types = tuple(range(len(SHAPES)))
        if self.effective_depth < 5 or depth > 2 or DEPTH5_CHANCE_WIDTH >= len(all_types):
            return all_types
        # A rotating, deterministic stratified sample keeps depth 5 an expectation over
        # the piece distribution while avoiding the same four-piece blind spot every time.
        offset = sum(board) % len(all_types)
        return tuple(all_types[(offset + i) % len(all_types)] for i in range(DEPTH5_CHANCE_WIDTH))

    def _chance_value(self, board, depth):
        if depth <= 0:
            return self._board_leaf_value(board)
        types = self._chance_types(self._grid_to_masks(board), depth)
        values = [self._max_expectiminimax(board, piece_type, depth) for piece_type in types]
        return sum(values) / len(values) if values else -10000.0

    def get_best_move(self):
        board = self._grid_to_masks(self.grid)
        self.search_cache.clear()
        if self.benchmark_mode:
            # Fast, deterministic strategy benchmark: compare a proxy of the same expert
            # signals without neural training, full feature scans, or future search.
            candidates = []
            strategy_id = self.strategy_override if self.strategy_override is not None else self.active_strategy_id
            for info, x in self._enumerate_placements(board, self.current_piece['shape']):
                b2, clears, blocks, y, clear_rows = self._simulate_drop(board, info, x)
                candidates.append((self._benchmark_score(b2, clears, strategy_id), info, x,
                                   self._placement_reward([0] * FEATURE_COUNT, clears)))
            if not candidates:
                return self.current_piece['x'], self.current_piece['shape'], [0] * FEATURE_COUNT, -10.0
            _, info, x, reward = max(candidates, key=lambda item: item[0])
            return x, info['shape'], [0] * FEATURE_COUNT, reward

        root = self._expand_piece(board, self.current_piece['shape'], self.current_piece.get('type'))
        if not root:
            return self.current_piece['x'], self.current_piece['shape'], [0] * FEATURE_COUNT, -10.0

        # Shallow full-width ranking keeps a good move from being discarded before the
        # expensive chance-node search. The deep pass then refines only the root beam.
        for candidate in root:
            next_candidates = self._expand_piece(
                candidate['board'], self.next_piece['shape'], self.next_piece.get('type'))
            if next_candidates:
                self._value_candidates(next_candidates)
                candidate['val'] = candidate['expert'] + SEARCH_DISCOUNT * max(
                    item['value'] for item in next_candidates)
            else:
                candidate['val'] = candidate['expert'] - 100.0

        search_depth = self.effective_depth
        if search_depth >= 3:
            for candidate in sorted(root, key=lambda item: item['val'], reverse=True)[:LOOKAHEAD_K]:
                candidate['val'] = candidate['expert'] + SEARCH_DISCOUNT * self._max_expectiminimax(
                    candidate['board'], self.next_piece.get('type'), search_depth - 1)

        # Exploration is retained for learning, but only among the best root candidates;
        # a late-stage model can explore without throwing away a safe board at random.
        ranked = sorted(root, key=lambda item: item['val'], reverse=True)
        if random.random() < self.epsilon * 0.25:
            chosen = random.choice(ranked[:min(3, len(ranked))])
        else:
            chosen = ranked[0]
        return chosen['x'], chosen['shape'], chosen['features'], chosen['reward']

    def step(self):
        started = time.perf_counter()
        self.last_step_started_at = time.time()
        if self.game_over:
            self.on_game_over()
            return

        tx, ts, state_features, reward = self.get_best_move()
        self.current_piece['x'], self.current_piece['shape'] = tx, ts
        board = self._grid_to_masks(self.grid)
        placed, clears, blocks, fy, clear_rows = self._simulate_drop(board, ts, tx)
        self.current_piece['y'] = fy
        # Paint only the new piece's cells and drop cleared rows, preserving classic
        # per-piece colors. Repainting the whole board with the current piece's color
        # made the live board cycle through a single rainbow hue every placement.
        piece_color = self.current_piece['color']
        for i, row in enumerate(ts):
            for j, cell in enumerate(row):
                if cell:
                    self.grid[fy + i][tx + j] = piece_color
        if clear_rows:
            for row_idx in sorted(clear_rows, reverse=True):
                del self.grid[row_idx]
            for _ in clear_rows:
                self.grid.insert(0, [(0, 0, 0)] * self.grid_w)

        self.score += 10
        if clears > 0:
            self.lines += clears
            self.score += [0, 100, 300, 500, 800][min(4, clears)]

        self.current_piece, self.next_piece = self.next_piece, self.new_piece()
        is_done = self.check_collision(self.grid, self.current_piece)
        if is_done:
            self.game_over = True
            reward -= 300.0

        event_id = f"{self.current_game_id}:{len(self.current_game_history)}"
        # Store the packed board (one digit per cell) instead of the raw color grid:
        # this keeps the in-memory history and the durable archive ~10x smaller, so
        # full per-placement replays fit within the frame cap for multi-million games.
        landed_frame = {
            'grid_packed': _pack_grid(self.grid),
            'piece': None,
            'score': self.score,
            'lines': self.lines,
            'clears': clears,
            'clear_rows': list(clear_rows),
            'next': self.next_piece['shape'],
            'next_color': f"rgb{self.next_piece['color']}",
            'gen': self.generation,
            'cand': 1,
            'event_id': event_id,
        }
        self.current_game_history.append(landed_frame)
        if len(self.current_game_history) > MAX_REPLAY_FRAMES * 2:
            self.current_game_history = self._compact_frames(self.current_game_history)
        self.last_clears = clears
        self.last_clear_rows = list(clear_rows)
        self.last_event_id = event_id
        self.last_step_ms = (time.perf_counter() - started) * 1000.0
        # Cruise control for search depth: stay deep while steps stay fast, back off
        # to depth 4 after repeated slow steps, and return to depth 5 once steps are
        # consistently quick again.
        if self.effective_depth >= 5:
            if self.last_step_ms > DEPTH_SLOW_MS:
                self.depth_slow_streak += 1
                if self.depth_slow_streak >= 3:
                    self.effective_depth = 4
                    self.depth_slow_streak = 0
            else:
                self.depth_slow_streak = 0
        else:
            if self.last_step_ms < DEPTH_FAST_MS:
                self.depth_fast_streak += 1
                if self.depth_fast_streak >= 10:
                    self.effective_depth = min(self.target_depth, 5)
                    self.depth_fast_streak = 0
            else:
                self.depth_fast_streak = 0

        # The next-state representation is small and stable across the migrated models.
        next_features = ([0] * FEATURE_COUNT if self.benchmark_mode else
                         self.extract_features(self.grid, 0, 4, 0, self.current_piece.get('type')))
        self.replay_buffer.push(state_features, reward, next_features, float(is_done))
        self.train_dqn()
        self.last_step_completed_at = time.time()
        self.steps_completed += 1
        self.step_failures = 0
        self.last_error = ""
        self.update_live_state()

    def train_dqn(self):
        # Repeated updates improve sample efficiency, while the bounded replay buffer and
        # one CPU thread keep the search responsive.
        for _ in range(2):
            sampled = self.replay_buffer.sample(self.batch_size)
            if sampled is None:
                return

            states, rewards, next_states, dones, weights, indices = sampled
            states = states.to(self.device)
            rewards = rewards.to(self.device)
            next_states = next_states.to(self.device)
            dones = dones.to(self.device)
            weights = weights.to(self.device)

            q_eval = self.model(states).squeeze(1)
            with torch.no_grad():
                q_next = self.target_model(next_states).squeeze(1)
                # Detach the target after leaving the no-grad context so MSELoss never
                # receives an inference tensor that an older backend tries to save.
                q_target = (rewards + (1.0 - dones) * self.gamma * q_next).detach()

            td_errors = (q_target - q_eval).detach().cpu()
            loss = (nn.MSELoss(reduction='none')(q_eval, q_target) * weights).mean()
            self.optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), 5.0)
            self.optimizer.step()
            self.replay_buffer.update_priorities(indices, td_errors.tolist())

            self.train_step_count += 1
            self.training_updates += 1
            if self.train_step_count % 100 == 0:
                self.target_model.load_state_dict(self.model.state_dict())

    def _update_strategy(self):
        strategy = self.strategy_population[self.active_strategy_id]
        strategy['games'] = int(strategy.get('games', 0)) + 1
        previous = float(strategy.get('ema', 0.0))
        strategy['ema'] = self.score if not previous else previous * 0.9 + self.score * 0.1
        self.strategy_games += 1
        self.strategy_champion_score = max(self.strategy_champion_score, self.score)
        # Mutate only specialists; the champion weights remain an immutable fallback.
        if self.strategy_games % 48 == 0 and self.strategy_population:
            champion = self.strategy_population[0]
            specialist = self.strategy_population[(self.strategy_games // 48) % len(self.strategy_population)]
            specialist['weights'] = [round(w * (1.0 + random.uniform(-0.06, 0.06)), 5)
                                     for w in champion['weights']]
            specialist['line_bonus'] = [round(v * (1.0 + random.uniform(-0.08, 0.08)), 3)
                                         for v in champion['line_bonus']]

    def on_game_over(self):
        episode_generation = self.generation
        episode_id = self.current_game_id or f"{self.session_id}-{episode_generation}"
        self._update_strategy()
        if self.epsilon > self.epsilon_min:
            self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

        if self.score > self.all_time_best_score and len(self.current_game_history) > 5:
            self.all_time_best_score = self.score
            self.all_time_best_lines = self.lines
            self.all_time_best_gen = episode_generation
            self.all_time_best_game_memory = pack_replay_frames(
                self._compact_frames(self.current_game_history))
            self.save_all_time_best(self.score, self.lines, episode_generation,
                                    self.all_time_best_game_memory)

        strategy_name = self.strategy_population[self.active_strategy_id].get('name', 'CHAMPION')
        weights_info = json.dumps({
            "epsilon": round(self.epsilon, 5),
            "buffer_size": len(self.replay_buffer),
            "updates": self.training_updates,
            "strategy": strategy_name,
            "depth": self.effective_depth,
        }, separators=(',', ':'))
        episode_event = {
            "episode_id": episode_id, "generation": episode_generation,
            "candidate": 1, "score": self.score, "lines": self.lines,
            "strategy": strategy_name, "search_depth": self.effective_depth,
            "step_ms": round(self.last_step_ms, 2), "weights": weights_info,
            "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        }
        try:
            conn = sqlite3.connect(DB_FILE, timeout=10.0)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO history "
                "(generation,candidate,score,lines,weights,episode_id,strategy,search_depth,step_ms) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (episode_generation, 1, self.score, self.lines, weights_info,
                 episode_id, strategy_name, self.effective_depth, self.last_step_ms))
            if HISTORY_MAX_ROWS > 0:
                cursor.execute(
                    "DELETE FROM history WHERE rowid NOT IN "
                    "(SELECT rowid FROM history ORDER BY generation DESC,rowid DESC LIMIT ?)",
                    (HISTORY_MAX_ROWS,))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error logging episode: {e}")

        self.generation += 1
        self.save_model()
        if HISTORY_EVENT_SYNC:
            queue_episode_event(episode_event)
        self.reset_game()

# --- 24/7 DURABLE CHECKPOINT PERSISTENCE (Hugging Face Hub primary + GitHub fallback) ---
def _github_headers():
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers

PERSISTENCE_NETWORK_LOCK = threading.Lock()
PENDING_EPISODES = queue.Queue()

def _github_put(path, data, message):
    # GitHub's Contents API is intentionally only a fallback. Keep payloads below its
    # practical limit and store the complete unbounded history in HF LFS instead.
    if len(data) > 900_000:
        print(f"[persist] GitHub skipped {path}: {len(data)} bytes (HF remains authoritative)")
        return False
    try:
        with PERSISTENCE_NETWORK_LOCK:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
            res = requests.get(url, headers=_github_headers(), timeout=30)
            payload = {"message": message, "content": base64.b64encode(data).decode("utf-8")}
            if res.status_code == 200:
                payload["sha"] = res.json().get("sha")
            resp = requests.put(url, headers=_github_headers(), json=payload, timeout=60)
        if resp.status_code not in (200, 201):
            print(f"[persist] GitHub upload {path} failed: {resp.status_code} {resp.text[:200]}")
            return False
        return True
    except Exception as e:
        print(f"[persist] GitHub upload {path} error: {e}")
        return False

def _github_get_raw(path):
    try:
        url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/HEAD/{path}"
        res = requests.get(url, headers=_github_headers(), timeout=30)
        if res.status_code == 200:
            return res.content
    except Exception as e:
        print(f"[persist] GitHub download {path} error: {e}")
    return None

def _hf_enabled():
    return _HF_AVAILABLE and bool(HF_TOKEN)

def _hf_upload(path, data):
    try:
        with PERSISTENCE_NETWORK_LOCK:
            HfApi(token=HF_TOKEN).upload_file(path_or_fileobj=data, path_in_repo=path,
                                              repo_id=HF_REPO, repo_type="model",
                                              commit_message="Auto-sync checkpoint [24/7]")
        return True
    except Exception as e:
        print(f"[persist] HF upload {path} error: {e}")
        return False

def _hf_download(path):
    try:
        return hf_hub_download(HF_REPO, path, repo_type="model", token=HF_TOKEN)
    except Exception as e:
        # Missing optional files are normal for the first deployment.
        if "404" not in str(e) and "Entry Not Found" not in str(e):
            print(f"[persist] HF download {path} error: {e}")
        return None

def _healthy_manifest():
    if not _hf_enabled():
        return None
    path = _hf_download("health/manifest.json")
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            value = json.loads(f.read().decode('utf-8'))
        return value if isinstance(value, dict) else None
    except Exception:
        return None

def _download_healthy_model():
    manifest = _healthy_manifest()
    if not manifest:
        return None, None
    model_path = manifest.get("model_path")
    if not model_path:
        return None, manifest
    local = _hf_download(model_path)
    if not local:
        return None, manifest
    try:
        with open(local, "rb") as f:
            data = f.read()
        return data if _valid_model_blob(data) else None, manifest
    except OSError:
        return None, manifest

def _valid_model_blob(data):
    if not data or len(data) < 1000:
        return False
    try:
        checkpoint = torch.load(io.BytesIO(data), map_location="cpu")
        return isinstance(checkpoint, dict) and "model_state" in checkpoint
    except Exception:
        return False

def _checkpoint_generation(data):
    try:
        return int(torch.load(io.BytesIO(data), map_location="cpu").get("generation", -1))
    except Exception:
        return -1

def _compact_frame_payload(frames):
    original = list(frames)
    if len(original) > MAX_REPLAY_FRAMES:
        stride = max(1, math.ceil(len(original) / MAX_REPLAY_FRAMES))
        frames = list(original[::stride])
        if original and original[-1] is not frames[-1]:
            frames.append(original[-1])
    else:
        frames = original
    return pack_replay_frames(frames)

def _snapshot_best_game():
    return {
        "score": ai.all_time_best_score,
        "lines": ai.all_time_best_lines,
        "generation": ai.all_time_best_gen,
        "frames": _compact_frame_payload(ai.all_time_best_game_memory),
    }

def _history_db_bytes():
    """Return a consistent SQLite snapshot, including rows still in the WAL."""
    if not os.path.exists(DB_FILE):
        return b""
    snapshot_path = DB_FILE + f".{uuid.uuid4().hex}.snapshot.tmp"
    source = destination = None
    try:
        source = sqlite3.connect(DB_FILE, timeout=10.0)
        destination = sqlite3.connect(snapshot_path, timeout=10.0)
        source.backup(destination)
        destination.close()
        destination = None
        source.close()
        source = None
        with open(snapshot_path, "rb") as f:
            return f.read()
    except Exception as e:
        print(f"[persist] SQLite snapshot failed: {e}")
        return b""
    finally:
        for connection in (destination, source):
            try:
                if connection is not None:
                    connection.close()
            except Exception:
                pass
        try:
            os.remove(snapshot_path)
        except OSError:
            pass

def _history_summary():
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10.0)
        row = conn.execute("SELECT COUNT(*), MIN(generation), MAX(generation), MAX(score) FROM history").fetchone()
        conn.close()
        return {"episodes": row[0] or 0, "first_generation": row[1],
                "last_generation": row[2], "best_score": row[3] or 0,
                "updated_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    except Exception:
        return {"episodes": 0, "best_score": 0}

def _merge_history_bytes(data, source_label):
    """Union an older DB snapshot into the local DB without dropping local episodes."""
    if not data or len(data) < 100:
        return 0
    temp_path = DB_FILE + f".{source_label}.merge.tmp"
    try:
        with open(temp_path, "wb") as f:
            f.write(data)
        source = sqlite3.connect(temp_path, timeout=10.0)
        target = sqlite3.connect(DB_FILE, timeout=10.0)
        source_cols = {row[1] for row in source.execute("PRAGMA table_info(history)")}
        wanted = ["generation", "candidate", "score", "lines", "weights", "timestamp",
                  "episode_id", "strategy", "search_depth", "step_ms"]
        selected = [column for column in wanted if column in source_cols]
        rows = source.execute("SELECT " + ",".join(selected) + " FROM history").fetchall()
        inserted = 0
        for index, row in enumerate(rows):
            values = dict(zip(selected, row))
            if not values.get("episode_id"):
                # Legacy snapshots predate episode IDs. Deduplicate their overlapping
                # auto-sync copies by the episode's observable result.
                duplicate = target.execute(
                    "SELECT 1 FROM history WHERE generation=? AND candidate=? AND score=? AND lines=? LIMIT 1",
                    (values.get("generation", 0), values.get("candidate", 1),
                     values.get("score", 0), values.get("lines", 0))).fetchone()
                if duplicate:
                    continue
            episode_id = values.get("episode_id") or f"{source_label}-{index}-{values.get('generation', 0)}"
            cursor = target.execute(
                "INSERT OR IGNORE INTO history "
                "(generation,candidate,score,lines,weights,timestamp,episode_id,strategy,search_depth,step_ms) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (values.get("generation", 0), values.get("candidate", 1), values.get("score", 0),
                 values.get("lines", 0), values.get("weights", "{}"), values.get("timestamp"),
                 episode_id, values.get("strategy", "LEGACY"), values.get("search_depth", 3),
                 values.get("step_ms", 0.0)))
            inserted += cursor.rowcount
        target.commit()
        source.close(); target.close()
        print(f"[persist] merged {inserted}/{len(rows)} history rows from {source_label}")
        return inserted
    except Exception as e:
        print(f"[persist] history merge failed ({source_label}): {e}")
        return 0
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass

def queue_episode_event(event):
    try:
        PENDING_EPISODES.put_nowait(event)
    except Exception:
        pass

def history_event_loop():
    while True:
        event = PENDING_EPISODES.get()
        try:
            if _hf_enabled():
                path = f"episodes/{event['episode_id']}.json"
                payload = json.dumps(event, separators=(',', ':')).encode('utf-8')
                uploaded = False
                for attempt in range(6):
                    if _hf_upload(path, payload):
                        uploaded = True
                        break
                    # A transient Hub/network failure should not lose an episode. The
                    # full DB sync is the backstop, while this queue retries immediately.
                    time.sleep(min(60, 2 ** attempt))
                if not uploaded:
                    PENDING_EPISODES.put(event)
        except Exception as e:
            print(f"[persist] episode sync error: {e}")
            PENDING_EPISODES.put(event)
        finally:
            PENDING_EPISODES.task_done()

def _refresh_remote_history_before_upload():
    """Union the current HF DB before writing so a stale Space cannot erase history.
    This is intentionally merge-only: a smaller remote snapshot never replaces local data."""
    if not _hf_enabled():
        return
    remote_path = _hf_download("ai_evolution.db")
    if not remote_path:
        return
    try:
        with open(remote_path, "rb") as f:
            remote_bytes = f.read()
        # Do not merge a downloaded DB while the training thread is inserting an
        # episode; the lock makes the union atomic from the engine's perspective.
        with ai.control_lock:
            _merge_history_bytes(remote_bytes, "remote-sync")
    except OSError as e:
        print(f"[persist] remote history refresh failed: {e}")

def upload_checkpoint():
    """Persist model, best replay, full DB, and a machine-readable history manifest."""
    try:
        if not os.path.exists(MODEL_FILE):
            return
        _refresh_remote_history_before_upload()
        # Capture model, best replay, and history under one engine lock. Network uploads
        # happen after releasing it, so a slow HF request never pauses training/search.
        with ai.control_lock:
            with open(MODEL_FILE, "rb") as f:
                model_bytes = f.read()
            best_bytes = json.dumps(_snapshot_best_game(), separators=(',', ':')).encode('utf-8')
            history_bytes = _history_db_bytes()
            model_b64 = base64.b64encode(model_bytes).decode("ascii")
    except Exception as e:
        print(f"[persist] checkpoint build failed: {e}")
        return

    manifest = json.dumps(_history_summary(), separators=(',', ':')).encode('utf-8')
    persisted = False
    if _hf_enabled():
        hf_ok = _hf_upload("dqn_model.pth", model_bytes)
        best_sync_ok = _hf_upload("best_game.json", best_bytes)
        history_sync_ok = (not history_bytes) or _hf_upload("ai_evolution.db", history_bytes)
        manifest_sync_ok = _hf_upload("history_manifest.json", manifest)
        health_manifest_ok = False
        # Publish the versioned model only after every core file succeeded, then write
        # the manifest last. A watchdog only trusts a fully restorable checkpoint.
        healthy_generation = _checkpoint_generation(model_bytes)
        if (hf_ok and best_sync_ok and history_sync_ok and manifest_sync_ok
                and healthy_generation >= 0):
            health_model_path = f"health/dqn_model_{healthy_generation}.pth"
            health_best_path = f"health/best_game_{healthy_generation}.json"
            health_model_ok = _hf_upload(health_model_path, model_bytes)
            health_best_ok = _hf_upload(health_best_path, best_bytes)
            if health_model_ok and health_best_ok:
                health_manifest = json.dumps({
                    "generation": healthy_generation,
                    "history_count": _history_summary().get("episodes", 0),
                    "best_score": _snapshot_best_game().get("score", 0),
                    "model_path": health_model_path,
                    "best_path": health_best_path,
                    "history_path": "ai_evolution.db",
                    "updated_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                }, separators=(',', ':')).encode('utf-8')
                health_manifest_ok = _hf_upload("health/manifest.json", health_manifest)
        persisted = hf_ok and best_sync_ok and history_sync_ok and manifest_sync_ok and health_manifest_ok
        print("[persist] HF checkpoint uploaded" if persisted else "[persist] HF upload incomplete")

    if GITHUB_TOKEN:
        github_results = []
        github_results.append(_github_put(
            "dqn_model.pth.b64.json",
            json.dumps({"data": model_b64}, separators=(',', ':')).encode("utf-8"),
            "Auto-sync DQN model checkpoint [24/7]"))
        # Compressed fallbacks keep GitHub useful without hitting the 1 MB Contents API cap.
        github_results.append(_github_put("best_game.json.gz", gzip.compress(best_bytes, compresslevel=6),
                                         "Auto-sync best game [24/7]"))
        if history_bytes:
            github_results.append(_github_put("ai_evolution.db.gz", gzip.compress(history_bytes, compresslevel=6),
                                             "Auto-sync complete AI history [24/7]"))
        github_results.append(_github_put("history_manifest.json", manifest,
                                         "Auto-sync history manifest [24/7]"))
        if all(github_results):
            persisted = True

    return persisted
def _local_model_generation():
    try:
        with open(MODEL_FILE, "rb") as f:
            return _checkpoint_generation(f.read())
    except OSError:
        return -1

def restore_checkpoint():
    """Restore the newest model and union all available history before engine startup."""
    model_bytes = None
    best_json = None
    history_bytes = None

    if _hf_enabled():
        local = _hf_download("dqn_model.pth")
        if local:
            try:
                with open(local, "rb") as f: model_bytes = f.read()
            except OSError: pass
        best_local = _hf_download("best_game.json")
        if best_local:
            try:
                with open(best_local, "rb") as f: best_json = json.loads(f.read().decode('utf-8'))
            except Exception: pass
        history_local = _hf_download("ai_evolution.db")
        if history_local:
            try:
                with open(history_local, "rb") as f: history_bytes = f.read()
            except OSError: pass

    if GITHUB_TOKEN and not _valid_model_blob(model_bytes):
        raw = _github_get_raw("dqn_model.pth.b64.json")
        if raw:
            try: model_bytes = base64.b64decode(json.loads(raw.decode("utf-8"))["data"])
            except Exception: pass
    if not _valid_model_blob(model_bytes):
        healthy_bytes, _ = _download_healthy_model()
        if healthy_bytes:
            model_bytes = healthy_bytes
            print("[persist] using last healthy HF model snapshot")
    if GITHUB_TOKEN and best_json is None:
        raw = _github_get_raw("best_game.json.gz") or _github_get_raw("best_game.json")
        if raw:
            try:
                if raw[:2] == b'\\x1f\\x8b': raw = gzip.decompress(raw)
                best_json = json.loads(raw.decode('utf-8'))
            except Exception: pass
    if GITHUB_TOKEN and history_bytes is None:
        raw = _github_get_raw("ai_evolution.db.gz") or _github_get_raw("ai_evolution.db")
        if raw:
            try: history_bytes = gzip.decompress(raw) if raw[:2] == b'\\x1f\\x8b' else raw
            except Exception: history_bytes = raw

    if history_bytes:
        _merge_history_bytes(history_bytes, "checkpoint")

    if _valid_model_blob(model_bytes) and _checkpoint_generation(model_bytes) >= _local_model_generation():
        try:
            tmp = MODEL_FILE + '.restore.tmp'
            with open(tmp, "wb") as f: f.write(model_bytes)
            os.replace(tmp, MODEL_FILE)
            print(f"[persist] restored model checkpoint ({len(model_bytes)} bytes)")
        except Exception as e:
            print(f"[persist] model restore write failed: {e}")

    if isinstance(best_json, dict) and isinstance(best_json.get("frames"), list):
        try:
            conn = sqlite3.connect(DB_FILE, timeout=10.0)
            current = conn.execute("SELECT score FROM best_game ORDER BY score DESC LIMIT 1").fetchone()
            remote_score = int(best_json.get("score", 0))
            if not current or remote_score > int(current[0]):
                frames = _compact_frame_payload(best_json["frames"])
                conn.execute("DELETE FROM best_game")
                conn.execute("INSERT INTO best_game (score, lines, generation, frames) VALUES (?,?,?,?)",
                             (remote_score, best_json.get("lines", 0), best_json.get("generation", 0),
                              json.dumps(frames, separators=(',', ':'))))
                conn.commit()
                print(f"[persist] restored best game (score {remote_score})")
            conn.close()
        except Exception as e:
            print(f"[persist] best game restore failed: {e}")

def _restore_last_healthy_checkpoint(reason):
    if not _hf_enabled():
        return False
    model_bytes, manifest = _download_healthy_model()
    if not model_bytes or not manifest:
        return False
    try:
        healthy_generation = int(manifest.get("generation", -1))
        history_path = manifest.get("history_path", "ai_evolution.db")
        history_local = _hf_download(history_path)
        history_bytes = None
        if history_local:
            with open(history_local, "rb") as f: history_bytes = f.read()
        best_json = None
        best_path = manifest.get("best_path")
        if best_path:
            best_local = _hf_download(best_path)
            if best_local:
                with open(best_local, "rb") as f: best_json = json.loads(f.read().decode('utf-8'))
        with ai.control_lock:
            if history_bytes:
                _merge_history_bytes(history_bytes, "watchdog")
            tmp = MODEL_FILE + '.healthy.tmp'
            with open(tmp, "wb") as f: f.write(model_bytes)
            os.replace(tmp, MODEL_FILE)
            ai.load_model()
            ai.target_model.load_state_dict(ai.model.state_dict())
            ai.reset_game()
            ai.last_healthy_generation = healthy_generation
            ai.last_healthy_history_count = _history_summary().get("episodes", 0)
            ai.watchdog_restores += 1
            ai.watchdog_status = f"restored:{reason}"
            if isinstance(best_json, dict) and best_json.get("score", 0) > ai.all_time_best_score:
                ai.all_time_best_score = int(best_json.get("score", 0))
                ai.all_time_best_lines = int(best_json.get("lines", 0))
                ai.all_time_best_gen = int(best_json.get("generation", healthy_generation))
                ai.all_time_best_game_memory = _compact_frame_payload(best_json.get("frames", []))
                ai.save_all_time_best(ai.all_time_best_score, ai.all_time_best_lines,
                                      ai.all_time_best_gen, ai.all_time_best_game_memory)
            ai.update_live_state()
        print(f"[watchdog] restored healthy generation {healthy_generation} ({reason})")
        return True
    except Exception as e:
        ai.watchdog_status = f"restore-failed:{str(e)[:80]}"
        print(f"[watchdog] healthy restore failed: {e}")
        return False

def watchdog_check_once():
    """Run one watchdog pass; split out so it can be tested without sleeping."""
    now = time.time()
    summary = _history_summary()
    ai.last_watchdog_at = now
    if not ai.last_healthy_history_count:
        ai.last_healthy_history_count = summary.get("episodes", 0)

    # A remote full DB with more episodes is merged immediately. This also heals a Space
    # that booted from a short snapshot before its first scheduled sync.
    if _hf_enabled():
        remote_manifest = _healthy_manifest()
        remote_count = int((remote_manifest or {}).get("history_count", 0))
        if remote_count > summary.get("episodes", 0) + WATCHDOG_HISTORY_GRACE:
            remote_db = _hf_download((remote_manifest or {}).get("history_path", "ai_evolution.db"))
            if remote_db:
                with open(remote_db, "rb") as f: _merge_history_bytes(f.read(), "watchdog-merge")
                summary = _history_summary()
                ai.last_healthy_history_count = max(ai.last_healthy_history_count, summary.get("episodes", 0))
                ai.watchdog_status = "history-merged"

    if not _hf_enabled():
        # Local development can report a stall, but it cannot restore a remote snapshot.
        ai.watchdog_status = ("stalled-local-only"
                              if now - ai.last_step_completed_at > WATCHDOG_STALL_SECONDS
                              else "local-only")
        return False
    if summary.get("episodes", 0) + WATCHDOG_HISTORY_GRACE < ai.last_healthy_history_count:
        restored = _restore_last_healthy_checkpoint("history-shrank")
        if not restored:
            ai.watchdog_status = "restore-unavailable"
        return restored
    if ai.step_failures >= WATCHDOG_FAILURE_LIMIT:
        restored = _restore_last_healthy_checkpoint("training-errors")
        if not restored:
            ai.watchdog_status = "restore-unavailable"
        return restored
    if now - ai.last_step_completed_at > WATCHDOG_STALL_SECONDS:
        restored = _restore_last_healthy_checkpoint("training-stalled")
        if not restored:
            ai.watchdog_status = "restore-unavailable"
        return restored
    if ai.watchdog_status not in ("history-merged", "sync-failed"):
        ai.watchdog_status = "healthy"
    return False

def watchdog_loop():
    """Detect stalled search and durable-history regressions without interrupting a move."""
    if not _hf_enabled():
        ai.watchdog_status = "local-only"
    while True:
        time.sleep(WATCHDOG_INTERVAL_SECONDS)
        try:
            watchdog_check_once()
        except Exception as e:
            ai.watchdog_status = f"watchdog-error:{str(e)[:80]}"
            print(f"[watchdog] check failed: {e}")

def persistence_loop():
    if not _hf_enabled() and not GITHUB_TOKEN:
        print("Persistence disabled (set HF_TOKEN or GITHUB_TOKEN).")
        return
    print(f"24/7 checkpoint persistence active (sync every {SYNC_INTERVAL_SECONDS}s)")
    while True:
        time.sleep(SYNC_INTERVAL_SECONDS)
        try:
            if upload_checkpoint():
                with ai.control_lock:
                    ai.last_healthy_generation = max(ai.last_healthy_generation, ai.generation)
                    ai.last_healthy_history_count = max(ai.last_healthy_history_count,
                                                        _history_summary().get("episodes", 0))
                    ai.watchdog_status = "healthy"
            else:
                ai.watchdog_status = "sync-failed"
        except Exception as e:
            ai.watchdog_status = "sync-failed"
            print(f"[persist] sync error: {e}")

# --- INITIALIZE ENGINE & BACKGROUND THREADS ---
init_db()
if not BENCHMARK_ONLY:
    restore_checkpoint()
ai = TetrisDQNEngine()
ai.last_healthy_history_count = _history_summary().get("episodes", 0)
ai.update_live_state()

def background_training_loop():
    while True:
        try:
            with ai.control_lock:
                ai.step()
        except Exception as e:
            # Do not advance the successful heartbeat on failure: the watchdog must be
            # able to distinguish a live loop from a loop repeatedly throwing errors.
            ai.step_failures += 1
            ai.last_error = repr(e)
            traceback.print_exc()
        time.sleep(0.01)

if os.environ.get("HDTETRIS_DISABLE_THREADS", "0") != "1":
    threading.Thread(target=background_training_loop, daemon=True, name="hdtetris-training").start()
    threading.Thread(target=persistence_loop, daemon=True, name="hdtetris-checkpoints").start()
    threading.Thread(target=history_event_loop, daemon=True, name="hdtetris-history-events").start()
    threading.Thread(target=watchdog_loop, daemon=True, name="hdtetris-watchdog").start()

# --- FLASK WEB APPLICATION & SSE STREAMING ---
app = Flask(__name__)
BENCHMARK_LOCK = threading.RLock()
BENCHMARK_STATE = {
    "status": "idle", "progress": 0, "total": 0,
    "current_strategy": "", "result": None, "error": ""
}

def _benchmark_job(seeds, max_moves):
    try:
        from benchmark import run_benchmark
        def progress(done, total, strategy):
            with BENCHMARK_LOCK:
                BENCHMARK_STATE.update({"progress": done, "total": total,
                                        "current_strategy": strategy})
        result = run_benchmark(seeds=seeds, max_moves=max_moves, workers=1,
                               progress_callback=progress)
        temp = BENCHMARK_FILE + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)
        # Windows refuses to replace a file while another thread is reading it. Keep
        # the atomic rename and guard both readers/writers with the same lock.
        with BENCHMARK_LOCK:
            os.replace(temp, BENCHMARK_FILE)
            BENCHMARK_STATE.update({"status": result["status"], "progress": result["seeds_per_strategy"] * len(result["strategies"]),
                                    "total": result["seeds_per_strategy"] * len(result["strategies"]),
                                    "current_strategy": "", "result": result, "error": ""})
    except Exception as e:
        with BENCHMARK_LOCK:
            BENCHMARK_STATE.update({"status": "error", "error": repr(e), "current_strategy": ""})
        traceback.print_exc()

def _benchmark_snapshot():
    with BENCHMARK_LOCK:
        snapshot = dict(BENCHMARK_STATE)
        # Only the initial idle state hydrates the last completed file. Running/error
        # states must not resurrect stale results from a previous benchmark.
        if (snapshot.get("status") == "idle" and snapshot.get("result") is None
                and os.path.exists(BENCHMARK_FILE)):
            try:
                with open(BENCHMARK_FILE, "r", encoding="utf-8") as handle:
                    snapshot["result"] = json.load(handle)
                snapshot["status"] = snapshot["result"].get("status", "complete")
            except Exception:
                pass
    return snapshot

def _benchmark_dashboard_html():
    return """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>HDTetris Strategy Benchmark</title><style>
body{margin:0;padding:24px;background:#080911;color:#e0e6ed;font:14px Outfit,Arial,sans-serif}main{max-width:1000px;margin:auto}h1{color:#00f3ff;letter-spacing:3px}.card{background:#101424;border:1px solid #00f3ff;border-radius:10px;padding:16px;margin:12px 0;box-shadow:0 0 20px #00f3ff22}button{background:#00f3ff;border:0;border-radius:6px;padding:12px 18px;font-weight:800;cursor:pointer}button:disabled{opacity:.5}progress{width:100%;height:16px;accent-color:#00f3ff}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:9px;border-bottom:1px solid #26304b}th{color:#7b88a1;font-size:11px;text-transform:uppercase}td{font-family:monospace}.pass{color:#00ff66}.fail{color:#ff007f}.muted{color:#7b88a1;font-size:12px}</style></head><body><main>
<h1>HDTETRIS · STRATEGY LAB</h1><div class='card'><button id='run'>RUN 10,000-SEED GATE</button><p class='muted'>Identical deterministic 7-bag seeds · fast expert-policy probe · 80 pieces per seed · no training side effects.</p><progress id='progress' value='0' max='1'></progress><div id='status' class='muted'>Loading benchmark status…</div></div><div class='card'><table><thead><tr><th>Strategy</th><th>Mean</th><th>Median</th><th>P95</th><th>Max</th><th>Lines</th><th>Top-out</th></tr></thead><tbody id='rows'></tbody></table></div></main><script>
const run=document.getElementById('run'), statusEl=document.getElementById('status'), progress=document.getElementById('progress'), rows=document.getElementById('rows');
function render(s){const r=s.result; const total=s.total||0; progress.max=total||1; progress.value=s.progress||0; run.disabled=s.status==='running'; statusEl.textContent=s.status==='running'?`Running ${s.current_strategy||'strategy'} · ${s.progress||0}/${total}`:(s.error|| (r?`${r.status.toUpperCase()} · ${r.seeds_per_strategy} seeds/strategy · ${r.duration_seconds}s`: 'No benchmark has run yet')); if(!r)return; statusEl.className=r.status==='passed'?'pass':(r.status==='regressed'?'fail':'muted'); rows.innerHTML=r.strategies.map(x=>`<tr><td>${x.strategy}</td><td>${x.mean_score}</td><td>${x.median_score}</td><td>${x.p95_score}</td><td>${x.max_score}</td><td>${x.mean_lines}</td><td>${(x.topout_rate*100).toFixed(1)}%</td></tr>`).join('')}
async function poll(){try{render(await (await fetch('/benchmark/status')).json())}catch(e){statusEl.textContent=e}setTimeout(poll,1500)}
run.onclick=async()=>{await fetch('/benchmark/run?seeds=10000&max_moves=80');poll()};poll();</script></body></html>"""

@app.route('/benchmark')
def benchmark_dashboard():
    return _benchmark_dashboard_html()

@app.route('/benchmark/status')
def benchmark_status():
    return jsonify(_benchmark_snapshot())

@app.route('/benchmark/run', methods=['GET', 'POST'])
def benchmark_run():
    with BENCHMARK_LOCK:
        if BENCHMARK_STATE["status"] == "running":
            return jsonify(_benchmark_snapshot()), 409
        try:
            seeds = max(1, min(10000, int(request.values.get('seeds', 10000))))
            max_moves = max(10, min(500, int(request.values.get('max_moves', 80))))
        except ValueError:
            return jsonify({"error": "seeds and max_moves must be integers"}), 400
        BENCHMARK_STATE.update({"status": "running", "progress": 0,
                                "total": seeds * len(ai.strategy_population), "current_strategy": "starting",
                                "result": None, "error": ""})
        response_state = dict(BENCHMARK_STATE)
    threading.Thread(target=_benchmark_job, args=(seeds, max_moves),
                     daemon=True, name="hdtetris-benchmark").start()
    return jsonify(response_state), 202

@app.route('/')
def index():
    return render_template_string("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>HDTetris</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;800&display=swap" rel="stylesheet">
        <style>
            * { box-sizing: border-box; }
            body { 
                background: #080911; 
                color: #e0e6ed; 
                font-family: 'Outfit', sans-serif; 
                display: flex; 
                flex-direction: column; 
                align-items: center; 
                margin: 0; 
                padding: 15px; 
                min-height: 100vh;
            }
            h1 {
                margin: 0 0 15px 0;
                font-size: 22px;
                letter-spacing: 3px;
                color: #00f3ff;
                text-shadow: 0 0 15px rgba(0, 243, 255, 0.6);
                font-weight: 800;
            }
            .hud-container {
                display: flex;
                gap: 12px;
                width: 320px;
                margin-bottom: 12px;
            }
            .panel {
                background: #101424;
                border: 1px solid #00f3ff;
                border-radius: 8px;
                padding: 10px;
                position: relative;
                box-shadow: 0 0 15px rgba(0, 243, 255, 0.25);
            }
            .panel-score { flex: 1; text-align: left; }
            .panel-next { width: 90px; display: flex; flex-direction: column; align-items: center; justify-content: center; }
            .label {
                color: #7b88a1;
                font-size: 10px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            .value {
                color: #00f3ff;
                font-size: 24px;
                font-weight: 800;
                margin-top: 4px;
                font-family: monospace;
                text-shadow: 0 0 10px rgba(0, 243, 255, 0.5);
            }
            .sub-value {
                color: #ff007f;
                font-size: 11px;
                margin-top: 2px;
                font-weight: 700;
            }
            #game-container {
                border: 2px solid #00f3ff;
                border-radius: 8px;
                background: #090a14;
                width: 300px;
                height: 600px;
                position: relative;
                box-shadow: 0 0 30px rgba(0, 243, 255, 0.35);
                overflow: hidden;
            }
            canvas { display: block; }
            #tetris {
                background-image: linear-gradient(#15192d 1px, transparent 1px), linear-gradient(90deg, #15192d 1px, transparent 1px);
                background-size: 30px 30px;
            }
            .mode-toggle {
                margin-top: 15px;
                display: flex;
                gap: 8px;
                width: 320px;
            }
            .btn {
                flex: 1;
                background: #15192d;
                border: 1px solid #2a3454;
                color: #e0e6ed;
                padding: 10px 8px;
                border-radius: 6px;
                cursor: pointer;
                font-size: 11px;
                font-weight: 700;
                text-transform: uppercase;
                transition: all 0.2s ease;
            }
            .btn:hover { background: #222b4a; border-color: #00f3ff; }
            .btn.active {
                background: #00f3ff;
                color: #080911;
                border-color: #00f3ff;
                box-shadow: 0 0 15px rgba(0, 243, 255, 0.6);
            }
            .sim-controls {
                margin-top: 10px;
                display: none;
                width: 320px;
                background: #101424;
                border: 1px solid #00f3ff;
                border-radius: 8px;
                padding: 10px;
            }
            .sim-slider-row {
                display: flex;
                align-items: center;
                gap: 10px;
                margin-bottom: 8px;
            }
            .sim-slider-row input[type="range"] {
                flex: 1;
                accent-color: #00f3ff;
            }
            .sim-btn-group {
                display: flex;
                gap: 6px;
            }
            .sim-btn-group .btn {
                padding: 6px 4px;
                font-size: 10px;
            }
            .telemetry-bar {
                margin-top: 12px;
                display: flex;
                justify-content: space-between;
                width: 320px;
                font-size: 11px;
                color: #7b88a1;
            }
            .modal {
                display: none;
                position: fixed;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                width: 92%;
                max-width: 440px;
                height: 85vh;
                background: #0d101e;
                border: 2px solid #00f3ff;
                border-radius: 12px;
                padding: 16px;
                z-index: 2000;
                box-shadow: 0 0 60px rgba(0, 243, 255, 0.4);
            }
            .modal-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 12px;
            }
            .modal-title { font-weight: 800; color: #fff; font-size: 16px; }
            .close-btn { color: #ff007f; cursor: pointer; font-weight: bold; font-size: 24px; }
            #history-scroll { height: calc(100% - 250px); overflow-y: auto; margin-top: 10px; border-top: 1px solid #2a3454; }
            .history-item { display: flex; justify-content: space-between; padding: 8px; border-bottom: 1px solid #1a2238; font-size: 12px; }
            #chart-container { width: 100%; height: 180px; background: #101424; border-radius: 8px; margin-top: 8px; padding: 5px; }

            /* CSS Screen Shake Keyframes */
            @keyframes screenShake {
                0% { transform: translate(0, 0) rotate(0); }
                20% { transform: translate(-4px, 4px) rotate(-0.6deg); }
                40% { transform: translate(4px, -4px) rotate(0.6deg); }
                60% { transform: translate(-3px, -2px) rotate(-0.35deg); }
                80% { transform: translate(3px, 2px) rotate(0.35deg); }
                100% { transform: translate(0, 0) rotate(0); }
            }
            .shake { animation: screenShake 0.28s ease-in-out; }
            .shake-heavy { animation-duration: 0.42s; }
            .sim-speed-note { color:#7b88a1; font-size:9px; letter-spacing:.6px; text-align:center; margin-top:7px; }

            /* --- RESPONSIVE LAYOUT: vertical on mobile, horizontal on desktop --- */
            .app {
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 14px;
                width: 100%;
                max-width: 1080px;
            }
            .board-col {
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 10px;
            }
            .side-col {
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 12px;
                width: 100%;
                max-width: 340px;
            }
            .hud-container { width: 100%; margin-bottom: 0; }
            .mode-toggle { width: 100%; margin-top: 0; }
            .sim-controls { width: 100%; margin-top: 0; }
            .telemetry-bar { width: 300px; margin-top: 0; }
            #player-controls { width: 100%; }
            #player-controls .btn-row { display: flex; gap: 8px; margin-bottom: 8px; }
            #player-controls .btn-row:last-child { margin-bottom: 0; }

            #game-container { flex: 0 0 auto; }

            #pause-overlay, #gameover-overlay {
                display: none;
                position: absolute;
                inset: 0;
                background: rgba(8, 9, 17, 0.72);
                align-items: center;
                justify-content: center;
                flex-direction: column;
                gap: 10px;
                z-index: 10;
            }
            #pause-overlay.show, #gameover-overlay.show { display: flex; }
            .gameover-score {
                font-size: 20px;
                font-weight: 800;
                color: #00f3ff;
                letter-spacing: 2px;
            }
            .gameover-best {
                font-size: 13px;
                font-weight: 800;
                color: #ffea00;
                letter-spacing: 2px;
            }
            .pause-icon {
                font-size: 56px;
                color: #00f3ff;
                text-shadow: 0 0 20px rgba(0, 243, 255, 0.9);
                letter-spacing: 6px;
                line-height: 1;
                font-weight: 800;
            }
            .pause-label {
                font-size: 13px;
                letter-spacing: 4px;
                font-weight: 800;
                color: #7b88a1;
            }
            .pause-hint {
                font-size: 10px;
                letter-spacing: 2px;
                color: #7b88a1;
                opacity: 0.8;
            }

            #toast {
                position: fixed;
                top: 18px;
                left: 50%;
                transform: translateX(-50%);
                background: rgba(16, 20, 36, 0.95);
                border: 1px solid #00f3ff;
                color: #00f3ff;
                padding: 8px 18px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: 800;
                letter-spacing: 2px;
                opacity: 0;
                pointer-events: none;
                transition: opacity 0.25s ease;
                z-index: 3000;
            }
            #toast.show { opacity: 1; }

            .btn { touch-action: manipulation; user-select: none; }
            .btn:active { transform: scale(0.97); }

            /* Desktop / horizontal: board left, HUD + controls right */
            @media (min-width: 880px) {
                .app { flex-direction: row; align-items: flex-start; justify-content: center; }
                .side-col { max-width: 320px; }
            }
            /* Bigger touch targets on small phones */
            @media (max-width: 420px) {
                .btn { min-height: 44px; font-size: 10px; }
            }
        </style>
    </head>
    <body>
        <h1>HDTetris</h1>
        <div id="toast"></div>
        
        <div class="app">
            <div class="board-col">
                <div id="game-container">
                    <canvas id="tetris" width="300" height="600"></canvas>
                    <div id="pause-overlay">
                        <span class="pause-icon">❚❚</span>
                        <span class="pause-label">PAUSED</span>
                        <span class="pause-hint">SPACE / SHIFT TO RESUME</span>
                    </div>
                    <div id="gameover-overlay">
                        <span class="pause-icon" style="color:#ff007f; text-shadow:0 0 20px rgba(255,0,127,0.9);">GAME OVER</span>
                        <span class="gameover-score">SCORE <strong id="gameover-score-val">0</strong></span>
                        <span class="gameover-best">BEST <strong id="gameover-best-val">0</strong></span>
                        <button id="gameover-restart" class="btn" style="margin-top:8px;">▶ PLAY AGAIN</button>
                        <span class="pause-hint">PRESS ENTER OR CLICK TO RESTART</span>
                    </div>
                </div>
                <div class="telemetry-bar">
                    <span>GEN (DQN): <strong id="gen-num" style="color:#00f3ff">0</strong></span>
                    <span>EPSILON: <strong id="cand-num" style="color:#ff007f">1.0</strong></span>
                    <span>HIGH: <strong id="high-score" style="color:#00f3ff">0</strong></span>
                </div>
            </div>
            <div class="side-col">
                <div class="hud-container">
                    <div class="panel panel-score">
                        <div class="label">Score / Lines</div>
                        <div class="value" id="score">0</div>
                        <div class="sub-value">LINES: <span id="lines-count" style="color:#00f3ff">0</span></div>
                    </div>
                    <div class="panel panel-next">
                        <div class="label">Next</div>
                        <canvas id="next-canvas" width="40" height="40" style="margin-top:6px"></canvas>
                    </div>
                </div>
                <div class="mode-toggle">
                    <button id="real-btn" class="btn active">Real Time</button>
                    <button id="sim-btn" class="btn">Simulation</button>
                    <button id="play-btn" class="btn">Play</button>
                    <button id="audio-btn" class="btn" style="background:#15192d;">🔊 Audio</button>
                    <button id="hist-btn" class="btn" style="background:#20283e;">Logs</button>
                </div>
                <div id="sim-controls" class="sim-controls">
                    <div class="sim-slider-row">
                        <button id="sim-step-back" class="btn" title="Step back one placement" style="flex:0 0 34px;">⏮</button>
                        <button id="sim-play-toggle" class="btn" style="flex:0 0 60px;">PAUSE</button>
                        <button id="sim-step-fwd" class="btn" title="Step forward one placement" style="flex:0 0 34px;">⏭</button>
                        <input type="range" id="sim-scrubber" min="0" max="100" value="0">
                        <span id="sim-frame-counter" style="font-size:10px; font-family:monospace;">0/0</span>
                    </div>
                    <div class="sim-btn-group">
                        <button class="btn sim-speed-btn active" data-speed="1">1x</button>
                        <button class="btn sim-speed-btn" data-speed="2">2x</button>
                        <button class="btn sim-speed-btn" data-speed="5">5x</button>
                        <button class="btn sim-speed-btn" data-speed="10">10x</button>
                        <button class="btn sim-speed-btn" data-speed="20">20x</button>
                    </div>
                    <div class="sim-speed-note">1x HUMAN PACE · 20x REALTIME</div>
                </div>
                <div id="player-controls" style="display: none;">
                    <div class="btn-row">
                        <button class="btn" style="flex:1; font-size:16px" onclick="playerInput('ArrowLeft')">◀</button>
                        <button class="btn" style="flex:1" onclick="playerInput('ArrowUp')">↻ ROTATE</button>
                        <button class="btn" style="flex:1; font-size:16px" onclick="playerInput('ArrowRight')">▶</button>
                    </div>
                    <div class="btn-row">
                        <button class="btn" style="flex:2" onclick="playerInput('ArrowDown')">▼ DROP</button>
                        <button class="btn" style="flex:1; background:#d32f2f;" onclick="playerInput('Shift')">PAUSE</button>
                        <button class="btn" style="flex:1; background:#2a3454;" onclick="playerInput('NewGame')">NEW</button>
                    </div>
                </div>
            </div>
        </div>

        <div id="history-box" class="modal">
            <div class="modal-header">
                <span class="modal-title" id="history-title">HDTetris · AI TRAINING LOGS</span>
                <button id="history-source-btn" class="btn" style="flex:0 0 auto; width:auto; padding:6px 10px; font-size:10px;">HUMAN LOGS</button>
                <span class="close-btn" onclick="toggleHistory()">×</span>
            </div>
            <div style="font-size:12px; color:#7b88a1;">ALL-TIME BEST: <strong id="best-score-modal" style="color:#00f3ff">0 PTS</strong> <span id="history-total" style="float:right"></span></div>
            <div id="chart-container"><canvas id="evoChart"></canvas></div>
            <div id="history-scroll"><div id="history-content"></div></div>
        </div>

        <script>
            const canvas = document.getElementById('tetris');
            const ctx = canvas.getContext('2d');
            const nCanvas = document.getElementById('next-canvas');
            const nctx = nCanvas.getContext('2d');

            let viewMode = 'real';
            let simFrames = [];
            let simIndex = 0;
            let simPlaying = true;
            let simSpeed = 1;
            // Smooth playback: each placement animates a piece drop over this many ms
            // at 1x. Higher speeds shorten it; 20x is a smooth realtime blur.
            const SIM_ANIM_MS = 500;
            let simAnimId = null;
            let simAnimStart = 0;
            let simPrevGrid = null;
            let simFalling = [];
            // Per-move scrubbing: simStepMode stops playback after one placement so
            // the user can step forward/backward one move at a time with the falling
            // animation (forward = drop in, backward = reverse lift out).
            let simStepMode = false;
            let simReverseCells = [];
            let simReverseToGrid = null;
            let simReverseTargetIdx = 0;
            let simReverseStart = 0;
            let lastEffectKey = '';
            let chart = null;

            // --- WEB AUDIO RETRO SYNTHWAVE SYNTHESIZER ---
            let audioCtx = null;
            let audioEnabled = true;

            function initAudio() {
                if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                if (audioCtx && audioCtx.state === 'suspended') {
                    try { audioCtx.resume(); } catch(e) {}
                }
            }

            // Browsers block AudioContext until a user gesture, so unlock it on the
            // very first interaction instead of waiting for the first sound.
            function unlockAudio() {
                initAudio();
                window.removeEventListener('pointerdown', unlockAudio);
                window.removeEventListener('keydown', unlockAudio);
            }
            window.addEventListener('pointerdown', unlockAudio);
            window.addEventListener('keydown', unlockAudio);

            function playSynthSound(freq, duration, type='square', fadeOut=true) {
                if (!audioEnabled) return;
                try {
                    initAudio();
                    const osc = audioCtx.createOscillator();
                    const gain = audioCtx.createGain();
                    osc.type = type;
                    osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
                    gain.gain.setValueAtTime(0.12, audioCtx.currentTime);
                    if (fadeOut) gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + duration);
                    osc.connect(gain);
                    gain.connect(audioCtx.destination);
                    osc.start();
                    osc.stop(audioCtx.currentTime + duration);
                } catch(e) {}
            }

            function triggerDropSound() { playSynthSound(220, 0.05, 'triangle'); }
            function triggerLineClearSound() { 
                playSynthSound(440, 0.1, 'square'); 
                setTimeout(() => playSynthSound(880, 0.15, 'sine'), 80);
            }
            function triggerTetrisSound() {
                [523.25, 659.25, 783.99, 1046.50].forEach((f, i) => {
                    setTimeout(() => playSynthSound(f, 0.12, 'square'), i * 60);
                });
            }

            document.getElementById('audio-btn').onclick = () => {
                audioEnabled = !audioEnabled;
                document.getElementById('audio-btn').innerText = audioEnabled ? '🔊 Audio' : '🔇 Muted';
                document.getElementById('audio-btn').style.borderColor = audioEnabled ? '#00f3ff' : '#555';
            };

            // --- CANVAS PARTICLE SYSTEM & SCREEN SHAKE ---
            let particles = [];

            const MAX_PARTICLES = 220;

            function spawnParticles(rows) {
                const targetRows = Array.isArray(rows) ? rows : [rows];
                const perRow = Math.max(8, Math.floor(24 / Math.max(1, targetRows.length)));
                for (const row of targetRows) {
                    if (particles.length >= MAX_PARTICLES) break;
                    const safeRow = Math.max(0, Math.min(19, Number(row) || 0));
                    for (let i = 0; i < perRow && particles.length < MAX_PARTICLES; i++) {
                        particles.push({
                            x: Math.random() * 300,
                            y: safeRow * 30 + 15 + (Math.random() - 0.5) * 12,
                            vx: (Math.random() - 0.5) * 5.5,
                            vy: (Math.random() - 0.8) * 4.5,
                            color: ['#00f3ff', '#ff007f', '#00ff66', '#ffea00'][Math.floor(Math.random() * 4)],
                            life: 1.0
                        });
                    }
                }
            }

            function updateAndDrawParticles() {
                if (particles.length === 0) return;
                for (let i = particles.length - 1; i >= 0; i--) {
                    const p = particles[i];
                    p.x += p.vx;
                    p.y += p.vy;
                    p.vy += 0.08;
                    p.life -= 0.055;
                    if (p.life <= 0) {
                        particles.splice(i, 1);
                        continue;
                    }
                    ctx.globalAlpha = p.life;
                    ctx.fillStyle = p.color;
                    ctx.fillRect(p.x, p.y, 3, 3);
                }
                ctx.globalAlpha = 1;
            }

            function triggerScreenShake(clears=1) {
                const container = document.getElementById('game-container');
                container.classList.remove('shake', 'shake-heavy');
                void container.offsetWidth;
                container.classList.add(clears >= 4 ? 'shake-heavy' : 'shake');
            }

            function triggerLineEffects(data, effectKey) {
                if (!data || !data.clears || data.clears < 1 || effectKey === lastEffectKey) return;
                lastEffectKey = effectKey;
                const rows = Array.isArray(data.clear_rows) && data.clear_rows.length
                    ? data.clear_rows : [19];
                spawnParticles(rows);
                triggerScreenShake(data.clears);
                if (data.clears >= 4) triggerTetrisSound();
                else triggerLineClearSound();
            }

            // --- PLAYER CONTROL STATE ---
            const JS_SHAPES = [[[1,1,1,1]], [[1,1],[1,1]], [[0,1,0],[1,1,1]], [[0,1,1],[1,1,0]], [[1,1,0],[0,1,1]], [[1,0,0],[1,1,1]], [[0,0,1],[1,1,1]]];
            const JS_COLORS = ["0,243,255", "255,234,0", "157,0,255", "0,255,102", "255,0,127", "0,102,255", "255,128,0"];
            function decodePackedGrid(rows) {
                return (rows || []).map(row => [...row].map(ch => {
                    if (ch === '0') return [0,0,0];
                    const rgb = (JS_COLORS[parseInt(ch, 10) - 1] || '0,243,255').split(',');
                    return rgb.map(Number);
                }));
            }
            let pGrid, pPiece, pNext, pScore, pLines, pPaused, pGameOver;
            let playerLoopId = null;
            let playerLastDrop = 0;
            const PLAYER_GRAVITY_MS = 450;
            const PLAYER_SAVE_KEY = 'HDTetris_play_save';
            const HUMAN_LOG_KEY = 'HDTetris_human_log';
            const HUMAN_BEST_KEY = 'HDTetris_human_best';

            function loadHumanLog() {
                try { return JSON.parse(localStorage.getItem(HUMAN_LOG_KEY)) || []; } catch(e) { return []; }
            }

            function saveHumanLog(log) {
                try { localStorage.setItem(HUMAN_LOG_KEY, JSON.stringify(log.slice(-200))); } catch(e) {}
            }

            function getHumanBest() {
                try { return Number(localStorage.getItem(HUMAN_BEST_KEY)) || 0; } catch(e) { return 0; }
            }

            function setHumanBest(v) {
                try { localStorage.setItem(HUMAN_BEST_KEY, String(v)); } catch(e) {}
            }

            function recordHumanGame(score, lines) {
                const log = loadHumanLog();
                log.push({ ts: Date.now(), score: score, lines: lines });
                saveHumanLog(log);
                if (score > getHumanBest()) setHumanBest(score);
            }

            function savePlayerState() {
                if (viewMode !== 'play' || !pGrid) return;
                try {
                    localStorage.setItem(PLAYER_SAVE_KEY, JSON.stringify({
                        grid: pGrid, score: pScore, lines: pLines,
                        piece: pPiece, next: pNext, savedAt: Date.now()
                    }));
                } catch(e) {}
            }

            function restorePlayerState() {
                try {
                    const raw = localStorage.getItem(PLAYER_SAVE_KEY);
                    if (!raw) return false;
                    const s = JSON.parse(raw);
                    if (!s || !s.grid || s.grid.length !== 20) return false;
                    // Reject a broken/lost save: a topped-out board (cells in the top
                    // two rows) can never spawn a piece, so it would just instantly
                    // game-over again. Discard it and start fresh.
                    for (let r = 0; r < 2; r++) {
                        for (let c = 0; c < 10; c++) {
                            const cell = s.grid[r][c];
                            if (cell && (cell[0] + cell[1] + cell[2] > 0)) return false;
                        }
                    }
                    pGrid = s.grid;
                    pScore = s.score || 0;
                    pLines = s.lines || 0;
                    pPiece = s.piece || null;
                    pNext = s.next || null;
                    pPaused = false;
                    return true;
                } catch(e) { return false; }
            }

            function clearPlayerSave() {
                try { localStorage.removeItem(PLAYER_SAVE_KEY); } catch(e) {}
            }

            let toastTimer = null;
            function showToast(text) {
                const t = document.getElementById('toast');
                t.textContent = text;
                t.classList.add('show');
                clearTimeout(toastTimer);
                toastTimer = setTimeout(() => t.classList.remove('show'), 1600);
            }

            function stopPlayerLoop() {
                if (playerLoopId) { clearInterval(playerLoopId); playerLoopId = null; }
            }

            function startPlayerLoop() {
                stopPlayerLoop();
                playerLastDrop = performance.now();
                playerLoopId = setInterval(playerTick, 33);
            }

            function playerTick() {
                if (viewMode !== 'play' || !pPiece) return;
                if (!pPaused) {
                    const now = performance.now();
                    if (now - playerLastDrop >= PLAYER_GRAVITY_MS) {
                        playerLastDrop = now;
                        playerDrop();
                    }
                }
                renderPlayer();
            }

            function resetPlayer() {
                pPaused = false;
                pGameOver = false;
                const ov = document.getElementById('pause-overlay');
                if (ov) ov.classList.remove('show');
                hidePlayerGameOver();
                if (restorePlayerState()) {
                    if (!pPiece) pPiece = randomPiece();
                    // A restored board that can't even spawn the next piece is a
                    // broken/lost save — drop it and start a fresh game instead of
                    // trapping the player in an instant game-over loop.
                    if (checkCollision(pPiece)) {
                        clearPlayerSave();
                        pGrid = Array.from({length: 20}, () => Array.from({length: 10}, () => [0,0,0]));
                        pScore = 0; pLines = 0;
                        pNext = randomPiece();
                        spawnPlayerPiece();
                        showToast('FRESH GAME');
                        return;
                    }
                    showToast('GAME RESTORED');
                    renderPlayer();
                    return;
                }
                pGrid = Array.from({length: 20}, () => Array.from({length: 10}, () => [0,0,0]));
                pScore = 0; pLines = 0;
                pNext = randomPiece();
                spawnPlayerPiece();
            }

            function randomPiece() {
                const idx = Math.floor(Math.random() * JS_SHAPES.length);
                return { shape: JS_SHAPES[idx], color: `rgb(${JS_COLORS[idx]})`, colorArr: JS_COLORS[idx].split(',').map(Number), x: 3, y: 0 };
            }

            function spawnPlayerPiece() {
                pPiece = pNext;
                pNext = randomPiece();
                if (checkCollision(pPiece)) {
                    const finalScore = pScore;
                    pPiece = null;
                    pPaused = true;
                    pGameOver = true;
                    clearPlayerSave();
                    recordHumanGame(finalScore, pLines);
                    renderPlayer();
                    showPlayerGameOver(finalScore);
                }
            }

            function showPlayerGameOver(score) {
                document.getElementById('gameover-score-val').innerText = score;
                document.getElementById('gameover-best-val').innerText = getHumanBest();
                const ov = document.getElementById('gameover-overlay');
                if (ov) ov.classList.add('show');
            }

            function hidePlayerGameOver() {
                const ov = document.getElementById('gameover-overlay');
                if (ov) ov.classList.remove('show');
            }

            function checkCollision(p, offsetX=0, offsetY=0, shape=null) {
                const s = shape || p.shape;
                for(let i=0; i<s.length; i++) {
                    for(let j=0; j<s[i].length; j++) {
                        if(s[i][j]) {
                            const nx = p.x + j + offsetX;
                            const ny = p.y + i + offsetY;
                            if(nx < 0 || nx >= 10 || ny >= 20) return true;
                            if(ny >= 0 && (pGrid[ny][nx][0] + pGrid[ny][nx][1] + pGrid[ny][nx][2] > 0)) return true;
                        }
                    }
                }
                return false;
            }

            function playerDrop() {
                if (!pPiece) return;
                if (checkCollision(pPiece, 0, 1)) {
                    placePlayerPiece();
                } else {
                    pPiece.y++;
                    triggerDropSound();
                }
            }

            function placePlayerPiece() {
                pPiece.shape.forEach((row, i) => {
                    row.forEach((cell, j) => {
                        if(cell && pPiece.y + i >= 0) {
                            pGrid[pPiece.y + i][pPiece.x + j] = [...pPiece.colorArr];
                        }
                    });
                });

                pScore += 10;
                let clears = 0;
                const clearRows = [];
                for(let y = 19; y >= 0; y--) {
                    if(pGrid[y].every(c => c[0] + c[1] + c[2] > 0)) {
                        clearRows.push(y);
                        pGrid.splice(y, 1);
                        pGrid.unshift(Array.from({length: 10}, () => [0,0,0]));
                        clears++;
                        y++;
                    }
                }
                if (clears > 0) {
                    pLines += clears;
                    pScore += [0, 100, 300, 500, 800][clears] || 0;
                    spawnParticles(clearRows);
                    triggerScreenShake(clears);
                    if (clears >= 4) triggerTetrisSound(); else triggerLineClearSound();
                }
                spawnPlayerPiece();
                savePlayerState();
            }

            function setPlayerPaused(paused) {
                pPaused = paused;
                const overlay = document.getElementById('pause-overlay');
                if (overlay) overlay.classList.toggle('show', pPaused);
                renderPlayer();
            }

            function playerInput(key) {
                if (viewMode !== 'play') return;
                // Restart is always allowed — including right after a game over when
                // pPiece is null (the old guard here froze the game after losing).
                if (key === 'NewGame' || key === 'Enter') {
                    clearPlayerSave();
                    resetPlayer();
                    showToast('NEW GAME');
                    return;
                }
                if (!pPiece || pGameOver) return;
                if (key === 'Shift' || key === ' ' || key === 'Space') {
                    setPlayerPaused(!pPaused);
                    savePlayerState();
                    return;
                }
                if (pPaused) return;
                if (key === 'ArrowLeft' && !checkCollision(pPiece, -1, 0)) pPiece.x--;
                if (key === 'ArrowRight' && !checkCollision(pPiece, 1, 0)) pPiece.x++;
                if (key === 'ArrowDown') playerDrop();
                if (key === 'ArrowUp') {
                    const rot = pPiece.shape[0].map((val, idx) => pPiece.shape.map(row => row[idx]).reverse());
                    if (!checkCollision(pPiece, 0, 0, rot)) pPiece.shape = rot;
                }
                savePlayerState();
                renderPlayer();
            }

            document.getElementById('gameover-restart').onclick = () => playerInput('NewGame');

            window.addEventListener('keydown', (e) => {
                if (viewMode === 'play' && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Shift', ' ', 'Space', 'Enter'].includes(e.key)) {
                    e.preventDefault();
                    playerInput(e.key);
                }
            });

            window.addEventListener('pagehide', () => { if (viewMode === 'play') savePlayerState(); });

            function renderPlayer() {
                render({
                    grid: pGrid,
                    piece: pPiece,
                    next: pNext ? pNext.shape : null,
                    next_color: pNext ? pNext.color : null,
                    score: pScore,
                    lines: pLines,
                    gen: 'HUMAN',
                    cand: '1.0'
                });
            }

            // --- SSE LIVE STREAMING REAL-TIME ENGINE ---
            let evtSource = null;

            // Real-time falling re-enactment: SSE only sends final placed boards, so
            // we diff each frame against the previous one and animate the newly added
            // cells dropping in from above. This gives the live AI a smooth falling
            // motion without needing intermediate positions on the wire.
            let rtPrevGrid = null;
            let rtFalling = [];
            let rtAnimId = null;
            let rtAnimStart = 0;
            const RT_ANIM_MS = 150;

            function rtAnimTick(now) {
                if (viewMode !== 'real') { rtAnimId = null; return; }
                const t = Math.min(1, (now - rtAnimStart) / RT_ANIM_MS);
                const ease = 1 - Math.pow(1 - t, 2.5);
                drawGridToCanvas(rtPrevGrid || []);
                if (rtFalling.length) {
                    const minY = Math.min(...rtFalling.map(f => f.targetY));
                    const offset = ease * minY;
                    for (const f of rtFalling) {
                        drawBlock(ctx, f.x, Math.round(f.targetY - minY + offset), f.color);
                    }
                }
                updateAndDrawParticles();
                if (t >= 1) {
                    rtAnimId = null;
                    rtFalling = [];
                    // Snap to the real final board once the drop completes.
                    if (rtPendingGrid) {
                        drawGridToCanvas(rtPendingGrid);
                        rtPrevGrid = rtPendingGrid;
                    }
                } else {
                    rtAnimId = requestAnimationFrame(rtAnimTick);
                }
            }

            let rtPendingGrid = null;

            function renderRealtime(data) {
                if (!data) return;
                const grid = data.grid || decodePackedGrid(data.grid_packed);
                if (!grid || !grid.length) return;
                if (data.event_id) triggerLineEffects(data, data.event_id);
                updateHUD(data);

                const hasClear = (data.clears || 0) > 0;

                if (rtAnimId) {
                    // A drop is mid-flight; remember the newest board and draw it
                    // once the current animation finishes.
                    rtPendingGrid = cloneGrid(grid);
                    return;
                }

                if (!hasClear && rtPrevGrid && rtPrevGrid.length === grid.length) {
                    // Find cells that just appeared (the newly placed piece).
                    rtFalling = [];
                    for (let y = 0; y < grid.length; y++) {
                        for (let x = 0; x < grid[y].length; x++) {
                            const c = grid[y][x];
                            const p = rtPrevGrid[y][x];
                            if ((c[0] + c[1] + c[2] > 0) && (p[0] + p[1] + p[2] === 0)) {
                                rtFalling.push({ x, targetY: y, color: `rgb(${c[0]},${c[1]},${c[2]})` });
                            }
                        }
                    }
                    if (rtFalling.length) {
                        rtPendingGrid = cloneGrid(grid);
                        rtAnimStart = performance.now();
                        rtAnimId = requestAnimationFrame(rtAnimTick);
                        return;
                    }
                }

                // No drop to animate (first frame or a line clear): draw directly.
                rtPrevGrid = cloneGrid(grid);
                drawGridToCanvas(grid);
                drawPieceToCanvas(data.piece);
                updateAndDrawParticles();
            }

            function initSSEStream() {
                if (evtSource) evtSource.close();
                evtSource = new EventSource('/stream');
                evtSource.onmessage = function(e) {
                    if (viewMode === 'real') {
                        try {
                            const data = JSON.parse(e.data);
                            renderRealtime(data);
                        } catch(err) {}
                    }
                };
            }
            initSSEStream();

            // --- FAST COMPRESSED SIMULATION REPLAY ENGINE ---
            async function loadSimulationData() {
                ctx.clearRect(0,0,300,600);
                ctx.fillStyle = "#00f3ff";
                ctx.font = "800 16px Outfit, sans-serif";
                ctx.textAlign = "center";
                ctx.fillText("LOADING REPLAY...", 150, 300);

                try {
                    const res = await fetch('/best_game');
                    simFrames = await res.json();
                    simIndex = 0;
                    simPlaying = true;
                    simSpeed = 1;
                    simPrevGrid = null;
                    simFalling = [];
                    stopSimAnim();
                    document.querySelectorAll('.sim-speed-btn').forEach(b => b.classList.toggle('active', b.dataset.speed === '1'));
                    if (simFrames && simFrames.length > 0) {
                        document.getElementById('sim-scrubber').max = simFrames.length - 1;
                        runSimStep();
                    } else {
                        ctx.clearRect(0,0,300,600);
                        ctx.fillText("NO BEST GAME YET", 150, 300);
                    }
                } catch(e) {
                    console.error(e);
                }
            }

            // --- SMOOTH SIMULATION PLAYBACK ---
            // Frames are per-placement board snapshots, so instead of a choppy 2fps
            // slideshow each newly placed block is animated dropping from the top of
            // the board into place with an eased curve. 1x plays a ~500ms human-paced
            // drop per piece; higher speeds shorten it until 20x is a realtime blur.
            function frameGrid(frame) {
                if (!frame) return null;
                if (frame.grid) return frame.grid;
                if (frame.grid_packed) return decodePackedGrid(frame.grid_packed);
                return null;
            }

            function cloneGrid(grid) {
                return grid.map(row => row.map(c => [c[0], c[1], c[2]]));
            }

            function updateSimFrameCounter() {
                // simIndex always points one past the displayed frame (the next target),
                // so the counter shows the frame currently on screen (1-based).
                const shown = Math.max(0, simIndex - 1);
                document.getElementById('sim-scrubber').value = shown;
                document.getElementById('sim-frame-counter').innerText = `${shown + 1}/${simFrames.length}`;
            }

            function stopSimAnim() {
                if (simAnimId) { cancelAnimationFrame(simAnimId); simAnimId = null; }
            }

            // A replay frame can skip several placements (the archive is strided to
            // stay small), and line clears shift cells down. Only animate a drop when
            // the diff is exactly one clean 4-cell tetromino; anything else snaps to
            // the frame instantly so we never render glitched block clusters.
            function isCleanTetromino(cells) {
                if (cells.length !== 4) return false;
                const set = new Set(cells.map(c => c.x + ',' + c.targetY));
                for (const c of cells) {
                    let adj = 0;
                    if (set.has((c.x + 1) + ',' + c.targetY)) adj++;
                    if (set.has((c.x - 1) + ',' + c.targetY)) adj++;
                    if (set.has(c.x + ',' + (c.targetY + 1))) adj++;
                    if (set.has(c.x + ',' + (c.targetY - 1))) adj++;
                    if (adj === 0) return false;
                }
                return true;
            }

            function snapSimTo(frame, nextGrid) {
                simPrevGrid = cloneGrid(nextGrid);
                drawGridToCanvas(nextGrid);
                updateAndDrawParticles();
                simIndex = (simIndex + 1) % simFrames.length;
                updateSimFrameCounter();
                simScheduleNext();
            }

            // Continue playback, or stop after exactly one placement when the user is
            // stepping through the replay one move at a time.
            function simScheduleNext() {
                if (simStepMode) {
                    simStepMode = false;
                    simPlaying = false;
                    updateSimPlayToggle();
                    return;
                }
                if (simPlaying) {
                    simAnimId = requestAnimationFrame(advanceSim);
                }
            }

            function updateSimPlayToggle() {
                document.getElementById('sim-play-toggle').innerText = simPlaying ? 'PAUSE' : 'PLAY';
            }

            function advanceSim() {
                if (viewMode !== 'sim' || !simPlaying) return;
                if (!simFrames || simFrames.length === 0) return;
                const frame = simFrames[simIndex];
                const nextGrid = frameGrid(frame);
                if (!nextGrid) {
                    simIndex = (simIndex + 1) % simFrames.length;
                    updateSimFrameCounter();
                    simScheduleNext();
                    return;
                }
                triggerLineEffects(frame, frame.event_id || `sim-${simIndex}`);
                updateHUD(frame);
                updateSimFrameCounter();

                if ((frame.clears || 0) > 0) {
                    // Line clear: show the new board instantly; particles and shake
                    // already fire at the cleared rows.
                    snapSimTo(frame, nextGrid);
                    return;
                }

                // Normal placement: the cells that just appeared drop in as one unit.
                simFalling = [];
                if (simPrevGrid && simPrevGrid.length === nextGrid.length) {
                    for (let y = 0; y < nextGrid.length; y++) {
                        for (let x = 0; x < nextGrid[y].length; x++) {
                            const c = nextGrid[y][x];
                            const p = simPrevGrid[y][x];
                            if ((c[0] + c[1] + c[2] > 0) && (p[0] + p[1] + p[2] === 0)) {
                                simFalling.push({ x, targetY: y, color: `rgb(${c[0]},${c[1]},${c[2]})` });
                            }
                        }
                    }
                }
                if (!isCleanTetromino(simFalling)) {
                    // Strided frame or shifted rows: no clean single piece to animate.
                    snapSimTo(frame, nextGrid);
                    return;
                }
                simAnimStart = performance.now();
                simAnimId = requestAnimationFrame(simAnimTick);
            }

            function simAnimTick(now) {
                if (viewMode !== 'sim' || !simPlaying) return;
                const duration = Math.max(16, SIM_ANIM_MS / simSpeed);
                const t = Math.min(1, (now - simAnimStart) / duration);
                const ease = 1 - Math.pow(1 - t, 2.5); // ease-out drop
                drawGridToCanvas(simPrevGrid || []);
                if (simFalling.length) {
                    const minY = Math.min(...simFalling.map(f => f.targetY));
                    const offset = ease * minY;
                    for (const f of simFalling) {
                        // Round to whole cells so the eased drop never renders at
                        // sub-pixel positions (which made blocks look glitchy/uneven).
                        drawBlock(ctx, f.x, Math.round(f.targetY - minY + offset), f.color);
                    }
                }
                updateAndDrawParticles();
                if (t >= 1) {
                    simPrevGrid = cloneGrid(frameGrid(simFrames[simIndex]));
                    simIndex = (simIndex + 1) % simFrames.length;
                    updateSimFrameCounter();
                    simScheduleNext();
                } else {
                    simAnimId = requestAnimationFrame(simAnimTick);
                }
            }

            function runSimStep() {
                if (viewMode !== 'sim' || !simFrames || simFrames.length === 0) return;
                if (!simPlaying) return;
                stopSimAnim();
                if (simPrevGrid === null) {
                    // Prime the first frame instantly, then animate every following drop.
                    simPrevGrid = cloneGrid(frameGrid(simFrames[0]) || []);
                    updateHUD(simFrames[0]);
                    updateSimFrameCounter();
                    simIndex = 1;
                }
                simAnimId = requestAnimationFrame(advanceSim);
            }

            document.getElementById('sim-scrubber').oninput = (e) => {
                const v = parseInt(e.target.value);
                if (simFrames && simFrames[v]) {
                    simIndex = v + 1;
                    simPrevGrid = cloneGrid(frameGrid(simFrames[v]));
                    stopSimAnim();
                    simPlaying = false;
                    updateSimPlayToggle();
                    drawGridToCanvas(simPrevGrid);
                    updateHUD(simFrames[v]);
                    updateSimFrameCounter();
                }
            };

            document.getElementById('sim-play-toggle').onclick = () => {
                simPlaying = !simPlaying;
                updateSimPlayToggle();
                if (simPlaying) runSimStep();
                else stopSimAnim();
            };

            // --- PER-MOVE REPLAY SCRUBBER ---
            // Step forward animates the next placement dropping in and then pauses;
            // step back lifts the last placed piece back out of the board (reverse of
            // the falling animation) and pauses on the previous frame.
            function simStepForward() {
                if (!simFrames || simFrames.length === 0) return;
                stopSimAnim();
                if (simPrevGrid === null) {
                    // Not primed yet: land on frame 0 instantly, then step to frame 1.
                    simPrevGrid = cloneGrid(frameGrid(simFrames[0]) || []);
                    simIndex = 1;
                    updateHUD(simFrames[0]);
                    updateSimFrameCounter();
                    drawGridToCanvas(simPrevGrid);
                }
                if (simIndex >= simFrames.length) return; // at the end
                simPlaying = true;
                simStepMode = true;
                advanceSim();
            }

            function simStepBack() {
                if (!simFrames || simFrames.length === 0) return;
                stopSimAnim();
                simPlaying = false;
                updateSimPlayToggle();
                if (simPrevGrid === null) return;
                const curIdx = simIndex - 1; // displayed frame
                if (curIdx <= 0) return;     // already at the first frame
                const targetIdx = curIdx - 1;
                const targetGrid = frameGrid(simFrames[targetIdx]);
                if (!targetGrid) return;
                const curGrid = simPrevGrid;
                const remove = [];
                for (let y = 0; y < curGrid.length; y++) {
                    for (let x = 0; x < curGrid[y].length; x++) {
                        const c = curGrid[y][x];
                        const p = targetGrid[y][x];
                        if ((c[0] + c[1] + c[2] > 0) && (p[0] + p[1] + p[2] === 0)) {
                            remove.push({ x, targetY: y, color: `rgb(${c[0]},${c[1]},${c[2]})` });
                        }
                    }
                }
                if (!isCleanTetromino(remove)) {
                    // Line clear or strided frame: snap back instantly.
                    simPrevGrid = cloneGrid(targetGrid);
                    simIndex = targetIdx + 1;
                    drawGridToCanvas(targetGrid);
                    updateHUD(simFrames[targetIdx]);
                    updateSimFrameCounter();
                    return;
                }
                simReverseCells = remove;
                simReverseToGrid = cloneGrid(targetGrid);
                simReverseTargetIdx = targetIdx;
                simReverseStart = performance.now();
                simAnimId = requestAnimationFrame(simReverseTick);
            }

            function simReverseTick(now) {
                if (viewMode !== 'sim') return;
                const duration = Math.max(16, SIM_ANIM_MS / simSpeed);
                const t = Math.min(1, (now - simReverseStart) / duration);
                const ease = 1 - Math.pow(1 - t, 2.5); // ease-out lift
                drawGridToCanvas(simReverseToGrid);
                for (const f of simReverseCells) {
                    // Rise from the resting row up out of the board (reverse drop).
                    const y = Math.round(f.targetY - ease * (f.targetY + 1));
                    if (y >= -1) drawBlock(ctx, f.x, y, f.color);
                }
                updateAndDrawParticles();
                if (t >= 1) {
                    simPrevGrid = cloneGrid(simReverseToGrid);
                    simIndex = simReverseTargetIdx + 1;
                    updateHUD(simFrames[simReverseTargetIdx]);
                    updateSimFrameCounter();
                    simAnimId = null;
                } else {
                    simAnimId = requestAnimationFrame(simReverseTick);
                }
            }

            document.getElementById('sim-step-back').onclick = simStepBack;
            document.getElementById('sim-step-fwd').onclick = simStepForward;

            // Keyboard: step through the replay one placement at a time in sim mode.
            window.addEventListener('keydown', (e) => {
                if (viewMode !== 'sim' || !simFrames || simFrames.length === 0) return;
                if (e.key === 'ArrowLeft') { e.preventDefault(); simStepBack(); }
                else if (e.key === 'ArrowRight') { e.preventDefault(); simStepForward(); }
            });

            document.querySelectorAll('.sim-speed-btn').forEach(btn => {
                btn.onclick = () => {
                    document.querySelectorAll('.sim-speed-btn').forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    simSpeed = parseInt(btn.dataset.speed);
                    if (simPlaying) runSimStep();
                };
            });

            // --- CANVAS RENDERING WITH NEON GLOW ---
            function updateHUD(data) {
                if (!data) return;
                document.getElementById('score').innerText = data.score || 0;
                document.getElementById('lines-count').innerText = data.lines || 0;
                if (data.gen !== undefined) document.getElementById('gen-num').innerText = data.gen;
                if (data.epsilon !== undefined) document.getElementById('cand-num').innerText = data.epsilon;
                if (data.best_score !== undefined) document.getElementById('high-score').innerText = data.best_score;

                nctx.clearRect(0, 0, 40, 40);
                if (data.next) {
                    data.next.forEach((row, i) => {
                        row.forEach((cell, j) => {
                            if (cell) {
                                nctx.fillStyle = data.next_color || '#00f3ff';
                                nctx.shadowColor = data.next_color || '#00f3ff';
                                nctx.shadowBlur = 6;
                                nctx.fillRect(j * 8 + 10, i * 8 + 10, 7, 7);
                            }
                        });
                    });
                }
            }

            function drawGridToCanvas(grid) {
                ctx.clearRect(0, 0, 300, 600);
                grid.forEach((row, y) => {
                    row.forEach((col, x) => {
                        if (col[0] + col[1] + col[2] > 0) {
                            drawBlock(ctx, x, y, `rgb(${col[0]},${col[1]},${col[2]})`);
                        }
                    });
                });
            }

            function drawPieceToCanvas(piece) {
                if (!piece) return;
                piece.shape.forEach((row, i) => {
                    row.forEach((cell, j) => {
                        if (cell) drawBlock(ctx, piece.x + j, piece.y + i, piece.color);
                    });
                });
            }

            function render(data) {
                if (!data) return;
                const grid = data.grid || decodePackedGrid(data.grid_packed);
                if (!grid || !grid.length) return;
                if (data.event_id && viewMode !== 'play') triggerLineEffects(data, data.event_id);
                updateHUD(data);
                drawGridToCanvas(grid);
                drawPieceToCanvas(data.piece);
                updateAndDrawParticles();
            }

            function drawBlock(c, x, y, col) {
                // Avoid per-cell shadowBlur: the old glow path forced a canvas compositor
                // pass for every block and became the main bottleneck at 20x replay.
                c.shadowBlur = 0;
                c.fillStyle = col;
                c.fillRect(x * 30, y * 30, 29, 29);
                c.strokeStyle = 'rgba(255,255,255,0.3)';
                c.lineWidth = 1;
                c.strokeRect(x * 30 + 0.5, y * 30 + 0.5, 28, 28);
                c.fillStyle = 'rgba(255,255,255,0.22)';
                c.fillRect(x * 30 + 2, y * 30 + 2, 25, 2);
            }

            // Mode Switching
            document.getElementById('real-btn').onclick = () => setMode('real');
            document.getElementById('sim-btn').onclick = () => setMode('sim');
            document.getElementById('play-btn').onclick = () => setMode('play');
            document.getElementById('hist-btn').onclick = toggleHistory;

            function setMode(mode) {
                if (viewMode === 'play' && mode !== 'play') savePlayerState();
                viewMode = mode;
                document.getElementById('real-btn').classList.toggle('active', mode === 'real');
                document.getElementById('sim-btn').classList.toggle('active', mode === 'sim');
                document.getElementById('play-btn').classList.toggle('active', mode === 'play');

                document.getElementById('sim-controls').style.display = (mode === 'sim') ? 'block' : 'none';
                document.getElementById('player-controls').style.display = (mode === 'play') ? 'block' : 'none';

                if (mode === 'sim') {
                    stopPlayerLoop();
                    stopSimAnim();
                    loadSimulationData();
                } else if (mode === 'play') {
                    stopPlayerLoop();
                    stopSimAnim();
                    resetPlayer();
                    startPlayerLoop();
                    renderPlayer();
                } else {
                    stopPlayerLoop();
                    stopSimAnim();
                }
            }

            let historySource = 'ai'; // 'ai' | 'human'

            async function renderAIHistory() {
                document.getElementById('history-title').innerText = 'HDTetris · AI TRAINING LOGS';
                document.getElementById('history-source-btn').innerText = 'HUMAN LOGS';
                try {
                    const res = await fetch('/history?limit=0');
                    const payload = await res.json();
                    const logs = payload.episodes || payload || [];
                    const rows = logs.map(l => Array.isArray(l) ? l : [l.generation, l.candidate, l.score, l.lines, l.strategy]);

                    let maxScore = payload.best_score || 0;
                    rows.forEach(l => { if (Number(l[2]) > maxScore) maxScore = Number(l[2]); });
                    document.getElementById('best-score-modal').innerText = maxScore + " PTS";
                    const total = payload.total !== undefined ? payload.total : rows.length;
                    const totalEl = document.getElementById('history-total');
                    if (totalEl) totalEl.innerText = `${total} EPISODES · COMPLETE ARCHIVE`;

                    document.getElementById('history-content').innerHTML = rows.map(l =>
                        `<div class="history-item"><span>EPISODE ${l[0]}${l[4] ? ` · ${l[4]}` : ''}</span><span style="color:#00f3ff">${l[2]} PTS / ${l[3]} LINES</span></div>`
                    ).join('');

                    const graphLogs = rows.slice().reverse();
                    const labels = graphLogs.map(l => `EP${l[0]}`);
                    const scores = graphLogs.map(l => l[2]);

                    if (chart) chart.destroy();
                    chart = new Chart(document.getElementById('evoChart'), {
                        type: 'line',
                        data: {
                            labels: labels,
                            datasets: [{
                                label: 'DQN Score',
                                data: scores,
                                borderColor: '#00f3ff',
                                tension: 0.3,
                                fill: true,
                                backgroundColor: 'rgba(0,243,255,0.15)'
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: { legend: { display: false } },
                            scales: { x: { display: false }, y: { grid: { color: '#1f2842' } } }
                        }
                    });
                } catch(e) {}
            }

            function renderHumanHistory() {
                document.getElementById('history-title').innerText = 'HDTetris · HUMAN LOGS';
                document.getElementById('history-source-btn').innerText = 'AI LOGS';
                const log = loadHumanLog();
                let best = 0;
                log.forEach(g => { if (g.score > best) best = g.score; });
                document.getElementById('best-score-modal').innerText = best + " PTS";
                const totalEl = document.getElementById('history-total');
                if (totalEl) totalEl.innerText = `${log.length} GAMES · LOCAL BROWSER`;
                document.getElementById('history-content').innerHTML = log.slice().reverse().map(g => {
                    const d = new Date(g.ts);
                    const when = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' +
                                 d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
                    return `<div class="history-item"><span>YOU · ${when}</span><span style="color:#00f3ff">${g.score} PTS / ${g.lines} LINES</span></div>`;
                }).join('') || '<div class="history-item"><span style="color:#7b88a1">NO GAMES YET — PLAY A ROUND!</span></div>';
                if (chart) chart.destroy();
                chart = new Chart(document.getElementById('evoChart'), {
                    type: 'line',
                    data: {
                        labels: log.map((_, i) => `GAME ${i + 1}`),
                        datasets: [{
                            label: 'HUMAN SCORE',
                            data: log.map(g => g.score),
                            borderColor: '#ff007f',
                            tension: 0.3,
                            fill: true,
                            backgroundColor: 'rgba(255,0,127,0.15)'
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: { x: { display: false }, y: { grid: { color: '#1f2842' } } }
                    }
                });
            }

            async function toggleHistory() {
                const box = document.getElementById('history-box');
                if (box.style.display === 'block') {
                    box.style.display = 'none';
                    return;
                }
                box.style.display = 'block';
                // Human history is shown by default while in Play mode; the button
                // switches to the AI training archive at any time.
                historySource = (viewMode === 'play') ? 'human' : 'ai';
                if (historySource === 'human') renderHumanHistory();
                else await renderAIHistory();
            }

            document.getElementById('history-source-btn').onclick = () => {
                historySource = historySource === 'ai' ? 'human' : 'ai';
                if (historySource === 'human') renderHumanHistory();
                else renderAIHistory();
            };
        </script>
    </body>
    </html>
    """)

@app.route('/state')
def get_state():
    return jsonify(ai.live_state)

@app.route('/stream')
def stream_state():
    def event_generator():
        while True:
            time.sleep(0.04) # ~25 FPS low-overhead SSE stream
            yield f"data: {json.dumps(ai.live_state)}\n\n"
    return Response(event_generator(), mimetype='text/event-stream')

@app.route('/best_game')
def get_best_game():
    return jsonify(ai.all_time_best_game_memory)

@app.route('/history')
def get_history():
    try:
        limit = int(request.args.get('limit', '0'))
        offset = max(0, int(request.args.get('offset', '0')))
        conn = sqlite3.connect(DB_FILE, timeout=10.0)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        best = conn.execute("SELECT MAX(score) FROM history").fetchone()[0] or 0
        sql = ("SELECT generation,candidate,score,lines,strategy,search_depth,step_ms,timestamp,episode_id "
               "FROM history ORDER BY generation ASC,rowid ASC")
        params = []
        if limit > 0:
            sql += " LIMIT ? OFFSET ?"
            params.extend([min(limit, 200000), offset])
        rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
        conn.close()
        return jsonify({"episodes": rows, "total": total, "offset": offset,
                        "limit": limit, "best_score": best})
    except Exception as e:
        print(f"History route error: {e}")
        return jsonify({"episodes": [], "total": 0, "best_score": 0}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)