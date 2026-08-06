# TeamTracker — Complete User Guide

**Version:** 1.0  
**Public URL:** https://harikaranm21-teamtracker.hf.space  
**GitHub:** https://github.com/harikaranm21/TeamTracker

---

## 1. What is TeamTracker?

TeamTracker is a web-based team work management app built for monthly planning and task tracking. It allows your entire team to collaborate on tasks, plan work by month, track progress visually on a Kanban board, and maintain personal daily calendars — all in one place accessible from any browser.

Anyone can view the dashboard and board without logging in. Only approved team members can create, edit, or delete content.

---

## 2. Capabilities at a Glance

| Feature | Description |
|---------|-------------|
| **Kanban Board** | Visual task board with To Do, In Progress, Review, Done columns |
| **Task Search** | Real-time search by title, description, labels, or assignee |
| **Task Comments** | Threaded comments on each task |
| **Member Filter** | Filter board to see one person's tasks (like Jira) |
| **Task Management** | Create tasks with title, description, priority, assignee, month, labels, due date |
| **Month Planning** | Create monthly work periods, track active vs completed months |
| **Team Members** | Add, edit, remove team members with avatar colors |
| **Dashboard** | Charts for monthly velocity, task status distribution, work per person |
| **Personal Calendar** | Private 24-hour daily schedule per user (spreadsheet style) |
| **User Authentication** | Secure login with username and password |
| **Password Management** | Users change own password; admins reset any user's password |
| **Role-based Access** | Guests view only; editors and admins can edit; admins manage users |
| **Admin Panel** | Approve registrations, change roles, reset passwords, remove users |
| **Data Cleanup** | Bulk delete old completed tasks, months, calendar events |

---

## 3. User Roles Explained

| Role | Who they are | What they can do |
|------|-------------|-----------------|
| **Guest** | Not logged in | View board, dashboard, months, team — read only |
| **Pending** | Registered but not approved | Same as guest — cannot edit anything |
| **Editor** | Approved team member | Full create/edit/delete on tasks, months, members + personal calendar |
| **Admin** | Team lead / manager | Everything editors can + manage user accounts |

---

## 4. How to Register & Become Admin

### First User = Automatic Admin

The **very first person to register** on the app is automatically made Admin. No setup required.

**Steps:**
1. Go to https://harikaranm21-teamtracker.hf.space
2. Click **"Sign in"** in the sidebar
3. Click **"Register"** below the sign-in form
4. Enter a username, email, and password (min 8 characters)
5. Click **"Register"**
6. Since you are the first user, you are instantly logged in as **Admin**

### Subsequent Users (Pending → Editor)

All users who register after the first one start as **Pending** and cannot edit anything until approved.

**How to approve:**
1. Admin logs in
2. Click **"Users"** tab in the sidebar (only visible to admins)
3. Find the pending user — click the green **"Approve"** button
4. They become an **Editor** and can now edit tasks, months, members

### How to Make Someone an Admin

1. Go to **Users** tab
2. Find the user
3. Use the role dropdown → select **"Admin"**
4. They now have full admin access

---

## 5. How to Use the Kanban Board

The board is the main workspace. Tasks are organized in 4 columns:

```
To Do → In Progress → Review → Done
```

### Viewing the Board
- Anyone (even without login) can see the board
- Tasks show title, priority badge, labels, assignee avatar, and due date

### Searching Tasks
- A **search bar** is at the top of the board (next to the Board title)
- Type any keyword to filter tasks by title, description, labels, or assignee name
- Click ✕ to clear the search
- Works together with the member filter

### Creating a Task (Editor/Admin only)
1. Click **"+ New Task"** (top right) or **"Add task"** at the bottom of any column
2. Fill in:
   - **Title** — required
   - **Description** — optional notes
   - **Status** — which column it starts in
   - **Priority** — High (red), Medium (orange), Low (blue)
   - **Assignee** — which team member owns this
   - **Month** — which monthly period this belongs to
   - **Labels** — comma-separated tags (e.g. frontend, bug, feature)
   - **Due Date** — optional deadline
3. Click **"Create Task"**

### Moving Tasks
- **Drag and drop** a task card to another column
- Or edit the task and change the Status dropdown

### Due Date Color Coding on Task Cards
- 🔴 **Red** = Overdue (past the due date)
- 🟠 **Orange** = Due today or tomorrow
- ⚫ **Gray** = Future date

### Filtering by Person (Member Filter)
Above the board columns you'll see filter chips for each team member:
- Click a **person's name** → see only their tasks
- Click **"All"** → back to full view

### Editing a Task
- Click the **pencil icon** on any task card
- Make changes → click **"Save Changes"**
- Scroll down in the edit dialog to see **Comments** on that task

