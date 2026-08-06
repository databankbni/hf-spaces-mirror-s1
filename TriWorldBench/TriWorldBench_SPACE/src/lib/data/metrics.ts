import { getDb } from "@/lib/db";
import { all, get as dbGet } from "@/lib/db/helpers";
import type { Metric, MetricExplanation, MetricScore } from "@/lib/db/schema";
import { localized } from "@/lib/i18n";

export function getMetrics(): Metric[] {
  return all<Metric>(getDb().prepare("SELECT * FROM metrics ORDER BY sort_order, id")).map((row) => ({
    ...row,
    displayNameText: localized(row.display_name_en || row.display_name, row.display_name_zh),
    shortLabelText: localized(row.short_label_en || row.display_name_en || row.display_name, row.short_label_zh || row.display_name_zh),
    descriptionText: localized(row.description_en || row.description || "", row.description_zh),
  }));
}

export function getMetricExplanations(): MetricExplanation[] {
  return all<MetricExplanation>(getDb().prepare("SELECT * FROM metric_explanations ORDER BY id"));
}

export function latestScoresForSubmissions(
  submissionIds: number[]
): Map<number, Record<string, MetricScore>> {
  const db = getDb();
  if (!submissionIds.length) return new Map();

  const placeholders = submissionIds.map(() => "?").join(",");
  const rows = db
    .prepare(
      `SELECT sr.*, m.*
       FROM score_records sr JOIN metrics m ON m.id = sr.metric_id
       JOIN (SELECT submission_id, metric_id, MAX(id) AS latest_id
             FROM score_records WHERE submission_id IN (${placeholders})
             GROUP BY submission_id, metric_id) latest ON latest.latest_id = sr.id
       ORDER BY m.sort_order`
    )
    .all(...submissionIds) as Array<Record<string, unknown>>;

  const grouped = new Map<number, Record<string, MetricScore>>();
  for (const row of rows) {
    const sid = row.submission_id as number;
    if (!grouped.has(sid)) grouped.set(sid, {});
    grouped.get(sid)![row.code as string] = {
      code: row.code as string,
      displayName: row.display_name as string,
      displayNameText: localized(
        (row.display_name_en as string | null) || (row.display_name as string),
        row.display_name_zh as string | null
      ),
      shortLabelText: localized(
        (row.short_label_en as string | null) || (row.display_name_en as string | null) || (row.display_name as string),
        (row.short_label_zh as string | null) || (row.display_name_zh as string | null)
      ),
      category: row.category as string,
      rawValue: row.raw_value as number | null,
      normalizedValue: row.normalized_value as number | null,
      percentile: row.percentile as number | null,
      recordedAt: row.recorded_at as string,
    };
  }
  return grouped;
}
