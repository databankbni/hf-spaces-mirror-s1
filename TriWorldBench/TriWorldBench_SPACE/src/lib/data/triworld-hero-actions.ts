import { getDb } from "@/lib/db";
import { all } from "@/lib/db/helpers";
import { contentValue, hasLocalizedText, localized, type LocalizedText } from "@/lib/i18n";

export interface TriWorldHeroAction {
  id: number;
  actionKey: string;
  labelText: LocalizedText;
  href: string;
  openInNewTab: boolean;
}

interface HeroActionRow {
  id: number;
  action_key: string;
  label_en: string;
  label_zh: string;
  href: string;
  open_in_new_tab: number;
}

const FALLBACK_ACTIONS: TriWorldHeroAction[] = [
  { id: 1, actionKey: "submission", labelText: localized("Submission", "提交"), href: "/submission", openInNewTab: false },
  { id: 2, actionKey: "contact_us", labelText: localized("Contact Us", "联系我们"), href: "#contact", openInNewTab: false },
  { id: 3, actionKey: "github", labelText: localized("GitHub", "GitHub"), href: "https://github.com", openInNewTab: true },
  { id: 4, actionKey: "paper", labelText: localized("Paper", "论文"), href: "#citation", openInNewTab: false },
];

export function getTriWorldHeroActions(): TriWorldHeroAction[] {
  try {
    const rows = all<HeroActionRow>(
      getDb().prepare("SELECT * FROM triworld_hero_actions ORDER BY sort_order, id")
    );
    if (!rows.length) return FALLBACK_ACTIONS;
    return rows
      .map((row) => ({
        id: row.id,
        actionKey: row.action_key,
        labelText: localized(row.label_en, row.label_zh),
        href: contentValue(row.href),
        openInNewTab: Number(row.open_in_new_tab) > 0,
      }))
      .filter((action) => hasLocalizedText(action.labelText) && Boolean(action.href));
  } catch {
    return FALLBACK_ACTIONS;
  }
}
