# TeamTracker — Complete Guide

This guide reflects the current TeamTracker application as it exists in the codebase today: a Node.js team tracker with a Kanban board, dashboard, member management, personal calendar, project AI assistant, and role-based project access.

## 1. Overview

TeamTracker is a project tracking tool for teams that need monthly planning, task control, and lightweight team coordination in one place. It supports:

- task tracking by status and assignee
- sprint/month planning
- dashboard reporting
- personal calendars
- admin approval and role management
- a floating AI assistant that summarizes project state and can help trigger safe updates

The app is designed to be simple, browser-based, and easy to run locally without Docker or platform-specific deployment files.

---

## 2. Feature summary

| Feature           | Details                                                        |
| ----------------- | -------------------------------------------------------------- |
| Kanban board      | To Do, In Progress, Review, Done columns                       |
| Task controls     | Create, edit, move, assign, delete, due dates                  |
| Project data      | Months, members, teams, tasks, comments                        |
| Dashboard         | Stats, workload, status distribution, sprint trends            |
| Personal calendar | User-specific blocks and time planning                         |
| Access control    | Viewer, editor, admin enforcement                              |
| AI assistant      | Project-aware chat assistant with confirmation before mutation |
| Admin tools       | User approval, role changes, cleanup utilities                 |

---

## 3. Roles and permissions

| Role    | What they can do                                              |
| ------- | ------------------------------------------------------------- |
| Guest   | View public app pages only                                    |
| Pending | Logged in, but waiting for approval                           |
| Viewer  | Access their own tasks and shared project data                |
| Editor  | Manage assigned work and project updates                      |
| Admin   | Full access to user approval, roles, teams, and admin actions |

The first registered user receives admin access automatically.

---

## 4. Registering and getting started

1. Open the app in the browser.
2. Click Sign in.
3. Switch to Register.
4. Create a username and password.
5. Submit the form.

If you are the first account, you become the admin automatically. Later users begin as pending until approved.

---

## 5. Working with the board

The main workspace is the Kanban board.

### Task columns

Tasks move between:

- To Do
- In Progress
- Review
- Done

### Creating a task

1. Click New Task.
2. Enter title and details.
3. Select assignee, status, priority, month, labels, and due date.
4. Save the task.

### Editing a task

- Open the task card actions.
- Update title, status, assignee, due date, and other values.
- Save changes.

### Moving tasks

- Drag tasks between columns.
- Or update task status from the task edit dialog.

### Task filters

- Search by title, description, label, or assignee.
- Filter by team member or active view.

### Comments

Task comments are available in the task details/edit flow. Admins and editors are typically the ones who can manage task data depending on the permissions model.

---

## 6. Months and sprint planning

Months represent planning periods for the project. Each task can belong to a month/sprint period.

### Typical flow

1. Create or select a month.
2. Assign tasks to that period.
3. Track active versus completed months.
4. Use the dashboard to compare activity and completion trends.

---

## 7. Team members and teams

The app supports team membership and work ownership.

### Add a member

- Create a user account and log in.
- Or add a member manually from the team management flow.

### Assign work

- Select a project member while creating or editing a task.
- Tasks then appear in relevant member filters and workload views.

---

## 8. Dashboard and reporting

The dashboard gives a high-level view of current project health.

Typical dashboard information includes:

- total tasks
- task distribution by status
- workload by assignee
- active months
- velocity and completion trends

This is useful for weekly reviews and planning discussions.

---

## 9. Personal calendar

Each user has a personal calendar view for scheduling work and personal blocks.

Features include:

- per-day scheduling across hours
- event creation by click or drag selection
- event types and colors
- personal calendar blocks separated from shared project data

---

## 10. AI assistant

The app includes a floating project assistant that uses the live project context to answer project questions and help with task-related actions.

### What it can do

- summarize project health
- explain task counts and workload
- answer sprint or team questions using live data
- help prepare task creation requests
- help with updates like rename, due date, status change, assignee changes

### Safety model

The assistant is designed to work conservatively:

- It uses the current project snapshot as context.
- It does not freely mutate project data without confirmation.
- It respects role-based access rules.
- Real writes happen only after user confirmation and permission checks.

This keeps the AI useful while preventing accidental destructive changes.

---

## 11. Admin operations

Admins can manage:

