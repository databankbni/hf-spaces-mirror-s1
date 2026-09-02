---
title: TS-Arena
emoji: 🚀
colorFrom: red
colorTo: red
sdk: docker
pinned: false
app_port: 3000
short_description: Time Series Forecasting Arena
---
# TS-Arena Frontend

## Concept

TS-Arena is a live forecasting benchmarking platform designed for **pre-registered forecasts into the real future**. This approach ensures rigorous, information leakage-free evaluations by comparing model predictions against data that did not exist at the time of the forecast.


For more information visit our [Git repository](https://github.com/DAG-UPB/ts-arena) or have a look at our KDD '26 paper at [doi.org/10.1145/3770855.3817515](https://doi.org/10.1145/3770855.3817515).

## Build paths

This repository is built two different ways, and anything build-related has to keep
working under both:

| Path | Used by | Build | Start |
|---|---|---|---|
| `Dockerfile` | the Hugging Face Space (`sdk: docker` above, pushed by `.github/workflows/main.yml` on every `main` push) | `npm run build` with `NEXT_OUTPUT_STANDALONE=1` | `node server.js` on port 3000 |
| Nixpacks | the Coolify apps (dev and prod) | `npm run build` | `npm start` → `next start` on `$PORT` |

Nixpacks never reads the `Dockerfile`, so the two paths share only what the npm scripts
do. That is why `scripts/fetch-news.mjs` hangs off the `prebuild` hook instead of living
in the `Dockerfile` — put a build step in an npm script and both paths get it.

`output: "standalone"` in `next.config.ts` is opt-in through `NEXT_OUTPUT_STANDALONE`,
which only the `Dockerfile` sets. It produces the slim `.next/standalone` bundle that the
image runs; `next start` cannot serve that bundle, so the Nixpacks path must be built
without it.

## News section

`/news` renders platform announcements from Markdown files in `content/news/`. That
directory is **not** part of this repository — it is populated from a separate content
repo when the image is built, so an instance you run does not inherit TS-Arena's own
announcements. With no content repo configured, the directory stays empty and the News
tab does not appear.

Point a build at a content repo with two **build-time environment variables**:

| Variable | Default | Meaning |
|---|---|---|
| `NEWS_CONTENT_REPO` | *(empty)* | Clone URL of the content repo. Empty = no news section. |
| `NEWS_CONTENT_REF` | `main` | Branch or tag to clone. |

The clone is done by `scripts/fetch-news.mjs`, wired up as the `prebuild` npm script so it
runs on every `npm run build`. That is deliberate: the Coolify apps build with Nixpacks,
which never reads the `Dockerfile`, and `prebuild` is the one hook both build paths share.
On Coolify these must be marked as **build variables**, not just runtime env vars, or the
build will not see them.

For a **private** content repo, put an access token in the URL
(`https://<token>@github.com/<org>/<repo>.git`). Note that the token is then recorded in
the built image. TS-Arena's own deployment accepts that: the images never leave internal
hosts, and anyone with Docker access there can read the content repo anyway. If you run
an instance where that is not true, use a public repo or a read-only token you are willing
to rotate.

A clone failure fails the build rather than silently shipping a site with no
announcements.

The content repo is just Markdown files at its root, one per post. The file name is the
URL slug (`elo-to-arena-score.md` → `/news/elo-to-arena-score`):

```markdown
---
title: Ranking switches from Elo to Arena Score
date: 2026-07-23
summary: Optional one-line teaser shown in the listing.
author: Optional byline
draft: true
---

Body in Markdown. Headings, lists, links, tables, code and block quotes are styled.
```

`title` and `date` are required; a post missing either is skipped with a build warning.
Posts are listed newest first by `date`.

`draft: true` keeps a post out of the build entirely — no page, no route, no listing entry
— so unfinished posts can sit in the content repo next to the published ones. Drop the
line (or set it to `false`) to publish on the next redeploy. The draft's Markdown file is
still copied into the image, it is just never rendered or routed; treat drafts as hidden
from site visitors, not as a secret from anyone who can read the image.

Publishing a post is a push to the content repo followed by a redeploy of the frontend —
the Markdown is baked into the image, so a rebuild is what makes a new post appear.

For local development, drop `.md` files straight into `content/news/` (it is gitignored)
and run `npm run dev`.

## Logging

Server-side output goes through `src/lib/logger.ts`, which writes one line per
event in the same shape the platform's Python services use:

```
2026-08-17T09:12:44.317Z | INFO | /api/v1/rounds | message
```

Timestamps are ISO-8601 in UTC, so a log window can be dated regardless of the
container's clock zone.

| Variable | Default | Meaning |
|---|---|---|
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARN` or `ERROR`, case-insensitive. An unrecognised value falls back to `INFO` rather than failing to start. |

This is a **runtime** variable — unlike `NEWS_CONTENT_REPO` and `CONSOLE_URL` it
is read on every call, so changing it takes effect on restart without a rebuild.

The API routes under `src/app/api/v1/` proxy the dashboard-api. Each one logs
the upstream request it makes at `DEBUG`, which is off by default: at `INFO` a
healthy site is silent and only failures appear. Set `LOG_LEVEL=DEBUG` to trace
requests while debugging, and turn it back off afterwards — it is one line per
proxied call, and a single chart view makes several.

Two things are deliberately never logged, at any level: the dashboard-api base
URL, which is internal topology that does not belong on the stdout of a
public-facing service, and the API key.

Client-side code keeps using `console.warn`/`console.error` directly. Those
land in the browser's console, which supplies its own timestamps and severity.

`/api/client-error` is separate: it is the sink the error boundaries POST to,
it writes its own structured `CLIENT ERROR:` line, and it rate-limits itself.
It is not affected by `LOG_LEVEL` — a crash report must never be filtered out.

## User console

Participants create an account, manage their organization and mint their own API keys in
the **user console**, a separate app on its own domain (`console.ts-arena.live` for
TS-Arena itself). This site only links to it:

| Variable | Default | Meaning |
|---|---|---|
| `CONSOLE_URL` | *(empty)* | Base URL of the console, no trailing slash. Empty = no console. |

It is read on the server, but the pages that link to the console (`/`, `/add-model`) are
statically prerendered, so the value is baked in at **build** time. On Coolify it must
therefore be marked as a **build variable**, like `NEWS_CONTENT_REPO`, or the build will
not see it and the links will silently not appear. The URL differs per environment, which
is why it is not hardcoded: a baked-in production URL would send anyone testing a staging
deployment to the live console.

Leave it unset and every console entry point disappears — the nav item, the footer link,
and the self-service copy on `/add-model`, which then falls back to asking for an API key
by email. That is the right default for a fork: the console is a separate service you may
well not be running.
