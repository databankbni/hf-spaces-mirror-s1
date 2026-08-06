/**
 * App — root component, navigation, data loading, and auth-gated UI.
 * Optimistic updates: mutations update local state immediately and
 * roll back on failure rather than waiting for a full re-fetch.
 * @module client/App
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Flex, Box, Text, Button, Separator, Avatar, DropdownMenu, Badge, Select } from '@radix-ui/themes';
import {
  SquaresFour, ChartBar, Users, Kanban, Lightning, SignOut, UserCircle, ShieldCheck, CalendarBlank, MagnifyingGlass, Key
} from '@phosphor-icons/react';
import { KanbanBoard } from './components/KanbanBoard';
import { TaskDialog } from './components/TaskDialog';
import { SprintPanel } from './components/SprintPanel';
import { MembersPanel } from './components/MembersPanel';
import { Dashboard } from './components/Dashboard';
import { AdminPanel } from './components/AdminPanel';
import { LoginPage } from './components/LoginPage';
import { CalendarView } from './components/CalendarView';
import { ChangePasswordDialog } from './components/ChangePasswordDialog';
import { useAuth } from './hooks/useAuth';
import { useConfirm } from './hooks/useConfirm';
import type { Task, Member, Sprint, TaskStatus, CreateTaskInput, UpdateTaskInput } from '../shared/types';
import * as api from './api';

type NavTab = 'board' | 'dashboard' | 'sprints' | 'members' | 'admin' | 'calendar';

export default function App(): React.ReactElement {
  const { user, loading: authLoading, logout } = useAuth();
  const isEditor = user?.role === 'editor' || user?.role === 'admin';
  const isAdmin = user?.role === 'admin';

  const [showLogin, setShowLogin] = useState(false);
  const [activeTab, setActiveTab] = useState<NavTab>('board');
  const [searchQuery, setSearchQuery] = useState('');
  const [showChangePassword, setShowChangePassword] = useState(false);

  // Core data state
  const [tasks, setTasks] = useState<Task[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [sprints, setSprints] = useState<Sprint[]>([]);

  const [taskDialogOpen, setTaskDialogOpen] = useState(false);
  const [editingTask, setEditingTask] = useState<Task | undefined>();
  const [defaultStatus, setDefaultStatus] = useState<TaskStatus>('todo');
  const [loading, setLoading] = useState(true);

  // Board month filter — null means show all tasks
  const [boardSprintFilter, setBoardSprintFilter] = useState<number | null>(null);

  // Styled confirm dialog (replaces window.confirm)
  const { confirm, ConfirmDialog } = useConfirm();

  // ── Data loaders ──────────────────────────────────────────────────────────
  const loadTasks = useCallback(async (): Promise<void> => {
    const data = await api.fetchTasks().catch(() => [] as Task[]);
    setTasks(data);
  }, []);

  const loadMembers = useCallback(async (): Promise<void> => {
    const data = await api.fetchMembers().catch(() => [] as Member[]);
    setMembers(data);
  }, []);

  const loadSprints = useCallback(async (): Promise<void> => {
    const data = await api.fetchSprints().catch(() => [] as Sprint[]);
    setSprints(data);
    // Default board filter to the active sprint on first load.
    // If there is no active sprint (e.g. maintenance hasn't run yet or data was lost),
    // fall back to null so ALL tasks are visible rather than showing a blank board.
    setBoardSprintFilter((prev) => {
      if (prev !== null) return prev; // user already picked something — don't override
      const active = data.find((s) => s.status === 'active');
      return active ? active.id : null; // null = show all tasks (safe fallback)
    });
  }, []);

  useEffect(() => {
    // 1. Trigger sprint maintenance (fix past months, create current month if missing)
    // 2. Run one-time August 2026 recovery (idempotent — safe on every load)
    // 3. Load all data so the client sees the fully recovered state
    setLoading(true);
    api.maintainSprints()
      .catch(console.error)
      .then(() => api.recoverAugust2026().catch(console.error))
      .finally(() => {
        Promise.all([loadTasks(), loadMembers(), loadSprints()]).finally(() => setLoading(false));
      });
  }, [loadTasks, loadMembers, loadSprints]);

  // ── Task mutations (optimistic) ───────────────────────────────────────────

  const openCreateTask = (status: TaskStatus = 'todo'): void => {
    setEditingTask(undefined);
    setDefaultStatus(status);
    setTaskDialogOpen(true);
  };

  const openEditTask = (task: Task): void => {
    setEditingTask(task);
    setTaskDialogOpen(true);
  };

  const handleSaveTask = async (input: CreateTaskInput): Promise<void> => {
    if (editingTask) {
      // Optimistic update for edits
      setTasks((prev) =>
        prev.map((t) => t.id === editingTask.id ? { ...t, ...input } as Task : t)
      );
      try {
        const updated = await api.updateTask(editingTask.id, input as UpdateTaskInput);
        setTasks((prev) => prev.map((t) => t.id === updated.id ? updated : t));
      } catch {
        await loadTasks(); // rollback
      }
    } else {
      // Optimistic add with a temp id
      const tempId = -Date.now();
      const optimistic: Task = {
        id: tempId,
        title: input.title,
        description: input.description ?? '',
        status: input.status ?? defaultStatus,
        priority: input.priority ?? 'medium',
        assignee_id: input.assignee_id ?? null,
        sprint_id: input.sprint_id ?? null,
        labels: input.labels ?? '',
        due_date: input.due_date ?? null,
        position: 9999,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        assignee_name: members.find((m) => m.id === input.assignee_id)?.name,
        assignee_color: members.find((m) => m.id === input.assignee_id)?.avatar_color,
        sprint_name: sprints.find((s) => s.id === input.sprint_id)?.name,
      };
      setTasks((prev) => [...prev, optimistic]);
      try {
        const created = await api.createTask(input);
        setTasks((prev) => prev.map((t) => t.id === tempId ? created : t));
      } catch {
        setTasks((prev) => prev.filter((t) => t.id !== tempId)); // rollback
      }
    }
  };

  const handleDeleteTask = async (id: number): Promise<void> => {
    const ok = await confirm({
      title: 'Delete task',
      description: 'This task will be permanently deleted.',
      confirmLabel: 'Delete',
    });
    if (!ok) return;
    // Optimistic remove
    setTasks((prev) => prev.filter((t) => t.id !== id));
    try {
      await api.deleteTask(id);
    } catch {
      await loadTasks(); // rollback
    }
  };

  const handleMoveTask = async (id: number, status: TaskStatus, position: number): Promise<void> => {
    // Optimistic status change
    setTasks((prev) =>
      prev.map((t) => t.id === id ? { ...t, status, position } : t)
    );
    try {
      const updated = await api.moveTask(id, status, position);
      setTasks((prev) => prev.map((t) => t.id === updated.id ? updated : t));
    } catch {
      await loadTasks(); // rollback
    }
  };

  const handleLogout = async (): Promise<void> => {
    await logout();
  };

  // Auth is still being determined
  if (authLoading) {
    return (
      <Flex align="center" justify="center" style={{ height: '100vh' }}>
        <Text color="gray">Loading…</Text>
      </Flex>
    );
  }

  if (showLogin) {
    return <LoginPage onSuccess={() => { setShowLogin(false); }} />;
  }

  const NAV: { id: NavTab; label: string; icon: React.ReactNode; adminOnly?: boolean; authOnly?: boolean }[] = [
    { id: 'board', label: 'Task Board', icon: <Kanban size={16} /> },
    { id: 'dashboard', label: 'Dashboard', icon: <ChartBar size={16} /> },
    { id: 'sprints', label: 'Months', icon: <Lightning size={16} /> },
    { id: 'members', label: 'Team', icon: <Users size={16} /> },
    { id: 'calendar', label: 'Calendar', icon: <CalendarBlank size={16} />, authOnly: true },
    { id: 'admin', label: 'Users', icon: <ShieldCheck size={16} />, adminOnly: true },
  ];

  const visibleNav = NAV.filter((item) => {
    if (item.adminOnly) return isAdmin;
    if (item.authOnly) return !!user;
    return true;
  });

  return (
    <Flex style={{ height: '100vh', overflow: 'hidden' }}>
      {/* Styled confirm dialog (portal-rendered) */}
      {ConfirmDialog}

      {/* Sidebar */}
      <Box
        style={{
          width: 200,
          flexShrink: 0,
          background: 'var(--gray-a2)',
          borderRight: '1px solid var(--gray-a4)',
          display: 'flex',
          flexDirection: 'column',
          padding: '16px 8px',
          gap: 4,
        }}
      >
        <Flex align="center" gap="2" px="2" mb="3">
          <SquaresFour size={22} weight="fill" style={{ color: 'var(--accent-9)' }} />
          <Text size="4" weight="bold">TeamTracker</Text>
        </Flex>

        <Separator size="4" mb="2" />

        {visibleNav.map((item) => (
          <Button
            key={item.id}
            variant={activeTab === item.id ? 'solid' : 'ghost'}
            color={activeTab === item.id ? 'accent' : 'gray'}
            size="2"
            title={item.label}
            onClick={() => setActiveTab(item.id)}
            style={{ justifyContent: 'flex-start', width: '100%' }}
          >
            {item.icon}
            {item.label}
          </Button>
        ))}

        <Box style={{ flex: 1 }} />

        {isEditor && activeTab === 'board' && (
          <Button
            size="2"
            title="Create new task"
            onClick={() => openCreateTask('todo')}
            style={{ width: '100%' }}
          >
            + New Task
          </Button>
        )}

        <Separator size="4" my="2" />

        {/* User area */}
        {user ? (
          <DropdownMenu.Root>
            <DropdownMenu.Trigger>
              <Flex
                align="center"
                gap="2"
                px="2"
                py="1"
                style={{ borderRadius: 'var(--radius-2)', cursor: 'pointer' }}
                role="button"
                aria-label="User menu"
              >
                <Avatar
                  size="1"
                  fallback={user.username[0].toUpperCase()}
                  color="accent"
                  radius="full"
                />
                <Box style={{ flex: 1, minWidth: 0 }}>
                  <Text size="2" weight="medium" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }}>
                    {user.username}
                  </Text>
                  <Badge size="1" color={isAdmin ? 'purple' : 'blue'} variant="soft">
                    {user.role}
                  </Badge>
                </Box>
              </Flex>
            </DropdownMenu.Trigger>
            <DropdownMenu.Content>
              <DropdownMenu.Item disabled>
                <UserCircle size={14} />
                {user.email}
              </DropdownMenu.Item>
              <DropdownMenu.Separator />
              <DropdownMenu.Item onClick={() => setShowChangePassword(true)}>
                <Key size={14} />
                Change Password
              </DropdownMenu.Item>
              <DropdownMenu.Separator />
              <DropdownMenu.Item color="red" onClick={handleLogout}>
                <SignOut size={14} />
                Sign out
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Root>
        ) : (
          <Button
            size="2"
            variant="soft"
            title="Sign in to edit"
            onClick={() => setShowLogin(true)}
            style={{ width: '100%' }}
          >
            Sign in
          </Button>
        )}
      </Box>

      {/* Pending user banner */}
      {user?.role === 'pending' && (
        <Box style={{
          background: 'var(--orange-a3)', borderBottom: '1px solid var(--orange-a6)',
          padding: '8px 16px', flexShrink: 0,
        }}>
          <Text size="2" style={{ color: 'var(--orange-11)' }}>
            ⏳ Your account is pending admin approval. You can view everything but cannot edit until approved.
            Ask your admin to approve you from the <strong>Users</strong> tab.
          </Text>
        </Box>
      )}

      {/* Main content */}
      <Box
        style={{
          flex: 1,
          overflow: 'auto',
          padding: '20px 24px',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {loading ? (
          <Flex align="center" justify="center" style={{ flex: 1 }}>
            <Text color="gray">Loading…</Text>
          </Flex>
        ) : (
          <>
            {activeTab === 'board' && (
              <Box style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                <Flex justify="between" align="center" mb="3" gap="3" wrap="wrap">
                  <Text size="5" weight="bold" style={{ flexShrink: 0 }}>Task Board</Text>

                  {/* Month filter */}
                  <Flex align="center" gap="2" style={{ flexShrink: 0 }}>
                    <Text size="2" color="gray" style={{ flexShrink: 0 }}>Month:</Text>
                    <Select.Root
                      value={boardSprintFilter == null ? 'all' : String(boardSprintFilter)}
                      onValueChange={(val) => setBoardSprintFilter(val === 'all' ? null : Number(val))}
                    >
                      <Select.Trigger placeholder="All months" style={{ minWidth: 150 }} />
                      <Select.Content>
                        <Select.Item value="all">All months</Select.Item>
                        {[...sprints]
                          .sort((a, b) => b.start_date.localeCompare(a.start_date))
                          .map((s) => (
                            <Select.Item key={s.id} value={String(s.id)}>{s.name}</Select.Item>
                          ))}
                      </Select.Content>
                    </Select.Root>
                  </Flex>

                  {/* Search bar */}
                  <Flex align="center" gap="2" style={{ flex: 1, maxWidth: 320 }}>
                    <MagnifyingGlass size={15} style={{ color: 'var(--gray-9)', flexShrink: 0 }} />
                    <input
                      type="text"
                      placeholder="Search tasks…"
                      value={searchQuery}
                      onChange={e => setSearchQuery(e.target.value)}
                      style={{
                        flex: 1, border: '1px solid var(--gray-a6)',
                        borderRadius: 'var(--radius-2)', padding: '5px 10px',
                        fontSize: 13, background: 'var(--color-panel-solid)',
                        color: 'inherit', outline: 'none',
                      }}
                    />
                    {searchQuery && (
                      <Button size="1" variant="ghost" color="gray" onClick={() => setSearchQuery('')}>✕</Button>
                    )}
                  </Flex>

                  {isEditor && (
                    <Button size="2" title="Create new task" onClick={() => openCreateTask('todo')}>
                      + New Task
                    </Button>
                  )}
                </Flex>
                <Box style={{ flex: 1, overflow: 'hidden' }}>
                  <KanbanBoard
                    tasks={(() => {
                      // Apply month filter first, then search filter
                      let filtered = boardSprintFilter != null
                        ? tasks.filter(t => t.sprint_id === boardSprintFilter)
                        : tasks;
                      if (searchQuery) {
                        const q = searchQuery.toLowerCase();
                        filtered = filtered.filter(t =>
                          t.title.toLowerCase().includes(q) ||
                          t.description?.toLowerCase().includes(q) ||
                          t.labels?.toLowerCase().includes(q) ||
                          t.assignee_name?.toLowerCase().includes(q)
                        );
                      }
                      return filtered;
                    })()}
                    members={members}
                    isEditor={isEditor}
                    onEditTask={openEditTask}
                    onDeleteTask={handleDeleteTask}
                    onMoveTask={handleMoveTask}
                    onCreateTask={openCreateTask}
                  />
                </Box>
              </Box>
            )}

            {activeTab === 'dashboard' && <Dashboard />}

            {activeTab === 'sprints' && (
              <SprintPanel
                sprints={sprints}
                isEditor={isEditor}
                onSprintsChange={loadSprints}
              />
            )}

            {activeTab === 'members' && (
              <MembersPanel
                members={members}
                isEditor={isEditor}
                onMembersChange={loadMembers}
              />
            )}

            {activeTab === 'admin' && isAdmin && <AdminPanel />}

            {activeTab === 'calendar' && user && <CalendarView />}
          </>
        )}
      </Box>

      {isEditor && (
        <TaskDialog
          open={taskDialogOpen}
          task={editingTask}
          defaultStatus={defaultStatus}
          members={members}
          sprints={sprints}
          onSave={handleSaveTask}
          onClose={() => setTaskDialogOpen(false)}
        />
      )}

      <ChangePasswordDialog
        open={showChangePassword}
        onClose={() => setShowChangePassword(false)}
      />
    </Flex>
  );
}
