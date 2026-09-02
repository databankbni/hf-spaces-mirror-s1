/**
 * TeamTracker Express server entry point.
 * @module server/server
 */
import 'dotenv/config';
import express from 'express';
import path from 'path';
import cookieParser from 'cookie-parser';
import { getDb } from './storage/db';
import { extractUser, requireAuth } from './middleware/auth';
import taskRoutes from './routes/tasks';
import memberRoutes from './routes/members';
import sprintRoutes from './routes/sprints';
import reportRoutes from './routes/reports';
import authRoutes from './routes/auth';
import calendarRoutes from './routes/calendar';
import adminRoutes from './routes/admin';
import commentRoutes from './routes/comments';
import teamRoutes from './routes/teams';
import { autoMaintainSprints } from './storage/sprints';

const app = express();
const PORT = process.env.PORT ? Number(process.env.PORT) : 3333;

// Initialize DB on startup
getDb();

// Run sprint maintenance on startup, then once every 24 hours
autoMaintainSprints();
setInterval(autoMaintainSprints, 24 * 60 * 60 * 1000);

app.use(express.json());
app.use(cookieParser());

// Attach user to every request (non-blocking — public routes still work)
app.use(extractUser);

// API routes
app.use('/api/auth', authRoutes);
app.use('/api/tasks', taskRoutes);
app.use('/api/members', memberRoutes);
app.use('/api/sprints', sprintRoutes);
app.use('/api/reports', reportRoutes);
app.use('/api/calendar', calendarRoutes);
app.use('/api/admin', adminRoutes);
app.use('/api/teams', teamRoutes);
app.use('/api/tasks/:taskId/comments', commentRoutes);

app.post('/api/assistant/chat', requireAuth, async (req, res) => {
  const message = String(req.body?.message ?? '').trim();
  const history = String(req.body?.history ?? '').trim();
  const context = req.body?.context ?? {};

  if (!message) {
    return res.status(400).json({ error: 'Message is required' });
  }

  const apiKey = process.env.GEMINI_API_KEY;
  const modelCandidates = [
    ...(process.env.GEMINI_MODELS
      ? process.env.GEMINI_MODELS.split(',').map((m) => m.trim()).filter(Boolean)
      : []),
    ...(process.env.GEMINI_MODEL ? [process.env.GEMINI_MODEL.trim()] : []),
    'gemini-2.5-flash',
    'gemini-2.5-flash-lite',
    'gemini-2.0-flash',
  ].filter((value, index, list) => value && list.indexOf(value) === index);

  if (!apiKey) {
    return res.json({
      reply: 'Gemini is not configured in the deployed environment. I can still help from the live project data by summarizing sprint health, workload, ownership, and task status. If you have editor/admin access, I can also help prepare a task-creation request and confirm the action before it is executed.',
    });
  }

  const tasks = Array.isArray(context.tasks) ? context.tasks : [];
  const members = Array.isArray(context.members) ? context.members : [];
  const sprints = Array.isArray(context.sprints) ? context.sprints : [];
  const teams = Array.isArray(context.teams) ? context.teams : [];
  const activeSprint = context.activeSprintId != null
    ? sprints.find((s: any) => s.id === context.activeSprintId)
    : (sprints.find((s: any) => s.status === 'active') ?? sprints[0] ?? null);
  const activeTeam = context.activeTeamId != null
    ? teams.find((t: any) => t.id === context.activeTeamId)
    : teams[0] ?? null;

  const statusSummary = ['todo', 'in_progress', 'done'].map((status) => {
    const count = tasks.filter((task: any) => task.status === status).length;
    return `${status}: ${count}`;
  }).join(', ');

  const prompt = `You are TeamTracker project copilot. Answer using the user's current project data only.
Project snapshot:
- total tasks: ${tasks.length}
- statuses: ${statusSummary}
- overdue tasks: ${tasks.filter((task: any) => task.due_date && task.status !== 'done' && new Date(task.due_date) < new Date()).length}
- members: ${members.map((member: any) => member.name).join(', ') || 'none'}
- teams: ${teams.map((team: any) => team.name).join(', ') || 'none'}
- active sprint: ${activeSprint?.name ?? 'none'}
- active team: ${activeTeam?.name ?? 'none'}
- historical sprint count: ${sprints.filter((s: any) => s.status === 'completed').length}

User question: ${message}
Conversation history:
${history ? history.slice(0, 2000) : 'No prior conversation.'}

Rules:
- Keep the answer concise, practical, and grounded in the project data.
- Use the conversation history to preserve context across the current chat. If the user asks a short follow-up such as "which is better?", use the earlier completed sprint comparison in the conversation history.
- If the user asks whether the assistant can create tasks, respond based on the current access and the confirmation workflow: for read-only users, say the assistant can help prepare the task but cannot execute it; for editor/admin users, say it can help create tasks after confirmation.
- If asked for workload, use task counts and ownership.
- If asked for sprint health, mention open vs done tasks and overdue items.
- If the user asks to compare sprint performance or month-over-month trends and there are no completed historical sprints in the data, respond exactly: "I can compare sprint performance only when previous sprint data exists. Right now the project snapshot only includes the active sprint, so there is no prior sprint to compare against yet."
- Do not invent previous sprint metrics or claim historical comparisons when the dataset has only the active sprint.
- Never claim that the assistant cannot create tasks when it is allowed to help create the task request and ask for confirmation first.`;

  let lastError: string | null = null;

  for (const model of modelCandidates) {
    try {
      const response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contents: [{
            role: 'user',
            parts: [{ text: prompt }],
          }],
        }),
      });

      const result = await response.json();
      const reply = result?.candidates?.[0]?.content?.parts?.map((part: any) => part.text ?? '').join('')?.trim();

      if (response.ok && reply) {
        return res.json({ reply, model });
      }

      lastError = result?.error?.message ?? 'Gemini request failed';
    } catch (error) {
      lastError = error instanceof Error ? error.message : 'Gemini request failed';
    }
  }

  return res.json({
    reply: `I could not reach Gemini with the configured models. The app is still grounded in the live project data, so I can summarize open work, workload, teams, and sprint health without the AI layer. ${lastError ? `Last error: ${lastError}` : ''}`.trim(),
  });
});

// Serve static frontend
const PUBLIC_DIR = path.join(process.cwd(), 'public');
app.use(express.static(PUBLIC_DIR));

// SPA fallback
app.get('*', (_req, res) => {
  res.sendFile(path.join(PUBLIC_DIR, 'index.html'));
});

app.listen(PORT, () => {
  console.log(`TeamTracker running at http://localhost:${PORT}`);
});
