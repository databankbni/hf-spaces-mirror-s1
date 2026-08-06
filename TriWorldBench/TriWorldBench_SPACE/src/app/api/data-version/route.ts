import { NextResponse } from "next/server";
import { getDb } from "@/lib/db";
import { get as dbGet } from "@/lib/db/helpers";

export function GET() {
  const row = dbGet<{ version: number; updated_at: string }>(
    getDb().prepare("SELECT version, updated_at FROM data_version WHERE id = 1")
  );
  return NextResponse.json(row || { version: 1, updated_at: "" });
}
