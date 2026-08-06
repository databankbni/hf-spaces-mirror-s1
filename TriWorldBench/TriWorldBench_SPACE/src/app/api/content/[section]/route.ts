import { NextRequest, NextResponse } from "next/server";
import { getDb } from "@/lib/db";
import { all, get as dbGet } from "@/lib/db/helpers";
import { parseJsonField } from "@/lib/utils";

const SECTION_MAP: Record<string, () => unknown[]> = {
  hero: () => all(getDb().prepare("SELECT * FROM hero_content ORDER BY id")),
  overview: () =>
    all<Record<string, unknown>>(getDb().prepare("SELECT * FROM overview_content ORDER BY id"))
      .map((row) => parseJsonField(row, "stat_json")),
  evaluation: () => all(getDb().prepare("SELECT * FROM evaluation_sections ORDER BY sort_order, id")),
  research: () =>
    all<Record<string, unknown>>(getDb().prepare("SELECT * FROM research_sections ORDER BY sort_order, id"))
      .map((row) => parseJsonField(row, "tags_json")),
  participation: () => all(getDb().prepare("SELECT * FROM participation_info ORDER BY sort_order, id")),
  venue: () => all(getDb().prepare("SELECT * FROM venue_host_info ORDER BY id")),
  policies: () => all(getDb().prepare("SELECT * FROM policy_items ORDER BY sort_order, id")),
  contact: () => all(getDb().prepare("SELECT * FROM contact_info ORDER BY sort_order, id")),
  other: () => all(getDb().prepare("SELECT * FROM other_information ORDER BY id")),
  announcements: () =>
    all(getDb().prepare("SELECT * FROM announcements ORDER BY published_at DESC, id DESC")),
  "academic-references": () =>
    all<Record<string, unknown>>(getDb().prepare("SELECT * FROM academic_references ORDER BY sort_order, id"))
      .map((row) => parseJsonField(row, "tags_json")),
  "metric-explanations": () => all(getDb().prepare("SELECT * FROM metric_explanations ORDER BY id")),
};

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ section: string }> }
) {
  const { section } = await params;
  const handler = SECTION_MAP[section];
  if (!handler) return NextResponse.json({ error: "unknown section" }, { status: 404 });
  return NextResponse.json({ section, items: handler() });
}
