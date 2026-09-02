/**
 * API client module — all HTTP calls to the TeamTracker backend.
 * @module client/api
 */
import type {
  Task, Member, Sprint,
  CreateTaskInput, UpdateTaskInput,
  CreateMemberInput, CreateSprintInput, UpdateSprintInput,
  DashboardStats, VelocityDataPoint, AssigneeDistribution, StatusDistribution,
  AuthUser, CreateUserInput,
  CalendarEvent, CreateCalendarEventInput, UpdateCalendarEventInput,
  Team, CreateTeamInput,
} from '../shared/types';

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error ?? 'Request failed');
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// Tasks
export const fetchTasks = (): Promise<Task[]> => request('/api/tasks');
export const fetchTask = (id: number): Promise<Task> => request(`/api/tasks/${id}`);
export const createTask = (input: CreateTaskInput): Promise<Task> =>
  request('/api/tasks', { method: 'POST', body: JSON.stringify(input) });
export const updateTask = (id: number, input: UpdateTaskInput): Promise<Task> =>
  request(`/api/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(input) });
export const moveTask = (id: number, status: string, position: number): Promise<Task> =>
  request(`/api/tasks/${id}/move`, { method: 'PATCH', body: JSON.stringify({ status, position }) });
export const deleteTask = (id: number): Promise<void> =>
  request(`/api/tasks/${id}`, { method: 'DELETE' });

// Members
export const fetchMembers = (): Promise<Member[]> => request('/api/members');
export const createMember = (input: CreateMemberInput): Promise<Member> =>
  request('/api/members', { method: 'POST', body: JSON.stringify(input) });
export const updateMember = (id: number, input: Partial<CreateMemberInput>): Promise<Member> =>
  request(`/api/members/${id}`, { method: 'PATCH', body: JSON.stringify(input) });
export const deleteMember = (id: number): Promise<void> =>
  request(`/api/members/${id}`, { method: 'DELETE' });

// Sprints
export const fetchSprints = (): Promise<Sprint[]> => request('/api/sprints');
export const maintainSprints = (): Promise<{ ok: boolean; completed: number; created: boolean }> =>
  request('/api/sprints/maintain', { method: 'POST' });
// One-time recovery for August 2026 data loss — safe to call repeatedly (idempotent)
export const recoverAugust2026 = (): Promise<{ ok: boolean; sprintId: number; sprintCreated: boolean; tasksRelinked: number; message: string }> =>
  request('/api/sprints/recover-august-2026', { method: 'POST' });
export const createSprint = (input: CreateSprintInput): Promise<Sprint> =>
  request('/api/sprints', { method: 'POST', body: JSON.stringify(input) });
export const updateSprint = (id: number, input: UpdateSprintInput): Promise<Sprint> =>
  request(`/api/sprints/${id}`, { method: 'PATCH', body: JSON.stringify(input) });
export const deleteSprint = (id: number): Promise<void> =>
  request(`/api/sprints/${id}`, { method: 'DELETE' });

// Reports
const reportQuery = (sprintId?: number, teamId?: number): string => {
  const params = new URLSearchParams();
  if (sprintId != null) params.set('sprintId', String(sprintId));
  if (teamId != null) params.set('teamId', String(teamId));
  const query = params.toString();
  return query ? `?${query}` : '';
};
export const fetchDashboardStats = (sprintId?: number, teamId?: number): Promise<DashboardStats> =>
  request(`/api/reports/stats${reportQuery(sprintId, teamId)}`);
export const fetchVelocity = (teamId?: number): Promise<VelocityDataPoint[]> =>
  request(`/api/reports/velocity${reportQuery(undefined, teamId)}`);
export const fetchAssigneeDistribution = (sprintId?: number, teamId?: number): Promise<AssigneeDistribution[]> =>
  request(`/api/reports/assignee-distribution${reportQuery(sprintId, teamId)}`);
export const fetchStatusDistribution = (sprintId?: number, teamId?: number): Promise<StatusDistribution[]> =>
  request(`/api/reports/status-distribution${reportQuery(sprintId, teamId)}`);

// Auth
export const authMe = (): Promise<AuthUser> => request('/api/auth/me');
export const authLogin = (username: string, password: string): Promise<{ user: AuthUser }> =>
  request('/api/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) });
export const authRegister = (input: CreateUserInput): Promise<{ user: AuthUser; message?: string }> =>
  request('/api/auth/register', { method: 'POST', body: JSON.stringify(input) });
export const authLogout = (): Promise<void> =>
  request('/api/auth/logout', { method: 'POST' });
export const fetchAllUsers = (): Promise<Omit<AuthUser, never>[]> => request('/api/auth/users');
export const fetchPendingUsers = (): Promise<AuthUser[]> => request('/api/auth/users/pending');
export const updateUserRole = (id: number, role: string): Promise<AuthUser> =>
  request(`/api/auth/users/${id}/role`, { method: 'PATCH', body: JSON.stringify({ role }) });
export const updateUserTeam = (id: number, team_id: number | null): Promise<AuthUser> =>
  request(`/api/auth/users/${id}/team`, { method: 'PATCH', body: JSON.stringify({ team_id }) });
export const deleteUser = (id: number): Promise<void> =>
  request(`/api/auth/users/${id}`, { method: 'DELETE' });

// Teams
export const fetchTeams = (): Promise<Team[]> => request('/api/teams');
export const createTeam = (input: CreateTeamInput): Promise<Team> =>
  request('/api/teams', { method: 'POST', body: JSON.stringify(input) });
export const updateTeam = (id: number, name: string): Promise<Team> =>
  request(`/api/teams/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) });
