import { getDb } from "@/lib/db";
import { all } from "@/lib/db/helpers";
import type { TriWorldVisualMetric } from "@/lib/db/schema";

export function getTriWorldVisualMetrics(): TriWorldVisualMetric[] {
  try {
    const rows = all<TriWorldVisualMetric>(
      getDb().prepare("SELECT * FROM triworld_visual_metrics ORDER BY sort_order, id")
    );
    return rows.length ? rows : fallbackVisualMetrics();
  } catch {
    return fallbackVisualMetrics();
  }
}

function fallbackVisualMetrics(): TriWorldVisualMetric[] {
  const rows = [
    ["__overall__", "TWB-Score", "TWB 总分", "Overall TWB-Score Ranking", "TWB 总分排名"],
    ["tri_view_consistency", "Tri-View", "三视角", "Tri-View Consistency Ranking", "三视角一致性排名"],
    ["task_alignment", "Task", "任务", "Task Alignment Ranking", "任务对齐排名"],
    ["physical_3d_coherence", "Physical 3D", "物理三维", "Physical and 3D Coherence Ranking", "物理与三维一致性排名"],
    ["motion_quality", "Motion", "运动", "Motion Quality Ranking", "运动质量排名"],
    ["temporal_consistency", "Temporal", "时间", "Temporal Consistency Ranking", "时间一致性排名"],
    ["visual_quality", "Visual", "视觉", "Visual Quality Ranking", "视觉质量排名"],
  ] as const;
  return rows.map(([metric_code, label_en, label_zh, title_en, title_zh], index) => ({
    id: index + 1,
    metric_code,
    label_en,
    label_zh,
    title_en,
    title_zh,
    sort_order: index,
    updated_at: "",
  }));
}
