// SPA mode — render entirely client-side so the static build is just the
// index.html fallback shell that talks to the FastAPI backend over /api.
// Prerendering is off because dynamic routes ([game], [id], [abbr]) are
// resolved client-side; the FastAPI catch-all serves the shell for them.
export const ssr = false;
export const prerender = false;
export const trailingSlash = 'never';
