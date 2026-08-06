import { getDb } from "@/lib/db";
import { all } from "@/lib/db/helpers";
import type { Announcement } from "@/lib/db/schema";

export function getAnnouncements(): Announcement[] {
  return all<Announcement>(
    getDb().prepare("SELECT * FROM announcements ORDER BY published_at DESC, id DESC")
  );
}
