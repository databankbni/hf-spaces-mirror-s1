/**
 * Auth routes — register, login, logout, me, admin user management.
 * @module server/routes/auth
 */
import { Router } from 'express';
import * as UserStore from '../storage/users';
import * as MemberStore from '../storage/members';
import { signToken, requireAuth, requireAdmin } from '../middleware/auth';
import type { CreateUserInput } from '../../shared/types';

const router = Router();

const COOKIE_OPTS = {
  httpOnly: true,
  sameSite: 'lax' as const,
  secure: process.env.NODE_ENV === 'production',
  maxAge: 7 * 24 * 60 * 60 * 1000, // 7 days
};

// POST /api/auth/register
router.post('/register', (req, res) => {
  const { username, email, password } = req.body as CreateUserInput;

  if (!username?.trim() || !email?.trim() || !password) {
    return res.status(400).json({ error: 'Username, email, and password are required' });
  }
  if (password.length < 8) {
    return res.status(400).json({ error: 'Password must be at least 8 characters' });
  }

  if (UserStore.getUserByUsername(username.trim())) {
    return res.status(409).json({ error: 'Username already taken' });
  }
  if (UserStore.getUserByEmail(email.trim())) {
    return res.status(409).json({ error: 'Email already registered' });
  }

  const user = UserStore.createUser({ username: username.trim(), email: email.trim(), password });

  // Auto-add as team member regardless of role
  try { MemberStore.createMember({ name: user.username, email: user.email }); } catch { /* ignore duplicate */ }

  // If first user (auto-admin), log them in immediately
  if (user.role === 'admin') {
    const token = signToken({ id: user.id, username: user.username, role: user.role });
    res.cookie('tt_token', token, COOKIE_OPTS);
    return res.status(201).json({ user, token });
  }

  return res.status(201).json({
    user,
    message: 'Registration successful. Your account is pending admin approval.',
  });
});

// POST /api/auth/login
router.post('/login', (req, res) => {
  const { username, password } = req.body as { username: string; password: string };

  if (!username?.trim() || !password) {
    return res.status(400).json({ error: 'Username and password are required' });
  }

  const user = UserStore.getUserByUsername(username.trim());
  if (!user || !UserStore.verifyPassword(user, password)) {
    return res.status(401).json({ error: 'Invalid username or password' });
  }

  if (user.role === 'pending') {
    return res.status(403).json({ error: 'Your account is pending admin approval' });
  }

  const token = signToken({ id: user.id, username: user.username, role: user.role });
  res.cookie('tt_token', token, COOKIE_OPTS);

  // Auto-add user as a team member if not already one
  const existingMember = MemberStore.getAllMembers().find(
    m => m.email === user.email
  );
  if (!existingMember) {
    try {
      MemberStore.createMember({ name: user.username, email: user.email });
    } catch { /* ignore duplicate */ }
  }

  res.json({ user: { id: user.id, username: user.username, email: user.email, role: user.role }, token });
});

// POST /api/auth/logout
router.post('/logout', (_req, res) => {
  res.clearCookie('tt_token');
  res.json({ ok: true });
});

// GET /api/auth/me
router.get('/me', requireAuth, (req, res) => {
  const user = UserStore.getUserById(req.user!.id);
  if (!user) return res.status(404).json({ error: 'User not found' });
  res.json({ id: user.id, username: user.username, email: user.email, role: user.role });
});

// ── Admin routes ──────────────────────────────────────────────────────────────

// GET /api/auth/users  (admin only)
router.get('/users', requireAdmin, (_req, res) => {
  res.json(UserStore.getAllUsers());
});

// GET /api/auth/users/pending  (admin only)
router.get('/users/pending', requireAdmin, (_req, res) => {
  res.json(UserStore.getPendingUsers());
});

// PATCH /api/auth/users/:id/role  (admin only)
router.patch('/users/:id/role', requireAdmin, (req, res) => {
  const { role } = req.body as { role: string };
  const validRoles = ['pending', 'editor', 'admin'];
  if (!validRoles.includes(role)) {
    return res.status(400).json({ error: 'Invalid role' });
  }

  // Prevent admin from demoting themselves
  if (Number(req.params.id) === req.user!.id && role !== 'admin') {
    return res.status(400).json({ error: 'Cannot change your own admin role' });
  }

  const user = UserStore.updateUserRole(Number(req.params.id), role as 'pending' | 'editor' | 'admin');
  if (!user) return res.status(404).json({ error: 'User not found' });
  res.json(user);
});

// DELETE /api/auth/users/:id  (admin only)
router.delete('/users/:id', requireAdmin, (req, res) => {
  if (Number(req.params.id) === req.user!.id) {
    return res.status(400).json({ error: 'Cannot delete your own account' });
  }
  const deleted = UserStore.deleteUser(Number(req.params.id));
  if (!deleted) return res.status(404).json({ error: 'User not found' });
  res.status(204).send();
});

// PATCH /api/auth/users/:id/password  (admin resets any user's password)
router.patch('/users/:id/password', requireAdmin, (req, res) => {
  const { password } = req.body as { password: string };
  if (!password || password.length < 8) {
    return res.status(400).json({ error: 'Password must be at least 8 characters' });
  }
  const user = UserStore.updateUserPassword(Number(req.params.id), password);
  if (!user) return res.status(404).json({ error: 'User not found' });
  res.json({ ok: true, message: 'Password updated' });
});

// PATCH /api/auth/me/password  (logged-in user changes their own password)
router.patch('/me/password', requireAuth, (req, res) => {
  const { currentPassword, newPassword } = req.body as { currentPassword: string; newPassword: string };
  if (!currentPassword || !newPassword) {
    return res.status(400).json({ error: 'Both current and new password are required' });
  }
  if (newPassword.length < 8) {
    return res.status(400).json({ error: 'New password must be at least 8 characters' });
  }
  const user = UserStore.getUserById(req.user!.id);
  if (!user) return res.status(404).json({ error: 'User not found' });
  if (!UserStore.verifyPassword(user, currentPassword)) {
    return res.status(401).json({ error: 'Current password is incorrect' });
  }
  UserStore.updateUserPassword(user.id, newPassword);
  res.json({ ok: true, message: 'Password changed successfully' });
});

export default router;
