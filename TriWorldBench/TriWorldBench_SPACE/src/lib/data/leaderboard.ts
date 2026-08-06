import { getDb } from "@/lib/db";
import { get as dbGet, all } from "@/lib/db/helpers";
import { latestScoresForSubmissions } from "@/lib/data/metrics";
import type { LeaderboardSnapshot, LeaderboardEntry, RadarEntry } from "@/lib/db/schema";

export const DEFAULT_RADAR_METRICS = [
  "tri_view_consistency", "task_alignment", "physical_3d_coherence",
  "motion_quality", "temporal_consistency", "visual_quality",
];
export const PUBLIC_LEADERBOARD_LIMIT = 10_000;

export function latestSnapshot(snapshotParam?: string | null): LeaderboardSnapshot | null {
  const db = getDb();
  if (snapshotParam && snapshotParam !== "latest") {
    return (
      dbGet<LeaderboardSnapshot>(db.prepare("SELECT * FROM leaderboard_snapshots WHERE id = ?"), snapshotParam) ||
      dbGet<LeaderboardSnapshot>(db.prepare("SELECT * FROM leaderboard_snapshots WHERE label = ?"), snapshotParam)
    );
  }
  return dbGet<LeaderboardSnapshot>(
    db.prepare("SELECT * FROM leaderboard_snapshots ORDER BY is_latest DESC, snapshot_time DESC, id DESC LIMIT 1")
  );
}

export function getSnapshotHistory(): LeaderboardSnapshot[] {
  return all<LeaderboardSnapshot>(
    getDb().prepare("SELECT * FROM leaderboard_snapshots ORDER BY snapshot_time DESC, id DESC")
  );
}

export function getLeaderboard(
  snapshotParam?: string | null,
  limit = PUBLIC_LEADERBOARD_LIMIT
): {
  snapshot: LeaderboardSnapshot | null;
  entries: LeaderboardEntry[];
} {
  const db = getDb();
  const snapshot = latestSnapshot(snapshotParam);
  if (!snapshot) return { snapshot: null, entries: [] };
  const safeLimit = Math.max(1, Math.min(limit, PUBLIC_LEADERBOARD_LIMIT));

  const rawEntries = db
    .prepare(
      `SELECT e.rank, e.status_label, e.updated_label, e.submission_id,
              t.id AS team_id, t.slug AS team_slug, t.name AS team_name, t.affiliation, t.strengths,
              mo.id AS model_id, mo.slug AS model_slug, mo.name AS model_name,
              s.version_label, s.status AS submission_status, s.dataset_split, s.submitted_at,
              sr.normalized_value, sr.percentile, sr.raw_value
       FROM leaderboard_snapshot_entries e
       JOIN submissions s ON s.id = e.submission_id
       JOIN models mo ON mo.id = s.model_id
       JOIN teams t ON t.id = mo.team_id
       JOIN score_records sr ON sr.id = e.score_record_id
       WHERE e.snapshot_id = ? ORDER BY e.rank LIMIT ?`
    )
    .all(snapshot.id, safeLimit) as Array<Record<string, unknown>>;

  const submissionIds = rawEntries.map((e) => e.submission_id as number);
  const scoresBySubmission = latestScoresForSubmissions(submissionIds);

  const entries: LeaderboardEntry[] = rawEntries.map((entry) => ({
    rank: entry.rank as number,
    statusLabel: entry.status_label as string | null,
    updatedLabel: entry.updated_label as string | null,
    team: {
      id: entry.team_id as number, slug: entry.team_slug as string,
      name: entry.team_name as string, affiliation: entry.affiliation as string | null,
      strengths: entry.strengths as string | null,
    },
    model: {
      id: entry.model_id as number, slug: entry.model_slug as string,
      name: entry.model_name as string,
    },
    submission: {
      id: entry.submission_id as number, versionLabel: entry.version_label as string,
      status: entry.submission_status as string, datasetSplit: entry.dataset_split as string | null,
      submittedAt: entry.submitted_at as string,
    },
    score: {
      rawValue: entry.raw_value as number | null,
      normalizedValue: entry.normalized_value as number | null,
      percentile: entry.percentile as number | null,
    },
    metrics: scoresBySubmission.get(entry.submission_id as number) || {},
  }));

  return { snapshot, entries };
}

export function getRadarData(
  metricCodes?: string[],
  top = 8
): { metricCodes: string[]; entries: RadarEntry[] } {
  const codes = metricCodes?.length ? metricCodes : DEFAULT_RADAR_METRICS;
  const board = getLeaderboard("latest");
  const entries = board.entries.slice(0, top).map((entry) => ({
    rank: entry.rank, model: entry.model, team: entry.team, score: entry.score,
    axes: codes.map((code) => {
      const metric = entry.metrics[code];
      return { code, label: metric ? metric.displayName : code, value: metric?.percentile ?? null };
    }),
  }));
  return { metricCodes: codes, entries };
}

export function rerankSnapshot(snapshotId: number): void {
  const db = getDb();
  const rows = db
    .prepare(
      `SELECT e.id, sr.raw_value FROM leaderboard_snapshot_entries e
       JOIN score_records sr ON sr.id = e.score_record_id
       WHERE e.snapshot_id = ? ORDER BY sr.raw_value DESC, e.id`
    )
    .all(snapshotId) as Array<{ id: number; raw_value: number | null }>;

  for (const row of rows) {
    db.prepare("UPDATE leaderboard_snapshot_entries SET rank = ? WHERE id = ?").run(-row.id, row.id);
  }
  rows.forEach((_row, index) => {
    db.prepare("UPDATE leaderboard_snapshot_entries SET rank = ? WHERE id = ?").run(index + 1, rows[index].id);
  });
}

export function getModelScores(modelId: string): {
  model: Record<string, unknown> | null;
  submission: Record<string, unknown> | null;
  scores: Array<Record<string, unknown>>;
} {
  const db = getDb();
  const model = db.prepare(
    `SELECT mo.*, t.name AS team_name FROM models mo JOIN teams t ON t.id = mo.team_id WHERE mo.id = ? OR mo.slug = ?`
  ).get(modelId, modelId) as Record<string, unknown> | null;

  if (!model) return { model: null, submission: null, scores: [] };

  const modelIdNum = model.id as number;
  const submission = db.prepare(
    "SELECT * FROM submissions WHERE model_id = ? ORDER BY submitted_at DESC, id DESC LIMIT 1"
  ).get(modelIdNum) as Record<string, unknown> | null;

  if (!submission) return { model, submission: null, scores: [] };

  const subId = submission.id as number;
  const scores = db.prepare(
    `SELECT m.code, m.display_name, m.category, sr.raw_value, sr.normalized_value, sr.percentile, sr.recorded_at
     FROM score_records sr JOIN metrics m ON m.id = sr.metric_id
     JOIN (SELECT metric_id, MAX(id) AS latest_id FROM score_records WHERE submission_id = ? GROUP BY metric_id) latest ON latest.latest_id = sr.id
     ORDER BY m.sort_order`
  ).all(subId) as Array<Record<string, unknown>>;

  return { model, submission, scores };
}
