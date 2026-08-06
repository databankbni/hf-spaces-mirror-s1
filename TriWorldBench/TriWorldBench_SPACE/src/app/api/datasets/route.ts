import { NextResponse } from "next/server";
import { getDatasetsWithVersions } from "@/lib/data/datasets";

export function GET() {
  return NextResponse.json(getDatasetsWithVersions());
}
