/**
 * Shared types for TeamTracker — used by both server and client.
 * @module shared/types
 */

export type TaskStatus = 'todo' | 'in_progress' | 'review' | 'done';
export type TaskPriority = 'high' | 'medium' | 'low';

// ── Auth types ────────────────────────────────────────────────────────────────

/**
 * User roles:
 *  pending — registered but not yet approved; cannot log in
 *  viewer  — approved personal workspace member; manages only own tasks
 *  editor  — manages tasks for the assigned team plus months and members
 *  admin   — everything + user management
 */
export type UserRole = 'pending' | 'viewer' | 'editor' | 'admin';

export interface User {
  id: number;
  username: string;
  email: string;
  password_hash: string;
  role: UserRole;
  team_id: number | null;
  created_at: string;
}

export interface CreateUserInput {
  username: string;
  email: string;
  password: string;
}

export interface JwtPayload {
  id: number;
  username: string;
  role: UserRole;
}

export interface AuthUser {
  id: number;
  username: string;
  email: string;
  role: UserRole;
  team_id: number | null;
}

export interface Team {
  id: number;
  name: string;
  created_at: string;
}

// ── Calendar types ────────────────────────────────────────────────────────────

export type CalendarEventType = 'task' | 'meeting' | 'reminder' | 'other';

export interface CalendarEvent {
  id: number;
  user_id: number;
  title: string;
  description: string;
  event_type: CalendarEventType;
  date: string;        // YYYY-MM-DD
  start_time: string | null;  // HH:MM
  end_time: string | null;    // HH:MM
  color: string;
  created_at: string;
  updated_at: string;
}

export interface CreateCalendarEventInput {
  title: string;
  description?: string;
  event_type?: CalendarEventType;
  date: string;
  start_time?: string | null;
  end_time?: string | null;
  color?: string;
}

export interface UpdateCalendarEventInput extends Partial<CreateCalendarEventInput> {}

export interface Member {
  id: number;
  name: string;
  email: string;
  avatar_color: string;
  team_id: number | null;
  created_at: string;
}

export interface Sprint {
  id: number;
  name: string;
  start_date: string;
  end_date: string;
  status: 'planning' | 'active' | 'completed';
  created_at: string;
}

export interface Task {
  id: number;
  title: string;
  description: string;
  status: TaskStatus;
  priority: TaskPriority;
  assignee_id: number | null;
  team_id: number | null;
  sprint_id: number | null;
  labels: string;
  due_date: string | null;
  position: number;
  created_at: string;
  updated_at: string;
  // Joined fields
  assignee_name?: string;
  assignee_color?: string;
  sprint_name?: string;
}

export interface CreateTaskInput {
  title: string;
  description?: string;
  status?: TaskStatus;
  priority?: TaskPriority;
  assignee_id?: number | null;
  team_id?: number | null;
  sprint_id?: number | null;
  labels?: string;
  due_date?: string | null;
}

export interface UpdateTaskInput extends Partial<CreateTaskInput> {
  position?: number;
}

export interface CreateMemberInput {
  name: string;
  email: string;
  avatar_color?: string;
  team_id?: number | null;
}

export interface CreateTeamInput {
  name: string;
}

export interface CreateSprintInput {
  name: string;
  start_date: string;
  end_date: string;
  status?: Sprint['status'];
}

export interface UpdateSprintInput extends Partial<CreateSprintInput> {}

// Reporting types
export interface VelocityDataPoint {
  sprint_name: string;
  completed: number;
  total: number;
}

export interface AssigneeDistribution {
  name: string;
  count: number;
  color: string;
}

export interface StatusDistribution {
  status: TaskStatus;
  count: number;
}

export interface DashboardStats {
  totalTasks: number;
  openTasks: number;
  completedTasks: number;
  inProgressTasks: number;
  totalMembers: number;
  activeSprints: number;
}
