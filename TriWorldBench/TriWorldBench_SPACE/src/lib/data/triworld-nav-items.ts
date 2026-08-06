import { getDb } from "@/lib/db";
import { all } from "@/lib/db/helpers";
import { contentValue, hasLocalizedText, localized, type LocalizedText } from "@/lib/i18n";

export interface TriWorldNavItem {
  id: number;
  itemKey: string;
  labelText: LocalizedText;
  href: string;
  openInNewTab: boolean;
}

interface NavItemRow {
  id: number;
  item_key: string;
  label_en: string;
  label_zh: string;
  href: string;
  open_in_new_tab: number;
  is_visible: number;
}

const FALLBACK_NAV_ITEMS: TriWorldNavItem[] = ([
  ["abstract", "Abstract", "摘要", "#abstract"],
  ["overview", "Overview", "概览", "#overview"],
  ["advantages", "Advantages", "优势", "#advantages"],
  ["cases", "Cases", "案例", "#cases"],
  ["metrics", "Metrics", "指标", "#metrics"],
  ["leaderboard", "Leaderboard", "榜单", "#leaderboard"],
  ["visualization", "Visualization", "可视化", "#visualization"],
  ["datasets", "Datasets", "数据集", "#datasets"],
  ["policies", "Policy&Rules", "政策与规则", "#policies"],
  ["submission", "Submission", "提交", "#submission"],
  ["contact", "Contact Us", "联系我们", "#contact"],
] as const).map(([itemKey, labelEn, labelZh, href], index) => ({
  id: index + 1,
  itemKey,
  labelText: localized(labelEn, labelZh),
  href,
  openInNewTab: false,
}));

export function getTriWorldNavItems(): TriWorldNavItem[] {
  try {
    const rows = all<NavItemRow>(
      getDb().prepare("SELECT * FROM triworld_nav_items ORDER BY sort_order, id")
    );
    if (!rows.length) return FALLBACK_NAV_ITEMS;
    return rows
      .map((row) => ({
        id: row.id,
        itemKey: row.item_key,
        labelText: localized(row.label_en, row.label_zh),
        href: contentValue(row.href),
        openInNewTab: Number(row.open_in_new_tab) > 0,
        isVisible: Number(row.is_visible) > 0,
      }))
      .filter((item) => item.isVisible && hasLocalizedText(item.labelText) && Boolean(item.href))
      .map(({ isVisible: _isVisible, ...item }) => item);
  } catch {
    return FALLBACK_NAV_ITEMS;
  }
}
