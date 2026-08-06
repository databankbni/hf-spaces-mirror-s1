---
title: TeamTracker
emoji: 📋
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# TeamTracker

Standalone team work tracking and reporting web app.  
**Public dashboard, authenticated editing.** Anyone can view the board and dashboard. Only approved editors can create, edit, or delete tasks/sprints/members.

## Tech Stack

- **Backend**: Node.js + Express + TypeScript
- **Frontend**: React 18 + Radix UI Themes + Phosphor Icons + Recharts
- **Database**: SQLite via better-sqlite3
- **Auth**: JWT (httpOnly cookies) + bcrypt password hashing
- **Bundler**: esbuild

## Features

- **Kanban board** — drag cards between Todo / In Progress / Review / Done
- **Task management** — create, edit, delete tasks with title, description, status, priority, assignee, sprint, and labels
- **Sprint management** — create sprints, set dates, track status
- **Team members** — add/remove team members with auto-assigned avatar colors
- **Dashboard** — velocity chart, tasks-by-status pie chart, work distribution by assignee, summary stats
- **Auth** — register/login with username + password, first user becomes admin automatically
- **Access control** — public read-only view; editors/admins can write; admins manage user approvals

## Roles

| Role | Can do |
|------|--------|
| (unauthenticated) | View board, dashboard, sprints, members |
| `pending` | Logged in but not yet approved |
| `editor` | Full create/edit/delete on tasks, sprints, members |
| `admin` | Everything editors can do + manage users (approve, change roles, delete) |

The **first user to register** is automatically made admin. All subsequent registrations start as `pending` and need admin approval.

## Setup

```bash
# Install dependencies
npm install

# Copy env template
cp .env.example .env
# Edit .env — at minimum set JWT_SECRET for production

# Build and start
npm run build
npm start
```

The app runs at **http://localhost:3333** by default.

## Deploying publicly (Railway / Render / Fly.io)

1. Set these environment variables in your hosting dashboard:
   - `JWT_SECRET` — a long random secret (generate: `node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"`)
   - `NODE_ENV=production`
   - `PORT` — usually set automatically by the platform

2. For **Railway**: the existing `Procfile` and `railway.json` are already configured.

3. For **Render**: set the build command to `npm run build` and start command to `npm start`.

4. SQLite persistence: on Railway/Render free tiers the filesystem is ephemeral. Use a mounted volume (Railway Volume / Render Disk) and set `DB_PATH` to point to it, e.g. `/data/teamtracker.db`.

## Development

```bash
# Rebuild server after server changes
npm run build:server && npm start

# Rebuild client after client changes
npm run build:client && npm start

# Rebuild everything
npm run build && npm start
```

## Data

SQLite database is stored at `data/teamtracker.db` (overridable with `DB_PATH` env var).

## Project Structure

```
src/
  server/
    middleware/   auth.ts — JWT extraction, requireAuth, requireAdmin
    routes/       tasks, members, sprints, reports, auth
    storage/      db, tasks, members, sprints, reports, users
  client/
    components/   KanbanBoard, TaskCard, TaskDialog, Dashboard,
                  SprintPanel, MembersPanel, LoginPage, AdminPanel
    hooks/        useAuth.tsx — auth context
    api.ts        HTTP client
    App.tsx       Root with auth-gated navigation
    index.tsx     Entry point
  shared/
    types.ts      Shared TypeScript interfaces
public/
  index.html      HTML shell
  bundle.js       Built client (generated)
data/
  teamtracker.db  SQLite database (generated)
```
