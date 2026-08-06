/**
 * JWT authentication middleware for TeamTracker.
 * @module server/middleware/auth
 */
import { Request, Response, NextFunction } from 'express';
import jwt from 'jsonwebtoken';
import type { JwtPayload } from '../../shared/types';

const JWT_SECRET = process.env.JWT_SECRET ?? 'teamtracker-dev-secret-change-in-production';

export function signToken(payload: JwtPayload): string {
  return jwt.sign(payload, JWT_SECRET, { expiresIn: '7d' });
}

export function verifyToken(token: string): JwtPayload | null {
  try {
    return jwt.verify(token, JWT_SECRET) as JwtPayload;
  } catch {
    return null;
  }
}

/** Extracts the authenticated user from cookie or Authorization header. Sets req.user if valid. */
export function extractUser(req: Request, _res: Response, next: NextFunction): void {
  const cookieToken = req.cookies?.tt_token as string | undefined;
  const headerToken = req.headers.authorization?.startsWith('Bearer ')
    ? req.headers.authorization.slice(7)
    : undefined;
  const token = cookieToken ?? headerToken;

  if (token) {
    const payload = verifyToken(token);
    if (payload) {
      req.user = payload;
    }
  }
  next();
}

/** Requires a valid authenticated user of any approved role (editor or admin). */
export function requireAuth(req: Request, res: Response, next: NextFunction): void {
  if (!req.user) {
    res.status(401).json({ error: 'Authentication required' });
    return;
  }
  if (req.user.role === 'pending') {
    res.status(403).json({ error: 'Your account is pending approval' });
    return;
  }
  next();
}

/** Requires admin role. */
export function requireAdmin(req: Request, res: Response, next: NextFunction): void {
  if (!req.user) {
    res.status(401).json({ error: 'Authentication required' });
    return;
  }
  if (req.user.role !== 'admin') {
    res.status(403).json({ error: 'Admin access required' });
    return;
  }
  next();
}
