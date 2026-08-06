import { NextRequest, NextResponse } from "next/server";
import { getLeaderboard } from "@/lib/data/leaderboard";

export function GET(req: NextRequest) {
  const snapshot = req.nextUrl.searchParams.get("snapshot");
  return NextResponse.json(getLeaderboard(snapshot));
}
