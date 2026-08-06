import { NextResponse } from "next/server";
import { getSnapshotHistory } from "@/lib/data/leaderboard";

export function GET() {
  return NextResponse.json({ snapshots: getSnapshotHistory() });
}
