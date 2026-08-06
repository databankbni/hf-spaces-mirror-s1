import { NextResponse } from "next/server";
import { getSiteAndHero } from "@/lib/data/site-info";

export function GET() {
  return NextResponse.json(getSiteAndHero());
}