- pending user approval
- role updates
- member and team assignments
- project data cleanup operations
- user management tasks

Cleanup tools are available for maintenance but should be used intentionally because they remove old record sets.

---

## 12. Setup and running locally

### Install

```bash
git clone <repo-url>
cd TeamTracker
npm install
cp .env.example .env
```

### Configure environment

Update `.env` with your settings before running the app.

```env
PORT=3333
JWT_SECRET=replace-with-a-long-random-secret
NODE_ENV=production
GEMINI_API_KEY=your_gemini_api_key_here
```

### Build and run

```bash
npm run build
npm start
```

Open:

```text
http://localhost:3333
```

---

## 13. Development commands

```bash
npm run build:client
npm run build:server
npm run build
npm start
npm test
```

Use the client/server split when you want faster iteration during UI or backend changes.

---

## 14. Deployment model

This repo is intentionally not built around Docker, Procfile, or Railway-specific config.

It is a standard Node.js project, so it can be deployed on:

- a VM or VPS
- a standard Node hosting service
- a platform where the app is started with `npm install` and `npm start`
- a compatible hosting environment with persistent storage for SQLite

If you deploy remotely, ensure:

- the app process remains alive
- `JWT_SECRET` is set
- `NODE_ENV=production` is set
- the database path is persistent if needed

---

## 15. Database and persistence

The app uses SQLite for its database. The default local database is created in the app data location and can also be moved via the configured `DB_PATH` environment variable.

For production hosting, keep the database on persistent storage so it survives restarts.

---

## 16. Common usage examples

### Example 1: update a task status

A user can move the task board card or edit the task and set the new status.

### Example 2: ask the assistant to summarize the project

Use the floating AI assistant to ask:

- What is the current workload?
- Which tasks are overdue?
- Which sprint is active?
- Who is assigned the most tasks?

### Example 3: ask the assistant to create or change a task

The assistant can prepare the action and ask for confirmation before performing it, so the change is deliberate and permission-aware.

---

## 17. Files to know

Important project areas include:

- `src/client/App.tsx` — app shell and navigation
- `src/client/components/ProjectAssistant.tsx` — floating assistant
- `src/client/components/Dashboard.tsx` — dashboard analytics
- `src/server/server.ts` — server boot and routes
- `src/server/routes/` — backend API routes
- `src/server/storage/` — database and persistence logic

---

## 18. Notes for maintainers

- Keep production secrets in `.env` and never commit them.
- Do not rely on generated bundle files as source code.
- Prefer the local Node workflow unless your host specifically requires a different deployment model.
- The newer assistant behavior is part of the live product, so update docs whenever the assistant workflow changes.

---

## _Last updated: 2026-08-31_

## 15. Environment Variables

| Variable     | Purpose            | Value                         |
| ------------ | ------------------ | ----------------------------- |
| `NODE_ENV`   | Environment mode   | `production`                  |
| `PORT`       | Port number        | `7860` (HF) or `3333` (local) |
| `JWT_SECRET` | Login token secret | Long random string            |
| `DB_PATH`    | Database file path | `/data/teamtracker.db`        |

---

## 16. Frequently Asked Questions

**Q: The app is sleeping / slow to load for the first visitor.**
HF free tier sleeps after 48 hours of no activity. The first request wakes it up — takes 20–30 seconds. After that it runs normally.

**Q: I registered but can't edit anything.**
Your account is "Pending". Ask the Admin to approve you from the Users tab.

**Q: I forgot my password.**
If you forgot your password, ask the Admin. The Admin can reset it from the Users tab (key icon next to your name). They set a temporary password → you log in → change it from your profile (user menu → "Change Password").

**Q: How do I change my own password?**
Click your username in the bottom-left sidebar → click **"Change Password"** → enter your current password and new password → save.

**Q: Can multiple people use it at the same time?**
Yes — multiple users can access the HF URL simultaneously.

**Q: My calendar events disappeared.**
Calendar events are personal — only you see yours. Make sure you're logged in with the same account.

**Q: The board shows tasks from everyone — how do I see only mine?**
Use the member filter chips above the board. Click your name to filter to your tasks.

**Q: How do I add someone as a team member?**
Either: (1) They register and log in — they're auto-added as a member, or (2) An editor manually adds them from the Team tab.

