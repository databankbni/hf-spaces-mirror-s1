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

TeamTracker is a full project and team tracking app built for monthly planning, task execution, and lightweight team coordination. It brings together the board, dashboard, member management, project discussions, and an AI assistant in a single workflow.

## What’s included

- Kanban board with task status columns
- Role-based access control for viewers, editors, and admins
- Monthly planning and sprint tracking
- Team member management and assignment
- Dashboard analytics and workload reporting
- Personal calendar for per-user scheduling
- Floating project assistant for task, sprint, and project queries
- Safe mutation flow that asks for confirmation before changing project data

## Tech stack

- Backend: Node.js + Express + TypeScript
- Frontend: React + Radix UI + Phosphor Icons
- Database: SQLite via better-sqlite3
- Auth: JWT in HTTP-only cookies + bcrypt
- Build: esbuild + TypeScript

## Roles

| Role    | Access                                                      |
| ------- | ----------------------------------------------------------- |
| Guest   | Can view public information only                            |
| Pending | Logged in but not approved                                  |
| Viewer  | Sees their own work and shared project data                 |
| Editor  | Can manage tasks and team content for assigned work         |
| Admin   | Full control over members, roles, approvals, and management |

The first registered user becomes the admin automatically.

## Local setup

```bash
git clone <repo-url>
cd TeamTracker
npm install
cp .env.example .env
```

Edit `.env` and set at least:

```env
JWT_SECRET=your-long-random-secret
NODE_ENV=production
PORT=3333
DB_PATH=/data/teamtracker.db
GEMINI_API_KEY=your_key_here
```

For Hugging Face Spaces, keep `DB_PATH=/data/teamtracker.db` so the SQLite database persists across rebuilds and restarts. If the Space has persistent storage mounted at `/data`, this keeps users, tasks, and project data from being wiped during deploys.

### Space recovery setup

If the Space has already been reset and you need a fresh admin account:

```bash
npm run create-admin
```

This creates a default admin user if the database is empty. You can also set:

```env
ADMIN_USERNAME=admin
ADMIN_EMAIL=admin@teamtracker.local
ADMIN_PASSWORD=admin123
```

If you want a non-default login, set those values before running the command.

Then run:

```bash
npm run build
npm start
```

The app runs by default at:

```text
http://localhost:3333
```

## Development commands

```bash
# build the client
npm run build:client

# build the server
npm run build:server

# full build
npm run build

# start local app
npm start

# run tests
npm test
```

## Deployment notes

This project is designed for a standard Node.js deployment and is not dependent on Docker, Procfile, or Railway config files.

You can deploy it to any host that supports Node.js and keeps the app running continuously, including:

- a VPS / VM
- a simple Node host
- a managed platform that runs `npm install` and `npm start`
- a Hugging Face Space using a standard Node startup flow if your host supports it

For production, make sure these are configured:

- `JWT_SECRET`
- `NODE_ENV=production`
- `PORT` if your host requires it
- `GEMINI_API_KEY` if you want the AI assistant to use Gemini

SQLite persistence is file-based, so the database needs a persistent storage path on your host if you deploy remotely.

## Project structure

```text
TeamTracker/
  src/
    client/
    server/
    shared/
  public/
  .env.example
  .gitignore
  package.json
  tsconfig.json
  tsconfig.server.json
  esbuild.config.js
  vitest.config.ts
```

## Important notes

- The app stores data in SQLite.
- The database file is created in the local project or the configured `DB_PATH` location.
- The AI assistant is project-aware and can help with summaries and safe task-related actions, but actual mutations require confirmation and proper access.
- The repo intentionally keeps deployment config minimal and platform-neutral.

## License

This project is for internal/team usage and is not a packaged SaaS product unless you explicitly add your own license and hosting terms.
