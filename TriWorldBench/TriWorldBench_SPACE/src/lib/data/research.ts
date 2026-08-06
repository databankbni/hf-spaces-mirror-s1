import { getDb } from "@/lib/db";
import { all } from "@/lib/db/helpers";
import type { ResearchSection, AcademicReference } from "@/lib/db/schema";
import { hasLocalizedText, localized } from "@/lib/i18n";

export function getResearchSections(): ResearchSection[] {
  const rows = all<ResearchSection>(
    getDb().prepare("SELECT * FROM research_sections ORDER BY sort_order, id")
  );
  for (const row of rows) {
    if (row.tags_json) { try { (row as any).tags = JSON.parse(row.tags_json); } catch { (row as any).tags = []; } }
  }
  return rows;
}

export function getAcademicReferences(): AcademicReference[] {
  const rows = all<AcademicReference>(
    getDb().prepare("SELECT * FROM academic_references ORDER BY sort_order, id")
  );
  for (const row of rows) {
    if (row.tags_json) { try { (row as any).tags = JSON.parse(row.tags_json); } catch { (row as any).tags = []; } }
    row.titleText = localized(row.title_en || row.title, row.title_zh);
    row.bodyText = localized(row.body_en || row.body, row.body_zh);
  }
  return rows.filter(
    (row) => hasLocalizedText(row.titleText) || hasLocalizedText(row.bodyText)
  );
}
