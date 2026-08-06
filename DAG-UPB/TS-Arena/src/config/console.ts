/**
 * The user console is a separate deployment on its own domain
 * (`console.ts-arena.live` for TS-Arena itself), so its URL differs per
 * environment and must not be hardcoded — a baked-in prod URL would send
 * anyone testing the dev site to the production console.
 *
 * Resolved from `CONSOLE_URL` on the server and passed down as a prop, the
 * same way `hasNews()` is. Note that the pages carrying the console links
 * (`/`, `/add-model`) are statically prerendered, so this is read at *build*
 * time — on Coolify `CONSOLE_URL` has to be marked as a build variable, like
 * `NEWS_CONTENT_REPO`, or the build will not see it.
 *
 * Unset means this instance has no console — every console entry point then
 * disappears and `/add-model` falls back to the email route. That is the
 * right default for a fork: the console is a separate service a self-hoster
 * may well not run.
 */
export function getConsoleUrl(): string | null {
  const url = process.env.CONSOLE_URL?.trim();
  if (!url) return null;
  return url.replace(/\/+$/, '');
}