**Q: Can I access the app from my phone?**
Yes — the app works in any mobile browser. Go to https://harikaranm21-teamtracker.hf.space on your phone.

---

## 17. Tech Stack (for developers)

| Layer    | Technology                             |
| -------- | -------------------------------------- |
| Backend  | Node.js 18 + Express + TypeScript      |
| Frontend | React 18 + Radix UI + Recharts         |
| Database | SQLite via better-sqlite3              |
| Auth     | JWT tokens (httpOnly cookies) + bcrypt |
| Hosting  | Hugging Face Spaces (Docker)           |
| Storage  | HF Storage Bucket mounted at /data     |
| Source   | GitHub: harikaranm21/TeamTracker       |

---

---

## 18. How to Make Code Changes and Deploy

### The Full Workflow

Every code change follows this exact sequence:

```
Edit file → Build → Test locally → Commit to GitHub → Push to HF → HF rebuilds automatically
```

---

### ⚠️ First Time on a New Laptop — Extra Setup Required

If you're making changes from a **different laptop** (not the one where the project was originally set up), you need to do a one-time setup first:

**Step 1 — Clone the repo:**

```bash
git clone https://github.com/harikaranm21/TeamTracker.git
cd TeamTracker
```

**Step 2 — Install dependencies:**

```bash
npm install
```

