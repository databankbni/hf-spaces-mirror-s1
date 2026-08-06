import { getDb } from "@/lib/db";
import { all, get } from "@/lib/db/helpers";
import { contentValue, hasLocalizedText, localized, type LocalizedText } from "@/lib/i18n";

export interface SubmissionGuideMeta {
  eyebrowText: LocalizedText;
  titleText: LocalizedText;
  introText: LocalizedText;
  backLabelText: LocalizedText;
  backHref: string;
}

export interface SubmissionGuideNavItem {
  id: number;
  itemKey: string;
  labelText: LocalizedText;
  href: string;
}

export interface SubmissionGuideSection {
  id: number;
  sectionKey: string;
  titleText: LocalizedText;
  bodyText: LocalizedText;
}

export interface HomepageEntrySection {
  id: number;
  sectionKey: string;
  titleText: LocalizedText;
  bodyText: LocalizedText;
  actionLabelText: LocalizedText;
  actionHref: string;
}

interface MetaRow {
  eyebrow_en: string;
  eyebrow_zh: string;
  title_en: string;
  title_zh: string;
  intro_en: string;
  intro_zh: string;
  back_label_en: string;
  back_label_zh: string;
  back_href: string;
}

interface NavRow {
  id: number;
  item_key: string;
  label_en: string;
  label_zh: string;
  href: string;
}

interface SectionRow {
  id: number;
  section_key: string;
  title_en: string;
  title_zh: string;
  body_en: string;
  body_zh: string;
}

interface EntryRow extends SectionRow {
  action_label_en: string;
  action_label_zh: string;
  action_href: string;
}

export function getSubmissionGuideMeta(): SubmissionGuideMeta | null {
  const row = get<MetaRow>(getDb().prepare("SELECT * FROM triworld_submission_guide_meta WHERE id = 1"));
  if (!row) return null;
  return {
    eyebrowText: localized(row.eyebrow_en, row.eyebrow_zh),
    titleText: localized(row.title_en, row.title_zh),
    introText: localized(row.intro_en, row.intro_zh),
    backLabelText: localized(row.back_label_en, row.back_label_zh),
    backHref: contentValue(row.back_href) || "/",
  };
}

export function getSubmissionGuideNavItems(): SubmissionGuideNavItem[] {
  return all<NavRow>(
    getDb().prepare(
      "SELECT * FROM triworld_submission_guide_nav_items WHERE is_visible = 1 ORDER BY sort_order, id"
    )
  )
    .map((row) => ({
      id: row.id,
      itemKey: row.item_key,
      labelText: localized(row.label_en, row.label_zh),
      href: contentValue(row.href),
    }))
    .filter((row) => hasLocalizedText(row.labelText) && Boolean(row.href));
}

export function getSubmissionGuideSections(): SubmissionGuideSection[] {
  return all<SectionRow>(
    getDb().prepare(
      "SELECT * FROM triworld_submission_guide_sections WHERE is_visible = 1 ORDER BY sort_order, id"
    )
  )
    .map((row) => ({
      id: row.id,
      sectionKey: row.section_key,
      titleText: localized(row.title_en, row.title_zh),
      bodyText: localized(row.body_en, row.body_zh),
    }))
    .filter((row) => hasLocalizedText(row.titleText) || hasLocalizedText(row.bodyText));
}

export function getHomepageEntrySections(): HomepageEntrySection[] {
  return all<EntryRow>(
    getDb().prepare(
      "SELECT * FROM triworld_entry_sections WHERE is_visible = 1 ORDER BY sort_order, id"
    )
  )
    .map((row) => ({
      id: row.id,
      sectionKey: row.section_key,
      titleText: localized(row.title_en, row.title_zh),
      bodyText: localized(row.body_en, row.body_zh),
      actionLabelText: localized(row.action_label_en, row.action_label_zh),
      actionHref: contentValue(row.action_href),
    }))
    .filter((row) =>
      hasLocalizedText(row.titleText) ||
      hasLocalizedText(row.bodyText) ||
      (hasLocalizedText(row.actionLabelText) && Boolean(row.actionHref))
    );
}
