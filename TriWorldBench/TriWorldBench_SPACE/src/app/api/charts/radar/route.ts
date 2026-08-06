import { NextRequest, NextResponse } from "next/server";
import { getRadarData } from "@/lib/data/leaderboard";

export function GET(req: NextRequest) {
  const metricsParam = req.nextUrl.searchParams.get("metrics");
  const topParam = req.nextUrl.searchParams.get("top");
  const metricCodes = metricsParam
    ? metricsParam.split(",").map((s) => s.trim()).filter(Boolean)
    : undefined;
  const top = topParam ? Number(topParam) : 8;
  return NextResponse.json(getRadarData(metricCodes, top));
}
