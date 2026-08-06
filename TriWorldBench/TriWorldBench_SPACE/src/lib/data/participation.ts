import { getDb } from "@/lib/db";
import { all } from "@/lib/db/helpers";
import type { ParticipationInfo } from "@/lib/db/schema";

export function getParticipationInfo(): ParticipationInfo[] {
  return all<ParticipationInfo>(
    getDb().prepare("SELECT * FROM participation_info ORDER BY sort_order, id")
  );
}
