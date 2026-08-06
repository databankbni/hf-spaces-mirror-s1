export const TRIWORLD_COLORS = [
  "#0f766e", "#2563eb", "#d97706", "#16a34a", "#7c3aed", "#e11d48",
  "#0891b2", "#4f46e5", "#c2410c", "#15803d", "#9333ea", "#be123c",
  "#0369a1", "#a16207", "#0f766e", "#4338ca", "#b45309", "#047857",
  "#6d28d9", "#9f1239", "#155e75", "#1d4ed8", "#ca8a04", "#166534",
] as const;

export const TRIWORLD_RANKING_CODE = "TWBScore" as const;
export const TRIWORLD_SCORE_ACCENT = "#a16207" as const;

// Database keys used by Evaluation Metrics. The leaderboard uses these labels
// so the table always follows the terminology maintained in localization data.
export const TRIWORLD_EVALUATION_DEFINITION_CODES: Readonly<Record<string, string>> = {
  "twb-score": "TWBScore",
  "tri-view-consistency": "tri_view_consistency",
  "task-alignment": "task_alignment",
  "physical-3d-coherence": "physical_3d_coherence",
  "motion-quality": "motion_quality",
  "temporal-consistency": "temporal_consistency",
  "visual-quality": "visual_quality",
  "normalized-psnr": "psnr",
  ssim: "ssim",
  "vlm-consistency-i": "vlm_consistency_i",
  "vlm-consistency-ii": "vlm_consistency_ii",
  "vlm-consistency-iii": "vlm_consistency_iii",
  "vqa-consistency": "vqa_consistency",
  "instruction-following": "Instruction_Following",
  "semantic-alignment": "semantic_alignment",
  "jepa-similarity": "jepa_similarity",
  "interaction-quality": "Interaction_Quality",
  perspective: "Perspectivity",
  "state-alignment": "dynamic_state_alignment",
  "flow-score": "flow_score",
  "trajectory-accuracy": "trajectory_accuracy",
  "subject-consistency": "subject_consistency",
  "background-consistency": "background_consistency",
  "photometric-smoothness": "photometric_smoothness",
  "image-quality": "image_quality",
  "aesthetic-quality": "aesthetic_quality",
};

export interface TriWorldMetricDefinition {
  key: string;
  code: string;
}

export interface TriWorldMetricGroup {
  key: string;
  code: string;
  color: string;
  submetrics: readonly TriWorldMetricDefinition[];
}

export const TRIWORLD_METRIC_GROUPS: readonly TriWorldMetricGroup[] = [
  {
    key: "twb-score",
    code: TRIWORLD_RANKING_CODE,
    color: TRIWORLD_SCORE_ACCENT,
    submetrics: [],
  },
  {
    key: "tri-view-consistency",
    code: "tri_view_consistency",
    color: "#2563eb",
    submetrics: [
      { key: "psnr", code: "psnr" },
      { key: "ssim", code: "ssim" },
      { key: "vlm-i", code: "vlm_consistency_i" },
      { key: "vlm-ii", code: "vlm_consistency_ii" },
      { key: "vlm-iii", code: "vlm_consistency_iii" },
      { key: "vqa", code: "vqa_consistency" },
    ],
  },
  {
    key: "task-alignment",
    code: "task_alignment",
    color: "#f97316",
    submetrics: [
      { key: "instruction", code: "Instruction_Following" },
      { key: "semantic", code: "semantic_alignment" },
      { key: "jepa", code: "jepa_similarity" },
    ],
  },
  {
    key: "physical-3d-coherence",
    code: "physical_3d_coherence",
    color: "#16a34a",
    submetrics: [
      { key: "interaction", code: "Interaction_Quality" },
      { key: "perspectivity", code: "Perspectivity" },
    ],
  },
  {
    key: "motion-quality",
    code: "motion_quality",
    color: "#7c3aed",
    submetrics: [
      { key: "state-alignment", code: "dynamic_state_alignment" },
      { key: "flow", code: "flow_score" },
      { key: "trajectory", code: "trajectory_accuracy" },
    ],
  },
  {
    key: "temporal-consistency",
    code: "temporal_consistency",
    color: "#e11d48",
    submetrics: [
      { key: "subject", code: "subject_consistency" },
      { key: "background", code: "background_consistency" },
      { key: "photometric", code: "photometric_smoothness" },
    ],
  },
  {
    key: "visual-quality",
    code: "visual_quality",
    color: "#0f766e",
    submetrics: [
      { key: "image", code: "image_quality" },
      { key: "aesthetic", code: "aesthetic_quality" },
    ],
  },
];

export interface TriWorldTableMetric extends TriWorldMetricDefinition {
  groupKey: string;
  color: string;
  isOverall: boolean;
  isCategory: boolean;
  className: string;
}

export const TRIWORLD_TABLE_METRICS: readonly TriWorldTableMetric[] = [
  // Keep the total and all second-level category scores together before any third-level metric.
  ...TRIWORLD_METRIC_GROUPS.map((group) => ({
    key: group.key,
    code: group.code,
    groupKey: group.key,
    color: group.color,
    isOverall: group.code === TRIWORLD_RANKING_CODE,
    isCategory: true,
    className: "twb-col-category",
  })),
  ...TRIWORLD_METRIC_GROUPS.flatMap((group) =>
    group.submetrics.map((metric) => ({
      ...metric,
      groupKey: group.key,
      color: group.color,
      isOverall: false,
      isCategory: false,
      className: "twb-col-submetric",
    }))
  ),
];

export const TRIWORLD_ALL_METRIC_CODES = TRIWORLD_TABLE_METRICS.map((metric) => metric.code);

export const TRIWORLD_RADAR_DIMS = TRIWORLD_METRIC_GROUPS
  .filter((group) => group.code !== TRIWORLD_RANKING_CODE)
  .map((group) => ({
    key: group.key,
    code: group.code,
    color: group.color,
    maxValue: group.code === "visual_quality" ? 50 : 100,
  }));

export interface TriWorldVisualizationPanel {
  key: string;
  code: string | null;
  groupKey: string;
  kind: "overall" | "category" | "submetric";
}

export const TRIWORLD_VIS_PANELS: readonly TriWorldVisualizationPanel[] = [
  { key: "overall", code: null, groupKey: "twb-score", kind: "overall" },
  ...TRIWORLD_METRIC_GROUPS
    .filter((group) => group.code !== TRIWORLD_RANKING_CODE)
    .flatMap((group) => [
      {
        key: group.key,
        code: group.code,
        groupKey: group.key,
        kind: "category" as const,
      },
      ...group.submetrics.map((metric) => ({
        key: metric.key,
        code: metric.code,
        groupKey: group.key,
        kind: "submetric" as const,
      })),
    ]),
];

export type TriWorldMetricCode = string;

export interface TriWorldBoardEntry {
  rank: number;
  modelName: string;
  teamName: string;
  score: number | null;
  normalizedScore: number | null;
  status: string;
  metrics: Record<string, number | null>;
  normalizedMetrics: Record<string, number | null>;
}
