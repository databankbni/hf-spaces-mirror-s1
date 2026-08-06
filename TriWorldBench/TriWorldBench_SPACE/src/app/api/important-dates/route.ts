import { NextResponse } from "next/server";
import { getImportantDates } from "@/lib/data/important-dates";

export function GET() {
  return NextResponse.json({ items: getImportantDates() });
}