### Task Comments
- Open any existing task to edit it → scroll to the bottom
- You'll see all existing comments with the username and time
- **Post a comment:** type in the text box → click **"Post"** (or Cmd+Enter)
- **Delete a comment:** click the red trash icon (only the comment author or admin can delete)
- Comments are visible to everyone but only editors/admins can post

### Deleting a Task
- Click the **trash icon** on any task card
- Confirm in the dialog

---

## 6. How to Use Months (Sprint Planning)

Months represent work periods — typically one calendar month.

### Creating a Month
1. Click **"Months"** tab in sidebar
2. Click **"+ New Month"**
3. Enter:
   - **Name** — e.g. "July 2026"
   - **Start Date** — first day of the month
   - **End Date** — last day of the month
   - **Status** — Active or Completed
4. Click **"Create Month"**

### Month Status
- **Active** — month is currently in progress
- **Completed** — month is finished
- Status is set manually — change it via the edit (pencil) button

### Assigning Tasks to a Month
When creating or editing a task, select the month from the **"Month"** dropdown.

### Viewing Monthly Velocity
Go to the **Dashboard** tab → the "Monthly Velocity" bar chart shows how many tasks were completed vs total per month.

---

## 7. How to Manage Team Members

### Adding a Member
1. Click **"Team"** tab in sidebar
2. Click **"Add Member"**
3. Enter name and email → click **"Add Member"**

Note: When any user registers and logs in, they are automatically added as a team member.

### Editing a Member
1. Click the **pencil icon** next to their name
2. Change name or email → click **"Save Changes"**

### Removing a Member
1. Click the **trash icon** next to their name
2. Confirm → their tasks become unassigned

---

## 8. How to Use the Personal Calendar

Each logged-in user has a **private calendar** — only you can see your own events.

### Layout
- **Rows** = dates (split into two groups per month: days 1–15 and 16–end)
- **Columns** = hours (12am to 11pm, full 24 hours)
- Scroll horizontally to see all hours

### Adding an Event
**Method 1 — Click a cell:**
- Click any empty hour cell → dialog opens pre-filled with that time
- Fill in title, type, start/end time → click "Add Event"

**Method 2 — Drag across cells:**
- Hold mouse down on a cell and drag right across multiple hours
- Blue highlight shows selection
- Release → dialog opens with the full span pre-filled (e.g. 2pm–6pm)

**Method 3 — Add Event button:**
- Click "+ Add Event" (top right) for manual entry

### Event Types and Colors
| Type | Color | Use for |
|------|-------|---------|
| Task | Purple | Work items |
| Meeting | Red | Calls, standups, meetings |
| Reminder | Orange | Reminders, deadlines |
| Other | Green | Personal events |

### Spanning Multiple Hours
A 4-hour task (e.g. 2pm–6pm) renders as one wide colored block spanning 4 cells. Edit it by clicking the block.

### Sleep Schedule
Instead of manually adding sleep to every day:
1. Click **"Set Sleep"** button (blue, top right)
2. Choose sleep time (e.g. 10pm) and wake time (e.g. 8am)
3. Click **"Apply to all [Month] days"**
4. Blue sleep blocks appear on every day of the month — 10pm–midnight (night) and 12am–8am (morning)

### Editing/Deleting Events
- **Edit** — click on any event block → dialog opens pre-filled
- **Delete** — click the red trash icon on the event block

---

## 9. Dashboard

The dashboard is visible to everyone (no login needed).

| Chart | What it shows |
|-------|--------------|
| **Total Tasks** | Count of all tasks |
| **Open Tasks** | Tasks not yet done |
| **In Progress** | Tasks currently in progress |
| **Completed** | Tasks marked Done |
| **Team Members** | Total member count |
| **Active Months** | Currently active monthly periods |
| **Monthly Velocity** | Bar chart: total vs completed tasks per month |
| **Tasks by Status** | Pie chart of task distribution across statuses |
| **Work by Assignee** | Horizontal bar chart showing tasks per person |

---

## 10. Admin: Managing Users

Only admins see the **"Users"** tab in the sidebar.

### Approving Pending Users
1. Go to **Users** tab → **Users** sub-tab
2. Pending users show an orange "pending" badge
3. Click **"Approve"** → they become Editor
4. Or use the role dropdown to assign any role

### Changing User Roles
Use the dropdown next to any user:
- **Pending** → cannot edit anything
- **Editor** → full edit access
- **Admin** → full access + user management

### Resetting a User's Password
If someone forgets their password:
1. Go to **Users** tab → find the user
2. Click the **key icon** 🔑 next to their name
3. Enter a new password (min 8 characters) → click **"Reset Password"**
4. Share the new password with them securely (message, call, etc.)
5. They can then log in and change it themselves from their profile

### Removing a User
Click the red trash icon → confirm.
Their tasks remain but become unassigned.

### Data Cleanup Tab
Go to **Users** tab → click **"Data Cleanup"** sub-tab to bulk delete old data.