export const deleteTeam = (id: number): Promise<void> =>
  request(`/api/teams/${id}`, { method: 'DELETE' });

// Admin cleanup
export interface CleanupStats {
  tasks: number; doneTasks: number; calendarEvents: number;
  months: number; completedMonths: number; members: number; users: number;
}
export const fetchAdminStats = (): Promise<CleanupStats> => request('/api/admin/stats');
export const cleanupDoneTasks = (): Promise<{ deleted: number; message: string }> =>
  request('/api/admin/cleanup/done-tasks', { method: 'DELETE' });
export const cleanupCompletedMonths = (): Promise<{ deleted: number; message: string }> =>
  request('/api/admin/cleanup/completed-months', { method: 'DELETE' });
export const cleanupOldCalendar = (months: number): Promise<{ deleted: number; message: string }> =>
  request(`/api/admin/cleanup/old-calendar?months=${months}`, { method: 'DELETE' });
export const cleanupAll = (calendarMonths: number): Promise<{ doneTasks: number; completedMonths: number; oldCalendarEvents: number; message: string }> =>
  request(`/api/admin/cleanup/all?calendarMonths=${calendarMonths}`, { method: 'DELETE' });

// Calendar
export const fetchCalendarMonth = (year: number, month: number): Promise<CalendarEvent[]> =>
  request(`/api/calendar?year=${year}&month=${month}`);
export const fetchCalendarDay = (date: string): Promise<CalendarEvent[]> =>
  request(`/api/calendar/day?date=${date}`);
export const createCalendarEvent = (input: CreateCalendarEventInput): Promise<CalendarEvent> =>
  request('/api/calendar', { method: 'POST', body: JSON.stringify(input) });
export const updateCalendarEvent = (id: number, input: UpdateCalendarEventInput): Promise<CalendarEvent> =>
  request(`/api/calendar/${id}`, { method: 'PATCH', body: JSON.stringify(input) });
export const deleteCalendarEvent = (id: number): Promise<void> =>
  request(`/api/calendar/${id}`, { method: 'DELETE' });

// Comments
export interface Comment {
  id: number; task_id: number; user_id: number;
  username: string; body: string; created_at: string;
}
export const fetchComments = (taskId: number): Promise<Comment[]> =>
  request(`/api/tasks/${taskId}/comments`);
export const createComment = (taskId: number, body: string): Promise<Comment> =>
  request(`/api/tasks/${taskId}/comments`, { method: 'POST', body: JSON.stringify({ body }) });
export const deleteComment = (taskId: number, commentId: number): Promise<void> =>
  request(`/api/tasks/${taskId}/comments/${commentId}`, { method: 'DELETE' });

// Password management
export const changeMyPassword = (currentPassword: string, newPassword: string): Promise<{ ok: boolean }> =>
  request('/api/auth/me/password', { method: 'PATCH', body: JSON.stringify({ currentPassword, newPassword }) });
export const adminResetPassword = (userId: number, password: string): Promise<{ ok: boolean }> =>
  request(`/api/auth/users/${userId}/password`, { method: 'PATCH', body: JSON.stringify({ password }) });
