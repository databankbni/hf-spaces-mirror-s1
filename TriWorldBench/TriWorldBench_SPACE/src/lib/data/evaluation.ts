import { getDb } from "@/lib/db";
import { all } from "@/lib/db/helpers";
import type { EvaluationSection } from "@/lib/db/schema";

export function getEvaluationSections(): EvaluationSection[] {
  return all<EvaluationSection>(
    getDb().prepare("SELECT * FROM evaluation_sections ORDER BY sort_order, id")
  );
}
