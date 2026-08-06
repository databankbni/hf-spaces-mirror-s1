import { getDb } from "@/lib/db";
import { all } from "@/lib/db/helpers";
import type { PolicyItem } from "@/lib/db/schema";
import { hasLocalizedText, localized } from "@/lib/i18n";

export function getPolicies(): PolicyItem[] {
  return all<PolicyItem>(getDb().prepare("SELECT * FROM policy_items ORDER BY sort_order, id"))
    .map((row) => ({
      ...row,
      titleText: localized(row.title_en || row.title, row.title_zh),
      bodyText: localized(row.body_en || row.body, row.body_zh),
    }))
    .filter((row) => hasLocalizedText(row.titleText) || hasLocalizedText(row.bodyText));
}
