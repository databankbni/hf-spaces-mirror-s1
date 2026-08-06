import { getDb } from "@/lib/db";
import { get as dbGet } from "@/lib/db/helpers";
import type { SiteInfo, HeroContent } from "@/lib/db/schema";

export function getSiteInfo(): SiteInfo | null {
  return dbGet<SiteInfo>(getDb().prepare("SELECT * FROM site_info WHERE id = 1"));
}

export function getHeroContent(): HeroContent | null {
  return dbGet<HeroContent>(getDb().prepare("SELECT * FROM hero_content ORDER BY id LIMIT 1"));
}

export function getSiteAndHero(): { site: SiteInfo | null; hero: HeroContent | null } {
  return { site: getSiteInfo(), hero: getHeroContent() };
}
