/** Parse a JSON string field on a row object, replacing the _json suffix key */
export function parseJsonField<T = unknown>(
  row: Record<string, unknown> | null,
  field: string
): Record<string, unknown> | null {
  if (!row || !row[field]) return row;
  try {
    const cleanKey = field.replace(/_json$/, "");
    (row as Record<string, unknown>)[cleanKey] = JSON.parse(
      row[field] as string
    );
    delete row[field];
  } catch {
    (row as Record<string, unknown>)[field.replace(/_json$/, "")] = [];
    delete row[field];
  }
  return row;
}

/** Determine if a date range is upcoming, live, or closed */
export function getDateStatus(
  startsAt: string,
  endsAt?: string | null
): "upcoming" | "live" | "closed" {
  const now = new Date();
  const start = new Date(startsAt);
  const end = endsAt ? new Date(endsAt) : start;
  if (now < start) return "upcoming";
  if (now >= start && now <= end) return "live";
  return "closed";
}

/** Slugify a string: lowercase, replace non-alphanumeric with dashes */
export function slugify(value: string): string {
  return String(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

/** Clamp a number between min and max */
export function clamp(value: number, min = 0, max = 100): number {
  return Math.max(min, Math.min(max, Number(value.toFixed(2))));
}