---

## 11. How Data is Stored (Persistence)

Your data is stored in a **SQLite database** file at `/data/teamtracker.db` inside the hosting environment.

The `/data` path is connected to a **Hugging Face Storage Bucket** (TeamTracker-storage) which persists across restarts. This means:

- ✅ Users, tasks, months, members, calendar events all survive app restarts
- ✅ Data is permanently stored in the HF bucket
- ✅ No data loss when the Space sleeps and wakes up

---

## 12. What Happens When Storage is Full

The HF Storage Bucket starts at a free tier limit. If storage runs low:

### How to check current usage
Go to your HF Space → **Settings** → **Git Storage Usage** — this shows how much is used.

### What to do when storage is full

**Option 1 — Clean old data**
- Delete completed tasks that are no longer needed
- Remove old months that are done
- Clear calendar events from past months

**Option 2 — Export and reset**
1. Download the database (see Section 13)
2. Delete old records manually
3. Re-upload the cleaned database

**Option 3 — Upgrade HF bucket**
HF buckets can be expanded. Go to your HF account → Buckets → expand storage (may require payment).

---

## 13. Backing Up and Transferring Data

Your database is a single file: `teamtracker.db`

### Downloading the database from HF
Since the app runs on HF, you can't directly download the DB from the browser. Options:

**Option A — Use HF Datasets**
Push the database to a private HF dataset as a backup.

**Option B — Run locally**
If you need the data locally:
1. Clone the repo: `git clone https://github.com/harikaranm21/TeamTracker.git`
2. Copy the data you need by manually re-entering it (for small datasets)

**Option C — Export as JSON (future feature)**
Currently the app doesn't have an export button — this can be added if needed.

### Moving to another hosting service
If you ever move away from HF:
1. Get the database file from the bucket
2. Set it up on the new server with `DB_PATH` pointing to it

---

## 14. Running Locally (on your laptop)

```bash
# Clone
git clone https://github.com/harikaranm21/TeamTracker.git
cd TeamTracker

# Install
npm install

# Build
npm run build

# Start
npm start
```

App runs at: **http://localhost:3333**

### Sharing on same WiFi network
```bash
# Find your IP
ipconfig getifaddr en0
```
Share: `http://YOUR_IP:3333` — anyone on same WiFi can access it.

---

## 15. Environment Variables

| Variable | Purpose | Value |
|----------|---------|-------|
| `NODE_ENV` | Environment mode | `production` |
| `PORT` | Port number | `7860` (HF) or `3333` (local) |
| `JWT_SECRET` | Login token secret | Long random string |
| `DB_PATH` | Database file path | `/data/teamtracker.db` |

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

| Layer | Technology |
|-------|-----------|
| Backend | Node.js 18 + Express + TypeScript |
| Frontend | React 18 + Radix UI + Recharts |
| Database | SQLite via better-sqlite3 |
| Auth | JWT tokens (httpOnly cookies) + bcrypt |
| Hosting | Hugging Face Spaces (Docker) |
| Storage | HF Storage Bucket mounted at /data |
| Source | GitHub: harikaranm21/TeamTracker |

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
<Text size="5" weight="bold">Kanban Board</Text>
```

Change it to:
```tsx
<Text size="5" weight="bold">Board</Text>
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

| What you want to change | File to edit |
|------------------------|-------------|
| Any UI text / labels | `src/client/App.tsx` or the relevant component |
| Board page | `src/client/components/KanbanBoard.tsx` |
| Task card appearance | `src/client/components/TaskCard.tsx` |
| Task create/edit form | `src/client/components/TaskDialog.tsx` |
| Months page | `src/client/components/SprintPanel.tsx` |
| Team members page | `src/client/components/MembersPanel.tsx` |
| Dashboard charts | `src/client/components/Dashboard.tsx` |
| Calendar | `src/client/components/CalendarView.tsx` |
| Login / Register page | `src/client/components/LoginPage.tsx` |
| Admin panel | `src/client/components/AdminPanel.tsx` |
| API calls (frontend) | `src/client/api.ts` |
| Server routes (backend) | `src/server/routes/` folder |
| Database schema | `src/server/storage/db.ts` |
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
<Text size="4" weight="bold">TeamTracker</Text>
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

| File/Folder | Reason |
|-------------|--------|
| `node_modules/` | 300MB+ of packages — regenerated by `npm install` |
| `dist/` | Compiled server JS — regenerated by `npm run build` |
| `public/bundle.js`, `bundle.css` | Built client files — regenerated by `npm run build` |
| `data/`, `*.db` | SQLite database with real user data and passwords — must stay private |

**Do not commit these.** The `.gitignore` is correct as-is. HF Spaces builds everything fresh from source using Docker, so no built files need to be committed.

---

*Last updated: June 2026*
