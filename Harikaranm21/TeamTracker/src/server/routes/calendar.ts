/**
 * Calendar event API routes — all routes require authentication.
 * Users can only access their own events.
 * @module server/routes/calendar
 */
import { Router } from 'express';
import * as CalendarStore from '../storage/calendar';
import { requireAuth } from '../middleware/auth';
import type { CreateCalendarEventInput, UpdateCalendarEventInput } from '../../shared/types';

const router = Router();

// All calendar routes require auth
router.use(requireAuth);

// GET /api/calendar?year=2026&month=6
router.get('/', (req, res) => {
  const year = Number(req.query.year) || new Date().getFullYear();
  const month = Number(req.query.month) || new Date().getMonth() + 1;
  const events = CalendarStore.getEventsByMonth(req.user!.id, year, month);
  res.json(events);
});

// GET /api/calendar/day?date=2026-06-25
router.get('/day', (req, res) => {
  const date = req.query.date as string;
  if (!date) return res.status(400).json({ error: 'date query param required (YYYY-MM-DD)' });
  const events = CalendarStore.getEventsByDate(req.user!.id, date);
  res.json(events);
});

// POST /api/calendar
router.post('/', (req, res) => {
  const input = req.body as CreateCalendarEventInput;
  if (!input.title?.trim() || !input.date) {
    return res.status(400).json({ error: 'title and date are required' });
  }
  const event = CalendarStore.createEvent(req.user!.id, input);
  res.status(201).json(event);
});

// PATCH /api/calendar/:id
router.patch('/:id', (req, res) => {
  const input = req.body as UpdateCalendarEventInput;
  const event = CalendarStore.updateEvent(Number(req.params.id), req.user!.id, input);
  if (!event) return res.status(404).json({ error: 'Event not found' });
  res.json(event);
});

// DELETE /api/calendar/:id
router.delete('/:id', (req, res) => {
  const deleted = CalendarStore.deleteEvent(Number(req.params.id), req.user!.id);
  if (!deleted) return res.status(404).json({ error: 'Event not found' });
  res.status(204).send();
});

export default router;
