/**
 * App — root component, navigation, data loading, and auth-gated UI.
 * Optimistic updates: mutations update local state immediately and
 * roll back on failure rather than waiting for a full re-fetch.
 * @module client/App
 */
import React, { useState, useEffect, useCallback } from "react";
import {
  Flex,
  Box,
  Text,
  Button,
  Separator,
  Avatar,
  DropdownMenu,
  Badge,
  Select,
} from "@radix-ui/themes";
import {
  SquaresFour,
  ChartBar,
  Users,
  Kanban,
  Lightning,
  SignOut,
  UserCircle,
  ShieldCheck,
  CalendarBlank,
  MagnifyingGlass,
  Key,
} from "@phosphor-icons/react";
import { KanbanBoard } from "./components/KanbanBoard";
import { TaskDialog } from "./components/TaskDialog";
import { SprintPanel } from "./components/SprintPanel";
import { MembersPanel } from "./components/MembersPanel";
import { Dashboard } from "./components/Dashboard";
import { AdminPanel } from "./components/AdminPanel";
import { LoginPage } from "./components/LoginPage";
import { CalendarView } from "./components/CalendarView";
import { ChangePasswordDialog } from "./components/ChangePasswordDialog";
import { ProjectAssistant } from "./components/ProjectAssistant";
import { useAuth } from "./hooks/useAuth";
import { useConfirm } from "./hooks/useConfirm";
import type {
  Task,
  Member,
  Sprint,
  TaskStatus,
  CreateTaskInput,
  UpdateTaskInput,
  Team,
} from "../shared/types";
import * as api from "./api";

type NavTab =
  | "board"
  | "dashboard"
  | "sprints"
  | "members"
  | "admin"
  | "calendar";

