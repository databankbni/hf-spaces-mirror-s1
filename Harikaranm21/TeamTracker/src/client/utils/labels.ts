/**
 * Label parsing utilities — handles the comma-separated labels string.
 * @module utils/labels
 */

/** Parses a comma-separated labels string into a trimmed, deduped array. */
export function parseLabels(raw: string | null | undefined): string[] {
  if (!raw) return [];
  return [...new Set(raw.split(',').map((l) => l.trim()).filter(Boolean))];
}

/** Serialises a label array back to a comma-separated string. */
export function serializeLabels(labels: string[]): string {
  return labels.map((l) => l.trim()).filter(Boolean).join(', ');
}
