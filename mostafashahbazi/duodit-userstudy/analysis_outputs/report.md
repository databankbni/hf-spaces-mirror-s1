# DuoDiT User Study Analysis

- Source dataset: `mostafashahbazi/duodit-user-study-results`
- Result files: `14`
- Raw rows: `4200`
- Total submissions: `14`
- Submissions excluded by email: `0`
- Rows after email exclusion: `4200`
- Complete submissions analyzed: `14`
- Rows analyzed: `4200`
- Expected questions per complete submission: `300`

## Model Preference

| Metric | Value |
| --- | ---: |
| DuoDiT wins | 1490 |
| LightningDiT wins | 1672 |
| About the same | 1038 |
| Decisive rows | 3162 |
| DuoDiT win rate among decisive | 47.12% |
| DuoDiT 95% Wilson CI | [0.4539, 0.4886] |
| Binomial p-value vs 50/50 | 0.001284 |

## Output Files

- `summary.json`: machine-readable headline metrics
- `submissions.csv`: one row per submission, including completeness
- `model_preference.csv`: one-row model preference summary
- `class_summary.csv`: per ImageNet class preference summary
- `prompt_summary.csv`: per prompt/image-pair preference summary
- `participant_summary.csv`: per participant preference summary
- `display_position_summary.csv`: left/right model balancing summary
- `raw_rows.csv`: rows used for analysis after filtering
- `incomplete_submissions.csv`: incomplete submissions excluded by default
- `excluded_submissions.csv`: submissions excluded by participant email
