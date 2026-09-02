/**
 * Minimal levelled logger.
 *
 * Everything this app writes to stdout ends up in one undated stream in the
 * container log, mixed in with whatever the runtime says. A bare `console.log`
 * carries no time and no severity, so a log window cannot even be dated, let
 * alone filtered. This module gives every surviving line both.
 *
 * Line format, deliberately the same shape the platform's Python services use
 * (`%(asctime)s | %(levelname)s | %(name)s | %(message)s`), so one habit reads
 * every service:
 *
 *     2026-08-17T09:12:44.317Z | INFO | /api/v1/rounds | message
 *
 * Timestamps are ISO-8601 in UTC. Container clocks are not reliably in any
 * particular zone and the rest of the platform reasons in UTC.
 *
 * Verbosity comes from the `LOG_LEVEL` environment variable — `DEBUG`, `INFO`,
 * `WARN` or `ERROR`, case-insensitive, defaulting to `INFO`. Per-request
 * tracing in the API routes is logged at `DEBUG`, so it is off unless someone
 * turns it on. An unrecognised value falls back to the default rather than
 * throwing: a typo in an env var must never take the site down.
 *
 * Two rules for callers:
 *
 * - **Never log the upstream base URL.** The dashboard-api address is internal
 *   topology and has no business on the stdout of a public-facing service. Log
 *   the path, not the host.
 * - **Never log an API key, a header, or a request body.**
 *
 * `console.*` is still the sink underneath — under `next start` stdout is the
 * only place a line can go, and adding a transport would buy nothing.
 */

export type LogLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';

const SEVERITY: Record<LogLevel, number> = {
  DEBUG: 10,
  INFO: 20,
  WARN: 30,
  ERROR: 40,
};

const DEFAULT_LEVEL: LogLevel = 'INFO';

function parseLevel(raw: string | undefined): LogLevel {
  if (!raw) return DEFAULT_LEVEL;
  const name = raw.trim().toUpperCase();
  // `WARNING` is what the Python services call it; accept both spellings.
  if (name === 'WARNING') return 'WARN';
  return name in SEVERITY ? (name as LogLevel) : DEFAULT_LEVEL;
}

/**
 * Read per call rather than once at module load. This module is evaluated
 * during the build for statically prerendered routes, where the runtime
 * environment does not exist yet — a value captured then would be wrong.
 *
 * In the browser bundle `LOG_LEVEL` is not exposed (it is not `NEXT_PUBLIC_`),
 * so client-side logging always runs at the default level.
 */
function activeLevel(): LogLevel {
  if (typeof process === 'undefined') return DEFAULT_LEVEL;
  return parseLevel(process.env.LOG_LEVEL);
}

/** Render one extra argument as a single line. */
function render(value: unknown): string {
  if (value instanceof Error) return `${value.name}: ${value.message}`;
  if (typeof value === 'string') return value;
  if (value === undefined) return '';
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}

function emit(level: LogLevel, name: string, message: string, args: unknown[]): void {
  if (SEVERITY[level] < SEVERITY[activeLevel()]) return;

  const detail = args.map(render).filter((part) => part.length > 0);
  const line = [
    `${new Date().toISOString()} | ${level} | ${name} | ${message}`,
    ...detail,
  ].join(' ');

  // WARN and ERROR go to stderr, which is how a reader tells them apart when
  // the two streams are separated.
  if (level === 'ERROR') console.error(line);
  else if (level === 'WARN') console.warn(line);
  else console.log(line);
}

export interface Logger {
  debug(message: string, ...args: unknown[]): void;
  info(message: string, ...args: unknown[]): void;
  warn(message: string, ...args: unknown[]): void;
  error(message: string, ...args: unknown[]): void;
}

/**
 * @param name Where the line came from, shown as the third field. For an API
 * route that is its own path, e.g. `/api/v1/rounds/[roundId]/leaderboard`.
 */
export function createLogger(name: string): Logger {
  return {
    debug: (message, ...args) => emit('DEBUG', name, message, args),
    info: (message, ...args) => emit('INFO', name, message, args),
    warn: (message, ...args) => emit('WARN', name, message, args),
    error: (message, ...args) => emit('ERROR', name, message, args),
  };
}
