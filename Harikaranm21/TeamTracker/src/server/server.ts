/**
 * TeamTracker Express server entry point.
 * @module server/server
 */
import express from 'express';
import path from 'path';
import cookieParser from 'cookie-parser';
import { getDb } from './storage/db';
import { extractUser } from './middleware/auth';
import taskRoutes from './routes/tasks';
import memberRoutes from './routes/members';
import sprintRoutes from './routes/sprints';
import reportRoutes from './routes/reports';
import authRoutes from './routes/auth';
import calendarRoutes from './routes/calendar';
import adminRoutes from './routes/admin';
import commentRoutes from './routes/comments';
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
app.use('/api/tasks/:taskId/comments', commentRoutes);

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
