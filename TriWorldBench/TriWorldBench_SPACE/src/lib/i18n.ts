export type Language = "en" | "zh";

export interface LocalizedText {
  en: string;
  zh: string;
}

export const EMPTY_CONTENT_MARKER = "#empty#";

export function isEmptyContentMarker(value: string | null | undefined): boolean {
  if (typeof value !== "string") return false;
  const normalized = value.trim().toLowerCase();
  return normalized === EMPTY_CONTENT_MARKER || /^#empty#[。．.!！?？,，;；:：、…]*$/i.test(normalized);
}

export function contentValue(value: string | null | undefined): string {
  if (!value || isEmptyContentMarker(value) || !value.trim()) return "";
  return value;
}

export function hasLocalizedText(text: LocalizedText | null | undefined): boolean {
  return Boolean(contentValue(text?.en) || contentValue(text?.zh));
}

export function localized(en: string | null | undefined, zh?: string | null): LocalizedText {
  const english = contentValue(en);
  const chineseIsEmptyMarker = isEmptyContentMarker(zh);
  const chinese = contentValue(zh);
  return {
    en: english,
    zh: chinese || (chineseIsEmptyMarker ? "" : english),
  };
}
