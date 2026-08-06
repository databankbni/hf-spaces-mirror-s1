BENCHMARK_DATASET_REPO = "studyOverflow/TempMemoryData"
LEADERBOARD_REPO = "PeanutUp/membench_leaderboard_submission"
LOCAL_LEADERBOARD_DIR = "./membench_leaderboard_submission"
RESULTS_CSV = "./membench_leaderboard_submission/results.csv"
SUBMISSION_JSON_FILENAME = "leaderboard_submission.json"

MODEL_INFO_COLUMNS = [
    "Rank",
    "Model Name",
    "Model Link",
    "Model Type",
    "Certification",
    "Accessibility",
    "Sampled by",
    "Evaluated by",
    "Date",
    "Total M-Score",
    "Entity Score",
    "Environment Score",
    "Causal Score",
]

METRIC_COLUMNS = [
    "Object Geometry",
    "Object Texture",
    "Human Identity",
    "Human Appearance",
    "Epipolar Geometry",
    "Reprojection Consistency",
    "Lighting Consistency",
    "Style Consistency",
    "State Progress",
    "Physical Plausibility",
    "Text Interaction",
    "Action Interaction",
]

ALL_COLUMNS = MODEL_INFO_COLUMNS + METRIC_COLUMNS

MODEL_TYPE_CHOICES = [
    "All",
    "text-conditioned",
    "action-conditioned",
]

LEADERBOARD_INTRO = """
# MBench Leaderboard

**MBench** evaluates memory capability in video world models: whether generated worlds keep entities, environments, and causal state coherent across long horizons and interaction.

- **Entity Consistency:** object geometry/texture and human identity/appearance.
- **Environment Consistency:** spatial consistency, reprojection, lighting, and style stability.
- **Causal Consistency:** state progress, physical plausibility, and text/action interaction consistency.

Seed leaderboard values are transcribed from Table 2 of the MBench paper. Aggregate columns are derived as unweighted averages over the reported sub-dimensions until official leaderboard totals are released.

Dataset: `studyOverflow/TempMemoryData`  
Leaderboard data repo: `PeanutUp/membench_leaderboard_submission`  
Project page: https://peanutup.github.io/MBench-project/  
GitHub: https://github.com/study-overflow/MBench
"""

SUBMIT_INTRO = """
# Submit to MBench

Upload a ZIP file containing `leaderboard_submission.json` at the ZIP root.
Detailed evaluation outputs may be included under `verification/`.
Submissions are saved to `submissions/pending/` in the leaderboard data repo and are **not** added to the public leaderboard automatically.

Required JSON keys: `model_name`, `model_link`, `model_type`, and `total_m_score`.
"""