**Step 3 — Add the Hugging Face remote** (this is the key step the new laptop doesn't know about):

```bash
git remote add space https://Harikaranm21:YOUR_HF_TOKEN@huggingface.co/spaces/Harikaranm21/TeamTracker
```

Replace `YOUR_HF_TOKEN` with your HF access token. Get it from:

- Go to https://huggingface.co/settings/tokens
- Click **New token** → Role: **Write** → Generate → Copy

**Step 4 — Verify both remotes are set up:**

```bash
git remote -v
```

You should see:

```
origin   https://github.com/harikaranm21/TeamTracker.git (fetch)
origin   https://github.com/harikaranm21/TeamTracker.git (push)
space    https://Harikaranm21:hf_...@huggingface.co/spaces/Harikaranm21/TeamTracker (fetch)
space    https://Harikaranm21:hf_...@huggingface.co/spaces/Harikaranm21/TeamTracker (push)
```

Now you can make changes and push as normal.

---

### Step-by-Step: Example — Change "Board" title text

**Step 1 — Find the file to edit**

Open `src/client/App.tsx` in any code editor. Search for the text you want to change.

**Step 2 — Build the changes**

```bash
cd TeamTracker
npm run build
```

Wait for: `Client bundle built successfully`

**Step 3 — Test locally first**

```bash
npm start
```

Open http://localhost:3333 — verify your change looks correct. Press `Ctrl+C` to stop.

**Step 4 — Commit to GitHub**

```bash
git add -A
git commit -m "describe your change"
git push origin main
```

**Step 5 — Push to Hugging Face (live site)**

```bash
git push space main
```

HF rebuilds automatically. Takes 3–5 minutes. Live at `https://harikaranm21-teamtracker.hf.space`.

---

### Step-by-Step: Example — Change "Kanban Board" to "Board"

**Step 1 — Find the file to edit**

The text "Kanban Board" lives in `src/client/App.tsx`. Open it in any code editor.

Search for: `Kanban Board`

You'll find this line:

```tsx
<Text size="5" weight="bold">
  Kanban Board
</Text>
```

Change it to:

```tsx
<Text size="5" weight="bold">
  Board
</Text>
```

**Step 2 — Build the changes**

Open your terminal, go to the project folder:

```bash
cd /Users/harikarm/TeamTracker
npm run build
```

Wait for:

```
Client bundle built successfully
```

**Step 3 — Test locally first**

```bash
npm start
```

Open http://localhost:3333 — verify your change looks correct.

Press `Ctrl+C` to stop the local server when done.

**Step 4 — Commit to GitHub**

```bash
git add -A
git commit -m "fix: rename Kanban Board to Board"
git push origin main
```

**Step 5 — Push to Hugging Face (live site)**

```bash
git push space main
```

HF will automatically rebuild and redeploy. Takes 3–5 minutes.
Your live site at `https://harikaranm21-teamtracker.hf.space` updates automatically.

---

### Where to Find What (File Map)

| What you want to change   | File to edit                                    |
| ------------------------- | ----------------------------------------------- |
| Any UI text / labels      | `src/client/App.tsx` or the relevant component  |
| Board page                | `src/client/components/KanbanBoard.tsx`         |
| Task card appearance      | `src/client/components/TaskCard.tsx`            |
| Task create/edit form     | `src/client/components/TaskDialog.tsx`          |
| Months page               | `src/client/components/SprintPanel.tsx`         |
| Team members page         | `src/client/components/MembersPanel.tsx`        |
| Dashboard charts          | `src/client/components/Dashboard.tsx`           |
| Calendar                  | `src/client/components/CalendarView.tsx`        |
| Login / Register page     | `src/client/components/LoginPage.tsx`           |
| Admin panel               | `src/client/components/AdminPanel.tsx`          |
| API calls (frontend)      | `src/client/api.ts`                             |
| Server routes (backend)   | `src/server/routes/` folder                     |
| Database schema           | `src/server/storage/db.ts`                      |
| Sidebar navigation labels | `src/client/App.tsx` — look for the `NAV` array |

---

### Common Changes and Exactly Where to Make Them

**Rename a navigation tab (e.g. "Team" → "Members")**

File: `src/client/App.tsx`
Find:

```tsx
{ id: 'members', label: 'Team', icon: <Users size={16} /> },
```

Change `'Team'` to `'Members'`.

**Change the app name "TeamTracker"**

File: `src/client/App.tsx`
Find:

```tsx
<Text size="4" weight="bold">
  TeamTracker
</Text>
```

Change to whatever you want.

**Add a new column to the Kanban board**

File: `src/client/components/KanbanBoard.tsx`
Find the `COLUMNS` array and add a new entry.
Also update `TaskStatus` type in `src/shared/types.ts`
and add the new status to the DB schema in `src/server/storage/db.ts`.

**Change priority labels (High/Medium/Low)**

File: `src/client/components/TaskCard.tsx` and `src/client/components/TaskDialog.tsx`

**Change avatar colors for members**

File: `src/server/storage/members.ts` — find the `COLORS` array.

---

### Deploying Only Frontend Changes (Faster)

If you only changed client-side files (anything in `src/client/`), you only need to rebuild the client:

```bash
npm run build:client   # faster than full build
git add -A
git commit -m "your message"
git push origin main
git push space main
```

If you changed server files (`src/server/`), always do the full build:

```bash
npm run build
```

---

### Checking if HF Deployed Successfully

After `git push space main`:

1. Go to https://huggingface.co/spaces/Harikaranm21/TeamTracker
2. Click the **"App"** tab
3. You'll see **"Building"** status while it rebuilds
4. Once it shows **"Running"** — your changes are live

If it shows **"Error"** — click **"Logs"** to see what went wrong.

---

### Quick Reference Commands

```bash
# ── First time on a new laptop ──────────────────────────────────────────────
git clone https://github.com/harikaranm21/TeamTracker.git
cd TeamTracker
npm install
git remote add space https://Harikaranm21:YOUR_HF_TOKEN@huggingface.co/spaces/Harikaranm21/TeamTracker

# ── Every time you make changes ──────────────────────────────────────────────

# Go to project folder
cd TeamTracker

# Build everything
npm run build

# Build only frontend (faster if only UI changes)
npm run build:client

# Start locally to test
npm start

# Save changes to GitHub
git add -A
git commit -m "describe your change here"
git push origin main

# Deploy to live site (Hugging Face)
git push space main

# Run tests
npm test
```

---

## 19. What's in .gitignore and Why

These files are intentionally excluded from GitHub:

| File/Folder                      | Reason                                                                |
| -------------------------------- | --------------------------------------------------------------------- |
| `node_modules/`                  | 300MB+ of packages — regenerated by `npm install`                     |
| `dist/`                          | Compiled server JS — regenerated by `npm run build`                   |
| `public/bundle.js`, `bundle.css` | Built client files — regenerated by `npm run build`                   |
| `data/`, `*.db`                  | SQLite database with real user data and passwords — must stay private |

**Do not commit these.** The `.gitignore` is correct as-is. HF Spaces builds everything fresh from source using Docker, so no built files need to be committed.

---

_Last updated: June 2026_
