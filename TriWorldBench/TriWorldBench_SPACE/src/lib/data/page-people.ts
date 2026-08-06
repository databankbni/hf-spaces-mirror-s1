import { getDb } from "@/lib/db";
import { all } from "@/lib/db/helpers";
import type { PageAffiliation, PageAuthor } from "@/lib/db/schema";
import { hasLocalizedText, localized } from "@/lib/i18n";

const FALLBACK_AUTHORS: PageAuthor[] = [];

const FALLBACK_AFFILIATIONS: PageAffiliation[] = ([
  ["1", "Peking University", "北京大学", "/institution-logos/pku.png", "https://www.pku.edu.cn/"],
  ["2", "Tsinghua University", "清华大学", "/institution-logos/tsinghua.png", "https://www.tsinghua.edu.cn/"],
  ["3", "Beihang University", "北京航空航天大学", "/institution-logos/buaa.png", "https://www.buaa.edu.cn/"],
  ["4", "Shanghai Jiao Tong University", "上海交通大学", "/institution-logos/sjtu.png", "https://www.sjtu.edu.cn/"],
  ["5", "University of Science and Technology of China", "中国科学技术大学", "/institution-logos/ustc.png", "https://www.ustc.edu.cn/"],
] as const).map(([ref, name, nameZh, logoPath, websiteUrl], index) => ({
  id: index + 1,
  ref,
  name,
  name_en: name,
  name_zh: nameZh,
  logo_path: logoPath,
  website_url: websiteUrl,
  sort_order: index + 1,
  updated_at: "",
  nameText: localized(name, nameZh),
}));

function uniqueByLocalizedName<T extends { name: string; name_en?: string | null }>(rows: T[]): T[] {
  const seen = new Set<string>();
  return rows.filter((row) => {
    const key = (row.name_en || row.name).trim().toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function getPageAuthors(): PageAuthor[] {
  try {
    const rows = all<PageAuthor>(getDb().prepare("SELECT * FROM page_authors ORDER BY sort_order, id"));
    if (!rows.length) return FALLBACK_AUTHORS;
    return uniqueByLocalizedName(rows)
      .map((row) => ({
        ...row,
        nameText: localized(row.name_en || row.name, row.name_zh),
      }))
      .filter((row) => hasLocalizedText(row.nameText));
  } catch {
    return FALLBACK_AUTHORS;
  }
}

export function getPageAffiliations(): PageAffiliation[] {
  try {
    const rows = all<PageAffiliation>(getDb().prepare("SELECT * FROM page_affiliations ORDER BY sort_order, id"));
    if (!rows.length) return FALLBACK_AFFILIATIONS;
    return uniqueByLocalizedName(rows)
      .map((row) => ({
        ...row,
        nameText: localized(row.name_en || row.name, row.name_zh),
      }))
      .filter((row) => hasLocalizedText(row.nameText));
  } catch {
    return FALLBACK_AFFILIATIONS;
  }
}