export default function App(): React.ReactElement {
  const { user, loading: authLoading, logout } = useAuth();
  const isEditor = user?.role === "editor" || user?.role === "admin";
  const isAdmin = user?.role === "admin";
  const isViewer = user?.role === "viewer";
  const canManageTasks = isEditor || isViewer;

  const [activeTab, setActiveTab] = useState<NavTab>("board");
  const [searchQuery, setSearchQuery] = useState("");
  const [showChangePassword, setShowChangePassword] = useState(false);

  // Core data state
  const [tasks, setTasks] = useState<Task[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [sprints, setSprints] = useState<Sprint[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);

  const [taskDialogOpen, setTaskDialogOpen] = useState(false);
  const [editingTask, setEditingTask] = useState<Task | undefined>();
  const [defaultStatus, setDefaultStatus] = useState<TaskStatus>("todo");
  const [loading, setLoading] = useState(true);

  // Board month filter — null means show all tasks
  const [boardSprintFilter, setBoardSprintFilter] = useState<number | null>(
    null,
  );
  const [boardTeamFilter, setBoardTeamFilter] = useState<number | null>(null);

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
      const active = data.find((s) => s.status === "active");
      return active ? active.id : null; // null = show all tasks (safe fallback)
    });
  }, []);

  const loadTeams = useCallback(async (): Promise<void> => {
    if (!isAdmin) return;
    const data = await api.fetchTeams().catch(() => [] as Team[]);
    setTeams(data);
  }, [isAdmin]);

  useEffect(() => {
    // 1. Trigger sprint maintenance (fix past months, create current month if missing)
    // 2. Run one-time August 2026 recovery (idempotent — safe on every load)
    // 3. Load all data so the client sees the fully recovered state
    setLoading(true);
    const maintenance = isEditor ? api.maintainSprints() : Promise.resolve();
    maintenance
      .catch(console.error)
      .then(() =>
        isAdmin ? api.recoverAugust2026().catch(console.error) : undefined,
      )
      .finally(() => {
        Promise.all([
          loadTasks(),
          loadMembers(),
          loadSprints(),
          loadTeams(),
        ]).finally(() => setLoading(false));
      });
  }, [isAdmin, isEditor, loadTasks, loadMembers, loadSprints, loadTeams]);

  // ── Task mutations (optimistic) ───────────────────────────────────────────

  const openCreateTask = (status: TaskStatus = "todo"): void => {
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
        prev.map((t) =>
          t.id === editingTask.id ? ({ ...t, ...input } as Task) : t,
        ),
      );
      try {
        const updated = await api.updateTask(
          editingTask.id,
          input as UpdateTaskInput,
        );
        setTasks((prev) =>
          prev.map((t) => (t.id === updated.id ? updated : t)),
        );
      } catch {
        await loadTasks(); // rollback
      }
    } else {
      // Optimistic add with a temp id
      const tempId = -Date.now();
      const optimistic: Task = {
        id: tempId,
        title: input.title,
        description: input.description ?? "",
        status: input.status ?? defaultStatus,
        priority: input.priority ?? "medium",
        assignee_id: input.assignee_id ?? null,
        sprint_id: input.sprint_id ?? null,
        labels: input.labels ?? "",
        due_date: input.due_date ?? null,
        position: 9999,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        assignee_name: members.find((m) => m.id === input.assignee_id)?.name,
        assignee_color: members.find((m) => m.id === input.assignee_id)
          ?.avatar_color,
        sprint_name: sprints.find((s) => s.id === input.sprint_id)?.name,
      };
      setTasks((prev) => [...prev, optimistic]);
      try {
        const created = await api.createTask(
          isAdmin && boardTeamFilter != null
            ? { ...input, team_id: boardTeamFilter }
            : input,
        );
        setTasks((prev) => prev.map((t) => (t.id === tempId ? created : t)));
      } catch {
        setTasks((prev) => prev.filter((t) => t.id !== tempId)); // rollback
      }
    }
  };

  const handleDeleteTask = async (id: number): Promise<void> => {
    const ok = await confirm({
      title: "Delete task",
      description: "This task will be permanently deleted.",
      confirmLabel: "Delete",
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

  const handleMoveTask = async (
    id: number,
    status: TaskStatus,
    position: number,
  ): Promise<void> => {
    // Optimistic status change
    setTasks((prev) =>
      prev.map((t) => (t.id === id ? { ...t, status, position } : t)),
    );
    try {
      const updated = await api.moveTask(id, status, position);
      setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
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
      <Flex align="center" justify="center" style={{ height: "100vh" }}>
        <Text color="gray">Loading…</Text>
      </Flex>
    );
  }

  // Not logged in → full-page login wall, no app content visible
  if (!user) {
    return (
      <LoginPage
        onSuccess={() => {
          window.location.reload();
        }}
      />
    );
  }

  // Pending → waiting for approval screen
  if (user.role === "pending") {
    return (
      <Flex
        align="center"
        justify="center"
        direction="column"
        gap="4"
        style={{ height: "100vh" }}
      >
        <SquaresFour
          size={40}
          weight="fill"
          style={{ color: "var(--accent-9)" }}
        />
        <Text size="5" weight="bold">
          TeamTracker
        </Text>
        <Box
          style={{
            background: "var(--orange-a3)",
            border: "1px solid var(--orange-a6)",
            borderRadius: "var(--radius-3)",
            padding: "16px 24px",
            maxWidth: 400,
            textAlign: "center",
          }}
        >
          <Text size="3" style={{ color: "var(--orange-11)" }}>
            ⏳ Your account is pending admin approval.
            <br />
            <br />
            Ask your admin to approve you from the <strong>Users</strong> tab.
            Once approved, refresh this page to get started.
          </Text>
        </Box>
        <Button variant="soft" color="gray" onClick={handleLogout}>
          Sign out
        </Button>
      </Flex>
    );
  }

  const NAV: {
    id: NavTab;
    label: string;
    icon: React.ReactNode;
    adminOnly?: boolean;
    editorOnly?: boolean;
  }[] = [
    { id: "board", label: "Task Board", icon: <Kanban size={16} /> },
    { id: "dashboard", label: "Dashboard", icon: <ChartBar size={16} /> },
    { id: "sprints", label: "Months", icon: <Lightning size={16} /> },
    { id: "members", label: "Team", icon: <Users size={16} /> },
    { id: "calendar", label: "Calendar", icon: <CalendarBlank size={16} /> },
    {
      id: "admin",
      label: "Users",
      icon: <ShieldCheck size={16} />,
      adminOnly: true,
    },
  ];

  const visibleNav = NAV.filter((item) => {
    if (item.adminOnly) return isAdmin;
    if (item.editorOnly) return isEditor;
    return true;
  });

  const boardMembers =
    isAdmin && boardTeamFilter != null
      ? members.filter((member) => member.team_id === boardTeamFilter)
      : members;

  return (
    <Flex className="tt-shell" style={{ height: "100vh", overflow: "hidden" }}>
      {/* Styled confirm dialog (portal-rendered) */}
      {ConfirmDialog}

      {/* Sidebar */}
      <Box
        style={{
          width: 220,
          flexShrink: 0,
          background:
            "linear-gradient(180deg, rgba(241,245,249,0.98), rgba(230,236,245,0.96))",
          borderRight: "1px solid rgba(148, 163, 184, 0.28)",
          display: "flex",
          flexDirection: "column",
          padding: "18px 12px 14px",
          gap: 6,
          boxShadow: "inset -1px 0 0 rgba(255,255,255,0.4)",
        }}
        className="tt-sidebar"
      >
        <Flex align="center" gap="2" px="2" mb="3">
          <Box
            style={{
              width: 32,
              height: 32,
              borderRadius: 10,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background:
                "linear-gradient(135deg, var(--blue-9), var(--violet-9))",
              boxShadow: "0 12px 26px rgba(37, 99, 235, 0.22)",
            }}
          >
            <SquaresFour size={18} weight="fill" style={{ color: "#fff" }} />
          </Box>
          <Text size="4" weight="bold">
            TeamTracker
          </Text>
        </Flex>

        <Separator size="4" mb="2" />

        {visibleNav.map((item) => (
          <Button
            key={item.id}
            className="tt-nav-button"
            data-active={activeTab === item.id}
            variant={activeTab === item.id ? "solid" : "ghost"}
            color={activeTab === item.id ? "accent" : "gray"}
            size="2"
            title={item.label}
            onClick={() => setActiveTab(item.id)}
            style={{ justifyContent: "flex-start", width: "100%" }}
          >
            {item.icon}
            {item.label}
          </Button>
        ))}

        <Box style={{ flex: 1 }} />

        <Separator size="4" my="2" />

        {/* User area — always shown since unauthenticated users never reach here */}
        <DropdownMenu.Root>
          <DropdownMenu.Trigger>
            <Flex
              align="center"
              gap="2"
              px="2"
              py="1"
              style={{ borderRadius: "var(--radius-2)", cursor: "pointer" }}
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
                <Text
                  size="2"
                  weight="medium"
                  style={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    display: "block",
                  }}
                >
                  {user.username}
                </Text>
                <Badge
                  size="1"
                  color={isAdmin ? "purple" : isViewer ? "gray" : "blue"}
                  variant="soft"
                >
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
      </Box>

      {/* Main content */}
      <Box
        className="tt-main"
        style={{
          flex: 1,
          overflow: "auto",
          padding: "20px 24px 28px",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <Box
          className="tt-main-inner"
          style={{
            width: "100%",
            maxWidth: 1560,
            margin: "0 auto",
            display: "flex",
            flexDirection: "column",
            flex: 1,
          }}
        >
          {loading ? (
            <Flex align="center" justify="center" style={{ flex: 1 }}>
              <Text color="gray">Loading…</Text>
            </Flex>
          ) : (
            <>
              {activeTab === "board" && (
                <Box
                  className="tt-board"
                  style={{
                    flex: 1,
                    display: "flex",
                    flexDirection: "column",
                    overflow: "hidden",
                  }}
                >
                  <Flex
                    className="tt-board-toolbar"
                    justify="between"
                    align="center"
                    mb="3"
                    gap="3"
                    wrap="nowrap"
                    style={{ minWidth: 0, overflow: "hidden" }}
                  >
                    <Text size="5" weight="bold" style={{ flexShrink: 0 }}>
                      Task Board
                    </Text>

                    <Flex
                      align="center"
                      gap="2"
                      wrap="nowrap"
                      style={{
                        flex: 1,
                        minWidth: 0,
                        overflow: "hidden",
                        flexShrink: 1,
                      }}
                    >
                      <Flex
                        align="center"
                        gap="2"
                        className="tt-toolbar-filter"
                      >
                        <Text size="2" color="gray" style={{ flexShrink: 0 }}>
                          Month:
                        </Text>
                        <Select.Root
                          value={
                            boardSprintFilter == null
                              ? "all"
                              : String(boardSprintFilter)
                          }
                          onValueChange={(val) =>
                            setBoardSprintFilter(
                              val === "all" ? null : Number(val),
                            )
                          }
                        >
                          <Select.Trigger
                            placeholder="All months"
                            style={{ minWidth: 150 }}
                          />
                          <Select.Content>
                            <Select.Item value="all">All months</Select.Item>
                            {[...sprints]
                              .sort((a, b) =>
                                b.start_date.localeCompare(a.start_date),
                              )
                              .map((s) => (
                                <Select.Item key={s.id} value={String(s.id)}>
                                  {s.name}
                                </Select.Item>
                              ))}
                          </Select.Content>
                        </Select.Root>
                      </Flex>

                      {isAdmin && (
                        <Flex
                          align="center"
                          gap="2"
                          className="tt-toolbar-filter"
                        >
                          <Text size="2" color="gray" style={{ flexShrink: 0 }}>
                            Team:
                          </Text>
                          <Select.Root
                            value={
                              boardTeamFilter == null
                                ? "all"
                                : String(boardTeamFilter)
                            }
                            onValueChange={(val) =>
                              setBoardTeamFilter(
                                val === "all" ? null : Number(val),
                              )
                            }
                          >
                            <Select.Trigger
                              placeholder="All teams"
                              style={{ minWidth: 150 }}
                            />
                            <Select.Content>
                              <Select.Item value="all">All teams</Select.Item>
                              {[...teams]
                                .sort((a, b) => a.name.localeCompare(b.name))
                                .map((team) => (
                                  <Select.Item
                                    key={team.id}
                                    value={String(team.id)}
                                  >
                                    {team.name}
                                  </Select.Item>
                                ))}
                            </Select.Content>
                          </Select.Root>
                        </Flex>
                      )}
                    </Flex>

                    <Flex
                      align="center"
                      gap="2"
                      className="tt-search-wrap"
                      style={{
                        flexShrink: 1,
                        minWidth: 0,
                        width: "min(360px, 100%)",
                      }}
                    >
                      <MagnifyingGlass
                        size={15}
                        style={{ color: "var(--gray-9)", flexShrink: 0 }}
                      />
                      <input
                        type="text"
                        className="tt-search-field"
                        placeholder="Search tasks…"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                      />
                      {searchQuery && (
                        <Button
                          size="1"
                          variant="ghost"
                          color="gray"
                          onClick={() => setSearchQuery("")}
                        >
                          ✕
                        </Button>
                      )}
                    </Flex>

                    {canManageTasks && (
                      <Button
                        className="tt-primary-button"
                        size="2"
                        title="Create new task"
                        onClick={() => openCreateTask("todo")}
                        style={{ flexShrink: 0 }}
                      >
                        + New Task
                      </Button>
                    )}
                  </Flex>

                  <Flex
                    gap="3"
                    align="stretch"
                    style={{
                      flex: 1,
                      minHeight: 0,
                      minWidth: 0,
                      overflow: "hidden",
                    }}
                  >
                    <Box style={{ flex: 1, minWidth: 0, overflow: "hidden" }}>
                      <KanbanBoard
                        tasks={(() => {
                          // Apply month filter first, then search filter
                          let filtered =
                            boardSprintFilter != null
                              ? tasks.filter(
                                  (t) => t.sprint_id === boardSprintFilter,
                                )
                              : tasks;
                          if (isAdmin && boardTeamFilter != null) {
                            const teamMemberIds = new Set(
                              members
                                .filter(
                                  (member) =>
                                    member.team_id === boardTeamFilter,
                                )
                                .map((member) => member.id),
                            );
                            filtered = filtered.filter(
                              (task) =>
                                task.team_id === boardTeamFilter ||
                                (task.team_id == null &&
                                  task.assignee_id != null &&
                                  teamMemberIds.has(task.assignee_id)),
                            );
                          }
                          if (searchQuery) {
                            const q = searchQuery.toLowerCase();
                            filtered = filtered.filter(
                              (t) =>
                                t.title.toLowerCase().includes(q) ||
                                t.description?.toLowerCase().includes(q) ||
                                t.labels?.toLowerCase().includes(q) ||
                                t.assignee_name?.toLowerCase().includes(q),
                            );
                          }
                          return filtered;
                        })()}
                        members={boardMembers}
                        isEditor={canManageTasks}
                        canDelete={isEditor}
                        onEditTask={openEditTask}
                        onDeleteTask={handleDeleteTask}
                        onMoveTask={handleMoveTask}
                        onCreateTask={openCreateTask}
                      />
                    </Box>

                    <ProjectAssistant
                      tasks={tasks}
                      members={members}
                      sprints={sprints}
                      teams={teams}
                      currentUser={user}
                      accessLevel={user.role}
                      onRefresh={() => {
                        void loadTasks();
                        void loadMembers();
                        void loadSprints();
                        void loadTeams();
                      }}
                      activeSprintId={boardSprintFilter}
                      activeTeamId={boardTeamFilter}
                    />
                  </Flex>
                </Box>
              )}

              {activeTab === "dashboard" && <Dashboard />}

              {activeTab === "sprints" && (
                <SprintPanel
                  sprints={sprints}
                  isEditor={isEditor}
                  onSprintsChange={loadSprints}
                />
              )}

              {activeTab === "members" && (
                <MembersPanel
                  members={members}
                  isEditor={isEditor}
                  onMembersChange={loadMembers}
                />
              )}

              {activeTab === "admin" && isAdmin && <AdminPanel />}

              {activeTab === "calendar" && user && <CalendarView />}
            </>
          )}
        </Box>
      </Box>

      {canManageTasks && (
        <TaskDialog
          open={taskDialogOpen}
          task={editingTask}
          defaultStatus={defaultStatus}
          members={boardMembers}
          sprints={sprints}
          currentUser={user}
          viewerMode={isViewer}
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
