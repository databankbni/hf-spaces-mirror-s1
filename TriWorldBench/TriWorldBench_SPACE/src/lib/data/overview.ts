import { getDb } from "@/lib/db";
import { get as dbGet } from "@/lib/db/helpers";
import type { OverviewContent } from "@/lib/db/schema";

export function getOverview(): OverviewContent | null {
  const row = dbGet<OverviewContent>(
    getDb().prepare("SELECT * FROM overview_content ORDER BY id LIMIT 1")
  );
  if (row?.stat_json) {
    try { row.stats = JSON.parse(row.stat_json); } catch { row.stats = []; }
  }
  return row;
}
