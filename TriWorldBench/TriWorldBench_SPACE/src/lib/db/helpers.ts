/**
 * Type-safe helpers for node:sqlite queries.
 * node:sqlite returns Record<string, SQLOutputValue>[], so we need
 * double-casting through unknown for TypeScript compatibility.
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function all<T>(stmt: { all(...params: any[]): unknown[] }, ...params: unknown[]): T[] {
  return stmt.all(...params) as unknown as T[];
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function get<T>(stmt: { get(...params: any[]): unknown }, ...params: unknown[]): T | null {
  return (stmt.get(...params) as T) ?? null;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function run(stmt: { run(...params: any[]): unknown }, ...params: unknown[]): { lastInsertRowid: number | bigint; changes: number } {
  return stmt.run(...params) as unknown as { lastInsertRowid: number | bigint; changes: number };
}
