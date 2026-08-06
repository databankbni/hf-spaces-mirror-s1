import { getDb } from "@/lib/db";
import { all } from "@/lib/db/helpers";
import { getDateStatus } from "@/lib/utils";
import type { ImportantDate } from "@/lib/db/schema";
import { hasLocalizedText, localized } from "@/lib/i18n";

function formatDate(value: string, locale: "en" | "zh"): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    month: locale === "zh" ? "long" : "short",
    day: "2-digit",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}

export function getImportantDates(): ImportantDate[] {
  const rows = all<ImportantDate>(
    getDb().prepare("SELECT * FROM important_dates ORDER BY sort_order, starts_at")
  );
  return rows
    .map((row) => ({
      ...row,
      status: getDateStatus(row.starts_at, row.ends_at),
      titleText: localized(row.title_en || row.title, row.title_zh),
      dateLabelText: localized(
        row.date_label_en || formatDate(row.starts_at, "en"),
        row.date_label_zh || formatDate(row.starts_at, "zh")
      ),
      bodyText: localized(row.body_en || row.body, row.body_zh),
      ctaLabelText: localized(row.cta_label_en || row.cta_label || "", row.cta_label_zh),
    }))
    .filter(
      (row) =>
        hasLocalizedText(row.titleText) ||
        hasLocalizedText(row.dateLabelText) ||
        hasLocalizedText(row.bodyText) ||
        hasLocalizedText(row.ctaLabelText)
    );
}
