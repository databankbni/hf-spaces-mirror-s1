import { NextRequest, NextResponse } from "next/server";
import { getModelScores } from "@/lib/data/leaderboard";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ modelId: string }> }
) {
  const { modelId } = await params;
  const result = getModelScores(modelId);
  if (!result.model) {
    return NextResponse.json({ error: "model not found" }, { status: 404 });
  }
  return NextResponse.json(result);
}
