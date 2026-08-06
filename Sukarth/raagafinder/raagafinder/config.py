"""All project constants in one place.

The FEATURE_* constants define the feature space shared between training and
the deployed Space. `feature_config_hash()` is stored inside the model
artifact and asserted at inference startup so a stale artifact fails loudly.

Dataset schema constants (DATASET_*) were verified against the dataset zip
during schema discovery; see DATASET_NOTES.md.
"""

import hashlib
import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
WORK_DIR = PROJECT_ROOT / "work"
NPZ_DIR = WORK_DIR / "npz"
ARTIFACTS_DIR = PROJECT_ROOT / "models_artifacts"
ASSETS_DIR = PROJECT_ROOT / "assets"


# ---------------------------------------------------------------------------
# Private solo-voice benchmark (held locally; not part of this repository)
# ---------------------------------------------------------------------------
# A set of solo-voice devotional recordings contributes derived pitch
# statistics to training and provides the permanent solo-voice holdout. The
# audio is never copied into this repository, redistributed, or uploaded: the
# scripts that use it read it in place. Both locations come from the
# environment so that no machine-specific path is committed.
#
#   RAAGAFINDER_PRIVATE_AUDIO      directory holding the recordings
#   RAAGAFINDER_PRIVATE_APPROVALS  reviewed per-song metadata (JSON)
#
# Everything derived from them lives under work/, which is gitignored and
# excluded from deployment.
PRIVATE_AUDIO_ENV = "RAAGAFINDER_PRIVATE_AUDIO"
PRIVATE_APPROVALS_ENV = "RAAGAFINDER_PRIVATE_APPROVALS"


def private_path(env_name: str) -> Path:
    """Resolve one of the private-set locations, or exit with an explanation.

    Exits rather than returning None because every caller needs the path to do
    anything at all, and a missing-file traceback three frames deeper does not
    tell the reader that an environment variable is what is missing.
    """
    value = os.environ.get(env_name)
    if not value:
        raise SystemExit(
            f"{env_name} is not set. This script reads the private solo-voice "
            f"set, which is not distributed with the repository. Point "
            f"{env_name} at the local copy to run it."
        )
    path = Path(value)
    if not path.exists():
        raise SystemExit(f"{env_name} points at {path}, which does not exist.")
    return path


# ---------------------------------------------------------------------------
# Dataset (Indian Art Music Raga Recognition Dataset - features, Zenodo)
# ---------------------------------------------------------------------------
DATASET_ZIP = DATA_DIR / "raw" / "raga_features.zip"
DATASET_URL = (
    "https://zenodo.org/api/records/7278506/files/"
    "Indian%20Art%20Music%20Raga%20Recognition%20Dataset%20(features).zip/content"
)
DATASET_MD5 = "5dfc26dd1c2652ab75a62faec7f45f08"
DATASET_SIZE_BYTES = 3_612_501_746

EXPECTED_N_RECORDINGS = 480  # Carnatic subset (CMD)
EXPECTED_N_RAGAS = 40
EXPECTED_RECS_PER_RAGA = 12

# Verified during schema discovery (see DATASET_NOTES.md):
DATASET_PITCH_HOP_S = 0.0044444  # 196/44100, Melodia hop
DATASET_UNVOICED_VALUE = 0.0

# ---------------------------------------------------------------------------
# Feature space (pure numpy; shared verbatim train <-> Space)
# ---------------------------------------------------------------------------
# PCD: 240 bins/octave = 5 cents/bin so that +-500/+-700 cent tonic rotations
# are exact integer bin shifts (500/5=100, 700/5=140).
PCD_BINS = 240
PCD_SMOOTH_SIGMA_BINS = 2.4  # ~12 cents

# TDMS: 120x120 = 10 cents/bin (500/10=50, 700/10=70 -> integer shifts).
TDMS_BINS = 120
TDMS_TAU_S = 0.2  # ablation winner (0.2 > 0.3 > 0.5 on grouped CV)
TDMS_ALPHA = 0.75
TDMS_SMOOTH_SIGMA_BINS = 2.0

CENTS_PER_OCTAVE = 1200.0

# Chunking (training-time augmentation; app-time windows)
CHUNK_VOICED_LENGTHS_S = (30.0, 60.0, 120.0, 240.0)
CHUNKS_PER_RECORDING = 16
APP_WINDOW_S = 45.0
APP_HOP_S = 15.0

# Tonic hypothesis rotations, in cents (0 must come first). On octave-folded
# features -700 = +500 and +700 = -500, so there are only two distinct
# non-zero hypotheses: detected tonic sitting a fifth or a fourth off.
TONIC_ROTATIONS_CENTS = (0, 700, 500)
ROTATION_ACCEPT_MARGIN = 0.15  # non-zero offset must beat offset-0 top-1 by this

# Inference quality gates
MIN_VOICED_S = 20.0
MIN_VOICED_RATIO = 0.15
UNCERTAIN_TOP1 = 0.35
UNCERTAIN_MARGIN = 0.10

# Long-recording sampling (shared by app.py and scripts/eval_real.py):
# recordings over MULTISEG_ABOVE_S are analyzed as SEGMENT_S-long sections at
# these positions, each section analyzed independently under one consensus
# tonic, then merged by corroboration (pipeline.analyze_segments).
MULTISEG_ABOVE_S = 6 * 60
SEGMENT_S = 120
SEGMENT_POSITIONS = (0.15, 0.40, 0.60, 0.85)

_FEATURE_KEYS = dict(
    pcd_bins=PCD_BINS,
    pcd_sigma=PCD_SMOOTH_SIGMA_BINS,
    tdms_bins=TDMS_BINS,
    tdms_tau=TDMS_TAU_S,
    tdms_alpha=TDMS_ALPHA,
    tdms_sigma=TDMS_SMOOTH_SIGMA_BINS,
)
# The per-swara gamaka member is NOT in this hash: it is an optional,
# self-describing ensemble component (present only when the artifact carries
# gamaka_W), so it must not invalidate artifacts that don't use it. Its
# descriptor is versioned in the artifact's gamaka meta block instead
# (raagafinder.features.gamaka.GAMAKA_VERSION), checked at predict time.


def feature_config_hash() -> str:
    blob = json.dumps(_FEATURE_KEYS, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]
