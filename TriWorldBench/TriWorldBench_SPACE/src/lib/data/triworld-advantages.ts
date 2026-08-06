import { getDb } from "@/lib/db";
import { all } from "@/lib/db/helpers";
import { contentValue, hasLocalizedText, localized, type LocalizedText } from "@/lib/i18n";

export interface TriWorldAdvantage {
  id: number;
  titleText: LocalizedText;
  bodyText: LocalizedText;
  them: string;
  themNoteText: LocalizedText;
  us: string;
  usNoteText: LocalizedText;
}

interface TriWorldAdvantageRow {
  id: number;
  title_en: string;
  title_zh: string;
  body_en: string;
  body_zh: string;
  them: string;
  them_note_en: string;
  them_note_zh: string;
  us: string;
  us_note_en: string;
  us_note_zh: string;
}

export function getTriWorldAdvantages(): TriWorldAdvantage[] {
  const rows = all<TriWorldAdvantageRow>(
    getDb().prepare("SELECT * FROM triworld_advantages ORDER BY sort_order, id")
  );
  return rows
    .map((row) => ({
      id: row.id,
      titleText: localized(row.title_en, row.title_zh),
      bodyText: localized(row.body_en, row.body_zh),
      them: contentValue(row.them),
      themNoteText: localized(row.them_note_en, row.them_note_zh),
      us: contentValue(row.us),
      usNoteText: localized(row.us_note_en, row.us_note_zh),
    }))
    .filter((item) =>
      hasLocalizedText(item.titleText) ||
      hasLocalizedText(item.bodyText) ||
      Boolean(item.them) ||
      Boolean(item.us) ||
      hasLocalizedText(item.themNoteText) ||
      hasLocalizedText(item.usNoteText)
    );
}
