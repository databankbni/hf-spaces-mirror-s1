import { getDb } from "@/lib/db";
import { get as dbGet } from "@/lib/db/helpers";
import type { VenueHostInfo } from "@/lib/db/schema";

export function getVenueHost(): VenueHostInfo | null {
  return dbGet<VenueHostInfo>(getDb().prepare("SELECT * FROM venue_host_info ORDER BY id LIMIT 1"));
}
