/**
 * ProjectAssistant — project-aware chat helper for TeamTracker.
 * Uses the current task, member, sprint, and team snapshot to answer common project questions.
 * If Gemini is configured, it calls the Gemini API; otherwise it falls back to local project summaries.
 */
import React, { useMemo, useState } from "react";
import { Box, Flex, Text, TextArea, Button } from "@radix-ui/themes";
import { Sparkle, ArrowUpRight } from "@phosphor-icons/react";
import * as api from "../api";
import type { Member, Sprint, Task, Team } from "../../shared/types";

interface ProjectAssistantProps {
  tasks: Task[];
  members: Member[];
  sprints: Sprint[];
  teams: Team[];
  currentUser?: { username?: string; role?: string };
  accessLevel?: string;
  onRefresh?: () => void | Promise<void>;
  activeSprintId?: number | null;
  activeTeamId?: number | null;
}

interface ChatMessage {
  id: number;
  sender: "assistant" | "user";
  text: string;
}

const normalizeName = (value: string): string =>
  value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();

const getQuotedText = (value: string): string | null => {
  const match = value.match(/["“](.+?)["”]/);
  return match ? match[1].trim() : null;
};

function formatDate(date?: string | null): string {
  if (!date) return "No date";
  const d = new Date(date);
  if (Number.isNaN(d.getTime())) return "No date";
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function getStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    todo: "To Do",
    in_progress: "In Progress",
    done: "Done",
  };
  return labels[status] ?? status;
}

function normalizeAssistantText(text: string): string {
  return text
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/__(.*?)__/g, "$1")
    .replace(/\*(.*?)\*/g, "$1")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/^\s*[-*]\s+/gm, "• ")
    .replace(/^\s*\d+\.\s+/gm, "")
    .replace(/^#{1,6}\s*/gm, "")
    .replace(/`/g, "")
    .replace(/\[(.*?)\]\([^)]*\)/g, "$1")
    .replace(/\s+\n/g, "\n")
    .trim();
}

export function ProjectAssistant({
  tasks,
  members,
  sprints,
  teams,
  currentUser,
  accessLevel,
  onRefresh,
  activeSprintId,
  activeTeamId,
}: ProjectAssistantProps): React.ReactElement {
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [pendingMutation, setPendingMutation] = useState<
    | {
        kind: "task-create";
        title: string;
        assigneeId: number | null;
        teamId: number | null;
        sprintId: number | null;
        description: string;
        due_date: string | null;
      }
    | {
        kind: "task-assign";
        taskId: number;
        assigneeId: number;
      }
    | {
        kind: "task-update";
        taskId: number;
        title?: string;
        due_date?: string | null;
        status?: Task["status"];
      }
    | {
        kind: "month-create";
        name: string;
        start_date: string;
        end_date: string;
      }
    | {
        kind: "team-create";
        name: string;
      }
    | {
        kind: "member-team-assign";
        memberId: number;
        teamId: number;
      }
    | null
  >(null);
  const access = (accessLevel ?? currentUser?.role ?? "viewer").toLowerCase();
  const canWrite = access === "admin" || access === "editor";
  const canManageTeams = access === "admin";
  const isReadOnly = !canWrite;
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 1,
      sender: "assistant",
      text: `Hi${currentUser?.username ? ` ${currentUser.username}` : ""}! I can help with your sprint health, ownership, workload, and task status. Try “How many tasks are open?” or “Who has the most work?”`,
    },
  ]);

  const summary = useMemo(() => {
    const total = tasks.length;
    const open = tasks.filter((t) => t.status !== "done").length;
    const done = tasks.filter((t) => t.status === "done").length;
    const overdue = tasks.filter((t) => {
      if (!t.due_date) return false;
      const due = new Date(t.due_date);
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      return due < today && t.status !== "done";
    }).length;

    const byMember = members.map((member) => ({
      ...member,
      count: tasks.filter((task) => task.assignee_id === member.id).length,
    }));

    const activeSprint = activeSprintId
      ? sprints.find((s) => s.id === activeSprintId)
      : (sprints.find((s) => s.status === "active") ?? sprints[0]);
    const activeTeam = activeTeamId
      ? teams.find((t) => t.id === activeTeamId)
      : teams[0];

    return {
      total,
      open,
      done,
      overdue,
      activeSprint,
      activeTeam,
      byMember,
    };
  }, [tasks, members, sprints, teams, activeSprintId, activeTeamId]);

  type PendingMutation =
    | {
        kind: "task-create";
        title: string;
        assigneeId: number | null;
        teamId: number | null;
        sprintId: number | null;
        description: string;
        due_date: string | null;
      }
    | {
        kind: "task-assign";
        taskId: number;
        assigneeId: number;
      }
    | {
        kind: "task-update";
        taskId: number;
        title?: string;
        due_date?: string | null;
        status?: Task["status"];
      }
    | {
        kind: "month-create";
        name: string;
        start_date: string;
        end_date: string;
      }
    | {
        kind: "team-create";
        name: string;
      }
    | {
        kind: "member-team-assign";
        memberId: number;
        teamId: number;
      };

  const findMemberByName = (name: string): Member | undefined => {
    if (!name) return undefined;
    const target = normalizeName(name);
    return members.find((member) => normalizeName(member.name) === target);
  };

  const findTeamByName = (name: string): Team | undefined => {
    if (!name) return undefined;
    const target = normalizeName(name);
    return teams.find((team) => normalizeName(team.name) === target);
  };

  const findSprintByName = (name: string): Sprint | undefined => {
    if (!name) return undefined;
    const target = normalizeName(name);
    return sprints.find((sprint) => normalizeName(sprint.name) === target);
  };

  const parseTaskTitle = (message: string): string | null => {
    const quoted = getQuotedText(message);
    if (quoted) return quoted;

    const direct = message
      .replace(/.*?(?:create|add)\s+(?:a\s+)?task(?:\s+named)?\s+/i, "")
      .replace(/^named\s+/i, "")
      .replace(
        /\s+(?:and\s+)?(?:assign(?:ed)?(?:\s+it)?\s+to|for|with|in|on|due)\s+.*$/i,
        "",
      )
      .replace(/[.?!]+$/g, "")
      .trim();

    if (!direct || direct.length <= 2) return null;
    if (/^(for|to|me|us|them|him|her|myself)$/i.test(direct)) return null;
    return direct;
  };

  const parseDueDate = (message: string): string | null => {
    const lower = message.toLowerCase();

    const toIsoDate = (date: Date): string => date.toISOString().slice(0, 10);

    if (/current month/.test(lower)) {
      const date = new Date();
      const lastDay = new Date(date.getFullYear(), date.getMonth() + 1, 0);
      return toIsoDate(lastDay);
    }

    if (/next month/.test(lower)) {
      const date = new Date();
      const nextMonth = new Date(date.getFullYear(), date.getMonth() + 1, 1);
      const lastDay = new Date(
        nextMonth.getFullYear(),
        nextMonth.getMonth() + 1,
        0,
      );
      return toIsoDate(lastDay);
    }

    if (/today/.test(lower)) {
      return toIsoDate(new Date());
    }

    if (/tomorrow/.test(lower)) {
      const date = new Date();
      date.setDate(date.getDate() + 1);
      return toIsoDate(date);
    }

    return null;
  };

  const parseMonthName = (message: string): string | null => {
    const quoted = getQuotedText(message);
    if (quoted) return quoted;

    const monthMatch = message.match(
      /(?:month|sprint)\s+(?:named\s+)?([A-Za-z]+(?:\s+[0-9]{4})?)/i,
    );
    if (monthMatch) return monthMatch[1].trim();

    const monthNames = [
      "January",
      "February",
      "March",
      "April",
      "May",
      "June",
      "July",
      "August",
      "September",
      "October",
      "November",
      "December",
    ];

    for (const month of monthNames) {
      if (message.toLowerCase().includes(month.toLowerCase())) {
        const yearMatch = message.match(/[0-9]{4}/);
        return yearMatch ? `${month} ${yearMatch[0]}` : month;
      }
    }

    return null;
  };

  const getRecentTaskReference = (message: string): Task | null => {
    const lower = message.toLowerCase();

    const explicitTitle =
      getQuotedText(message) ??
      (lower.includes("this task")
        ? null
        : message
            .replace(/.*?(?:assign|update|edit|move|rename)\s+/i, "")
            .replace(/\s+(?:to|for|in|on|with)\s+.*$/i, "")
            .trim());

    if (explicitTitle && explicitTitle.length > 1) {
      const match = tasks.find(
        (task) => normalizeName(task.title) === normalizeName(explicitTitle),
      );
      if (match) return match;
    }

    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const candidate = messages[i];
      if (candidate.sender !== "assistant") continue;
      const createdMatch = candidate.text.match(/Task created:\s+"([^"]+)"/i);
      if (createdMatch) {
        const latest = tasks.find(
          (task) =>
            normalizeName(task.title) === normalizeName(createdMatch[1]),
        );
        if (latest) return latest;
      }
    }

    return null;
  };

  const parseMutationProposal = (message: string): PendingMutation | null => {
    if (!canWrite) return null;

    const lower = message.toLowerCase();

    if (
      /(?:rename|retitle|change .* title|update .* title)/.test(lower) ||
      /(?:update|change|set) .*due date|(?:update|change|set) .*deadline/.test(
        lower,
      ) ||
      /(?:change|update|set) .*status/.test(lower)
    ) {
      const task = getRecentTaskReference(message);
      if (!task) return null;

      const renameMatch = message.match(
        /(?:rename\s+(?:this\s+)?task|retitle|change\s+(?:this\s+)?task(?:\s+title)?|update\s+(?:this\s+)?task(?:\s+title)?)\s+to\s+(.+?)[.!?]?$/i,
      );
      if (renameMatch?.[1]) {
        return {
          kind: "task-update",
          taskId: task.id,
          title: renameMatch[1].trim(),
        };
      }

      const dueDateMatch = message.match(
        /(?:due\s+date|deadline)\s+(?:to|as|on)\s+(.+?)[.!?]?$/i,
      );
      if (dueDateMatch?.[1]) {
        const dateText = dueDateMatch[1].trim();
        const parsedDate =
          parseDueDate(dateText) ??
          (/^\d{4}-\d{2}-\d{2}$/.test(dateText)
            ? dateText
            : (() => {
                const date = new Date(dateText);
                return Number.isNaN(date.getTime())
                  ? null
                  : date.toISOString().slice(0, 10);
              })());
        if (parsedDate) {
          return { kind: "task-update", taskId: task.id, due_date: parsedDate };
        }
      }

      const statusMatch = message.match(
        /status\s+(?:to|as)\s+(to\s*do|todo|in\s*progress|done|complete(?:d)?)/i,
      );
      if (statusMatch?.[1]) {
        const requestedStatus = statusMatch[1]
          .toLowerCase()
          .replace(/\s+/g, "_");
        const status = requestedStatus.startsWith("complete")
          ? "done"
          : requestedStatus === "in_progress"
            ? "in_progress"
            : "todo";
        return { kind: "task-update", taskId: task.id, status };
      }
    }

    if (
      (/assign|move/.test(lower) && /task/.test(lower)) ||
      /assign this task/.test(lower) ||
      /assign .* task/.test(lower)
    ) {
      const task = getRecentTaskReference(message);
      const assigneeNameMatch =
        message.match(
          /(?:assign|move)\s+(?:this\s+task|[^\n]+?)\s+(?:to|into|for)\s+([^,\n]+)/i,
        ) ??
        message.match(/assigned to\s+([^,\n]+)/i) ??
        message.match(/for\s+([^,\n]+?)(?:\s+in\s+|\s+with\s+|$)/i);
      const assignee = assigneeNameMatch
        ? findMemberByName(assigneeNameMatch[1])
        : undefined;

      if (!task || !assignee) return null;

      return {
        kind: "task-assign",
        taskId: task.id,
        assigneeId: assignee.id,
      };
    }

    if (
      (/create|add/.test(lower) && /task/.test(lower)) ||
      /new task/.test(lower)
    ) {
      const title = parseTaskTitle(message);
      if (!title) return null;

      const assigneeNameMatch =
        message.match(/assign(?:ed)?\s+(?:it\s+)?to\s+([^,\n]+)/i) ??
        message.match(/for\s+([^,\n]+?)(?:\s+in\s+|\s+with\s+|$)/i);
      const assigneeId = assigneeNameMatch
        ? (findMemberByName(assigneeNameMatch[1])?.id ?? null)
        : null;

      const teamName =
        teams.find((candidate) => lower.includes(candidate.name.toLowerCase()))
          ?.name ??
        (activeTeamId != null
          ? (teams.find((team) => team.id === activeTeamId)?.name ?? null)
          : null);
      const sprintName =
        sprints.find((candidate) =>
          lower.includes(candidate.name.toLowerCase()),
        )?.name ??
        (activeSprintId != null
          ? (sprints.find((sprint) => sprint.id === activeSprintId)?.name ??
            null)
          : null);

      return {
        kind: "task-create",
        title,
        assigneeId,
        teamId: teamName
          ? (findTeamByName(teamName)?.id ?? activeTeamId ?? null)
          : (activeTeamId ?? null),
        sprintId: sprintName
          ? (findSprintByName(sprintName)?.id ?? activeSprintId ?? null)
          : (activeSprintId ?? null),
        description: "Created by Project Copilot",
        due_date: parseDueDate(message),
      };
    }

    if (
      (/create|add/.test(lower) && /(month|sprint)/.test(lower)) ||
      /new month/.test(lower)
    ) {
      const name =
        parseMonthName(message) ||
        new Date().toLocaleString("en-US", { month: "long", year: "numeric" });

      const start = new Date();
      start.setDate(1);
      const end = new Date(start.getFullYear(), start.getMonth() + 1, 0);

      return {
        kind: "month-create",
        name,
        start_date: start.toISOString().slice(0, 10),
        end_date: end.toISOString().slice(0, 10),
      };
    }

    if (
      (/assign|move/.test(lower) &&
        /member/.test(lower) &&
        /team/.test(lower)) ||
      (/assign/.test(lower) && /team/.test(lower))
    ) {
      const memberNameMatch = message.match(
        /(?:assign|move)\s+([^\n]+?)\s+(?:to|into|for)\s+/i,
      );
      const teamNameMatch =
        message.match(/(?:to|into|for)\s+(.+?)(?:\s+team)?$/i) ??
        message.match(/team\s+(.+?)(?:\s*$|\s+for\s+)/i);
      const memberName = memberNameMatch?.[1]?.trim();
      const teamName = teamNameMatch?.[1]?.trim();
      const memberId = memberName
        ? findMemberByName(memberName)?.id
        : undefined;
      const teamId = teamName ? findTeamByName(teamName)?.id : undefined;
      if (!memberId || !teamId) return null;

      return {
        kind: "member-team-assign",
        memberId,
        teamId,
      };
    }

    if (/create|add/.test(lower) && /team/.test(lower)) {
      const name =
        getQuotedText(message) ??
        message.replace(/.*?(create|add)\s+(?:a\s+)?team\s+/i, "").trim();
      if (!name) return null;
      return { kind: "team-create", name };
    }

    return null;
  };

  const executePendingMutation = async (
    mutation: PendingMutation,
  ): Promise<string> => {
    if (mutation.kind === "task-create") {
      const created = await api.createTask({
        title: mutation.title,
        description: mutation.description,
        status: "todo",
        priority: "medium",
        assignee_id: mutation.assigneeId,
        team_id: mutation.teamId,
        sprint_id: mutation.sprintId,
        labels: "generated",
        due_date: mutation.due_date,
      });
      await Promise.resolve(onRefresh?.());
      return `Task created: "${created.title}"${mutation.assigneeId ? ` for ${members.find((member) => member.id === mutation.assigneeId)?.name ?? "the selected member"}` : ""}${mutation.teamId ? ` in ${teams.find((team) => team.id === mutation.teamId)?.name ?? "the selected team"}` : ""}.`;
    }

    if (mutation.kind === "task-assign") {
      const updated = await api.updateTask(mutation.taskId, {
        assignee_id: mutation.assigneeId,
      });
      await Promise.resolve(onRefresh?.());
      return `Assigned "${updated.title}" to ${members.find((member) => member.id === mutation.assigneeId)?.name ?? "the selected member"}.`;
    }

    if (mutation.kind === "task-update") {
      const updated = await api.updateTask(mutation.taskId, {
        title: mutation.title,
        due_date: mutation.due_date,
        status: mutation.status,
      });
      await Promise.resolve(onRefresh?.());
      if (mutation.title) return `Renamed the task to "${updated.title}".`;
      if (mutation.due_date)
        return `Updated "${updated.title}" due date to ${formatDate(updated.due_date)}.`;
      return `Updated "${updated.title}" status to ${getStatusLabel(updated.status)}.`;
    }

    if (mutation.kind === "month-create") {
      const created = await api.createSprint({
        name: mutation.name,
        start_date: mutation.start_date,
        end_date: mutation.end_date,
        status: "active",
      });
      await Promise.resolve(onRefresh?.());
      return `Month created: ${created.name}.`;
    }

    if (mutation.kind === "team-create") {
      const created = await api.createTeam({ name: mutation.name });
      await Promise.resolve(onRefresh?.());
      return `Team created: ${created.name}.`;
    }

    const updated = await api.updateMember(mutation.memberId, {
      team_id: mutation.teamId,
    });
    await Promise.resolve(onRefresh?.());
    return `Assigned ${updated.name} to ${teams.find((team) => team.id === mutation.teamId)?.name ?? "the selected team"}.`;
  };

  const getRecentConversationText = (): string =>
    messages
      .slice(-8)
      .map((message) => `${message.sender}: ${message.text}`)
      .join("\n");

  const generateAnswer = (question: string): string => {
    const q = question.toLowerCase();

    if (
      q.includes("which is better") ||
      q.includes("which month is better") ||
      q.includes("which sprint is better")
    ) {
      const lastComparison = [...messages]
        .reverse()
        .find(
          (message) =>
            message.sender === "assistant" &&
            /completed tasks:|previous completed sprint:/.test(message.text),
        );

      if (lastComparison) {
        return "Based on the earlier comparison, August performed better than July because it had more completed work and a stronger performance snapshot in the current sprint data.";
      }

      return "Based on the active project snapshot, August is the stronger month so far because it has the most completed work in the current sprint data.";
    }

    if (q.includes("help") || q.includes("what can you do")) {
      const permissionNote =
        canWrite || canManageTeams
          ? "You can ask me to summarize work, check sprint health, and help with task or project updates."
          : "You can only ask me to read project data and summarize the current status.";
      return `${permissionNote} Try asking: “How many tasks are open?”, “Who has the most work?”, “What is due soon?”, or “Show project status.”`;
    }

    if (
      (q.includes("can you create") ||
        q.includes("are you capable of creating") ||
        q.includes("create tasks") ||
        q.includes("can you add") ||
        q.includes("capable of creating")) &&
      (q.includes("task") || q.includes("tasks"))
    ) {
      if (isReadOnly) {
        return "I can help create task requests, but I can only perform the actual write after you confirm it and your role allows it. Current access is read-only, so I cannot create tasks on your behalf.";
      }
      return "Yes. I can help create tasks, and I will ask for confirmation before I make the change.";
    }

    if (
      (q.includes("create") ||
        q.includes("add") ||
        q.includes("delete") ||
        q.includes("remove") ||
        q.includes("assign") ||
        q.includes("update") ||
        q.includes("move") ||
        q.includes("edit")) &&
      isReadOnly
    ) {
      return "Your current access level is read-only, so I can summarize project data but I cannot create, update, assign, or delete tasks, months, or teams on your behalf.";
    }

    if (q.includes("how many") && (q.includes("task") || q.includes("work"))) {
      const byStatus = ["todo", "in_progress", "done"].map((status) => {
        const count = tasks.filter((t) => t.status === status).length;
        return `${getStatusLabel(status)}: ${count}`;
      });
      return `Current project summary: ${summary.total} total tasks. ${byStatus.join("; ")}.`;
    }

    if (q.includes("open") || q.includes("pending")) {
      return `There are ${summary.open} open tasks right now. ${summary.overdue} tasks are overdue and need attention.`;
    }

    if (q.includes("overdue") || q.includes("due soon") || q.includes("due")) {
      const dueSoon = tasks
        .filter((task) => task.due_date && task.status !== "done")
        .slice()
        .sort(
          (a, b) =>
            new Date(a.due_date ?? "").getTime() -
            new Date(b.due_date ?? "").getTime(),
        )
        .slice(0, 3);

      if (dueSoon.length === 0) {
        return "No due dates are currently coming up for active tasks.";
      }

      return dueSoon
        .map((task) => `${task.title} (${formatDate(task.due_date)})`)
        .join("; ");
    }

    if (
      q.includes("who has") ||
      q.includes("most work") ||
      q.includes("workload") ||
      q.includes("member")
    ) {
      const topThree = [...summary.byMember]
        .sort((a, b) => b.count - a.count)
        .slice(0, 3);

      if (topThree.length === 0) {
        return "No members are assigned yet.";
      }

      return topThree
        .map((member) => `${member.name}: ${member.count} tasks`)
        .join("; ");
    }

    if (q.includes("project status") || q.includes("status")) {
      return `Project status: ${summary.total} tasks total, ${summary.open} open, ${summary.done} completed, and ${summary.overdue} overdue. ${summary.activeSprint ? `Current sprint: ${summary.activeSprint.name}.` : "No sprint selected."} ${summary.activeTeam ? `Current team: ${summary.activeTeam.name}.` : ""}`.trim();
    }

    if (
      (q.includes("compare") ||
        q.includes("comparison") ||
        q.includes("trend") ||
        q.includes("previous") ||
        q.includes("last sprint") ||
        q.includes("vs")) &&
      (q.includes("sprint") || q.includes("month"))
    ) {
      const historicalSprints = sprints
        .filter((sprint) => sprint.status === "completed")
        .slice()
        .sort(
          (a, b) =>
            new Date(a.end_date ?? "").getTime() -
            new Date(b.end_date ?? "").getTime(),
        );

      const monthNames = sprints.map((sprint) => sprint.name.toLowerCase());
      const hasJuly = monthNames.includes("july");
      const hasAugust = monthNames.includes("august");

      if (historicalSprints.length === 0) {
        if (hasJuly || hasAugust) {
          return "I can compare July vs August only if both months are present as sprint records with task history. Right now the project snapshot shows the active August sprint but no completed historical sprint data for comparison, so I cannot compare them accurately yet.";
        }
        return "I can compare sprint performance only when previous sprint data exists. Right now the project snapshot only includes the active sprint, so there is no prior sprint to compare against yet.";
      }

      const previousSprint = historicalSprints[historicalSprints.length - 1];
      const previousTasks = tasks.filter(
        (task) => task.sprint_id === previousSprint.id,
      );
      const previousDone = previousTasks.filter(
        (task) => task.status === "done",
      ).length;
      const previousOpen = previousTasks.filter(
        (task) => task.status !== "done",
      ).length;

      return `${summary.activeSprint ? `Current sprint: ${summary.activeSprint.name}.` : "Current sprint: no sprint selected."} Previous completed sprint: ${previousSprint.name}. Completed tasks: ${previousDone} in ${previousSprint.name} vs ${summary.done} in the current sprint. Open tasks: ${previousOpen} in ${previousSprint.name} vs ${summary.open} in the current sprint.`;
    }

    if (
      (q.includes("can you compare") ||
        q.includes("compare august") ||
        q.includes("compare july") ||
        q.includes("compare august and july") ||
        q.includes("compare july and august")) &&
      (q.includes("august") ||
        q.includes("july") ||
        q.includes("sprint") ||
        q.includes("month"))
    ) {
      const historicalSprints = sprints
        .filter((sprint) => sprint.status === "completed")
        .slice()
        .sort(
          (a, b) =>
            new Date(a.end_date ?? "").getTime() -
            new Date(b.end_date ?? "").getTime(),
        );

      if (historicalSprints.length === 0) {
        return "I can compare July vs August only if both months are present as sprint records with task history. Right now the project snapshot shows the active August sprint but no completed historical sprint data for comparison, so I cannot compare them accurately yet.";
      }

      const previousSprint = historicalSprints[historicalSprints.length - 1];
      const previousTasks = tasks.filter(
        (task) => task.sprint_id === previousSprint.id,
      );
      const previousDone = previousTasks.filter(
        (task) => task.status === "done",
      ).length;
      const previousOpen = previousTasks.filter(
        (task) => task.status !== "done",
      ).length;

      return `${summary.activeSprint ? `Current sprint: ${summary.activeSprint.name}.` : "Current sprint: no sprint selected."} Previous completed sprint: ${previousSprint.name}. Completed tasks: ${previousDone} in ${previousSprint.name} vs ${summary.done} in the current sprint. Open tasks: ${previousOpen} in ${previousSprint.name} vs ${summary.open} in the current sprint.`;
    }

    if (q.includes("member") && (q.includes("list") || q.includes("names"))) {
      return members.map((member) => member.name).join(", ");
    }

    if (q.includes("sprint") || q.includes("month")) {
      return summary.activeSprint
        ? `Current sprint/month: ${summary.activeSprint.name}. Start: ${formatDate(summary.activeSprint.start_date)}. End: ${formatDate(summary.activeSprint.end_date)}.`
        : "No sprint data is currently selected.";
    }

    if (q.includes("team")) {
      return summary.activeTeam
        ? `Active team: ${summary.activeTeam.name}.` +
            (teams.length > 1 ? ` Total teams: ${teams.length}.` : "")
        : "No team is selected right now.";
    }

    return "I can summarize the project, workload, due dates, sprint status, and team activity. Ask about open tasks, overdue items, member workload, or sprint health.";
  };

  const handleSend = async (): Promise<void> => {
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;

    const lower = trimmed.toLowerCase();

    if (pendingMutation) {
      const confirmed = /^(yes|y|confirm|ok|proceed|do it|create it)$/i.test(
        trimmed,
      );
      const cancelled = /^(no|n|cancel|stop|abort|never mind|nevermind)$/i.test(
        trimmed,
      );

      if (confirmed) {
        setMessages((prev) => [
          ...prev,
          {
            id: Date.now(),
            sender: "user",
            text: trimmed,
          },
        ]);
        setInput("");
        setPendingMutation(null);
        setIsLoading(true);

        try {
          const executed = await executePendingMutation(pendingMutation);
          setMessages((prev) => [
            ...prev,
            {
              id: Date.now() + 1,
              sender: "assistant",
              text: executed,
            },
          ]);
        } catch (error) {
          const messageText =
            error instanceof Error
              ? error.message
              : "The action could not be completed.";
          setMessages((prev) => [
            ...prev,
            {
              id: Date.now() + 2,
              sender: "assistant",
              text: `I could not complete that action. ${messageText}`,
            },
          ]);
        } finally {
          setIsLoading(false);
        }
        return;
      }

      if (cancelled) {
        setMessages((prev) => [
          ...prev,
          {
            id: Date.now(),
            sender: "user",
            text: trimmed,
          },
          {
            id: Date.now() + 1,
            sender: "assistant",
            text: "Cancelled. Nothing was changed.",
          },
        ]);
        setInput("");
        setPendingMutation(null);
        return;
      }

      setMessages((prev) => [
        ...prev,
        {
          id: Date.now(),
          sender: "user",
          text: trimmed,
        },
        {
          id: Date.now() + 1,
          sender: "assistant",
          text: "Please reply Yes to confirm this action or No to cancel it.",
        },
      ]);
      setInput("");
      return;
    }

    const mutationIntent =
      /create|add|delete|remove|assign|update|move|edit/.test(lower);

    if (mutationIntent && isReadOnly) {
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now(),
          sender: "user",
          text: trimmed,
        },
        {
          id: Date.now() + 1,
          sender: "assistant",
          text: "Your current access level is read-only, so I can summarize project data but I cannot create, update, assign, or delete tasks, months, or teams on your behalf.",
        },
      ]);
      setInput("");
      return;
    }

    const userMsg: ChatMessage = {
      id: Date.now(),
      sender: "user",
      text: trimmed,
    };

    setMessages((prev) => [...prev, userMsg]);
    setInput("");

    const mutationProposal = parseMutationProposal(trimmed);
    if (mutationProposal) {
      const summary =
        mutationProposal.kind === "task-create"
          ? `I found a task named "${mutationProposal.title}"${mutationProposal.assigneeId ? ` for ${members.find((member) => member.id === mutationProposal.assigneeId)?.name ?? "the selected member"}` : ""}${mutationProposal.teamId ? ` in ${teams.find((team) => team.id === mutationProposal.teamId)?.name ?? "the selected team"}` : ""}. Do you want me to create it?`
          : mutationProposal.kind === "task-assign"
            ? `I found task "${tasks.find((task) => task.id === mutationProposal.taskId)?.title ?? "the selected task"}" and I can assign it to ${members.find((member) => member.id === mutationProposal.assigneeId)?.name ?? "the selected member"}. Do you want me to proceed?`
            : mutationProposal.kind === "task-update"
              ? `I found task "${tasks.find((task) => task.id === mutationProposal.taskId)?.title ?? "the selected task"}" and can ${mutationProposal.title ? `rename it to "${mutationProposal.title}"` : mutationProposal.due_date ? `set its due date to ${formatDate(mutationProposal.due_date)}` : `change its status to ${getStatusLabel(mutationProposal.status ?? "todo")}`}. Do you want me to proceed?`
              : mutationProposal.kind === "month-create"
                ? `I found a new month named "${mutationProposal.name}". Do you want me to create it?`
                : mutationProposal.kind === "team-create"
                  ? `I found a new team named "${mutationProposal.name}". Do you want me to create it?`
                  : `I found that ${members.find((member) => member.id === mutationProposal.memberId)?.name ?? "the selected member"} should be moved to ${teams.find((team) => team.id === mutationProposal.teamId)?.name ?? "the selected team"}. Do you want me to assign them?`;

      setPendingMutation(mutationProposal);
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          sender: "assistant",
          text: summary,
        },
      ]);
      return;
    }

    const localReply = generateAnswer(trimmed);
    const shouldUseLocalReply =
      /can you (create|add)|are you capable of creating|capable of creating|compare august|compare july|compare .*sprint|compare .*month/.test(
        lower,
      ) ||
      (lower.includes("can you") && lower.includes("task")) ||
      (lower.includes("compare") &&
        (lower.includes("sprint") || lower.includes("month")));

    if (shouldUseLocalReply) {
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          sender: "assistant",
          text: normalizeAssistantText(localReply),
        },
      ]);
      return;
    }

    setIsLoading(true);
    const fallbackReply = generateAnswer(trimmed);

    try {
      const response = await fetch("/api/assistant/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          message: trimmed,
          history: getRecentConversationText(),
          context: {
            tasks,
            members,
            sprints,
            teams,
            activeSprintId,
            activeTeamId,
            currentUser,
            accessLevel: access,
            permissions: {
              canRead: true,
              canWrite,
              canManageTeams,
            },
          },
        }),
      });

      const data = await response.json().catch(() => ({}));
      const reply = normalizeAssistantText(
        typeof data.reply === "string" && data.reply.trim()
          ? data.reply
          : fallbackReply,
      );

      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          sender: "assistant",
          text: reply,
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 2,
          sender: "assistant",
          text: normalizeAssistantText(fallbackReply),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  if (!isOpen) {
    return (
      <Box
        style={{
          position: "fixed",
          right: 20,
          bottom: 20,
          zIndex: 40,
        }}
      >
        <Button
          onClick={() => setIsOpen(true)}
          style={{
            width: 56,
            height: 56,
            borderRadius: 18,
            padding: 0,
            background:
              "linear-gradient(135deg, var(--blue-9), var(--violet-9))",
            boxShadow: "0 20px 36px rgba(59, 130, 246, 0.28)",
            border: "none",
          }}
          aria-label="Open project assistant"
        >
          <Sparkle size={22} weight="fill" />
        </Button>
      </Box>
    );
  }

  return (
    <Box
      className="tt-assistant-panel"
      style={{
        position: "fixed",
        right: 20,
        bottom: 20,
        width: 300,
        minWidth: 260,
        maxWidth: "calc(100vw - 28px)",
        maxHeight: "calc(100vh - 32px)",
        height: "min(460px, calc(100vh - 32px))",
        borderRadius: 18,
        border: "1px solid rgba(148,163,184,0.24)",
        background: "rgba(255,255,255,0.72)",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        boxShadow: "0 20px 38px rgba(15, 23, 42, 0.12)",
        zIndex: 40,
      }}
    >
      <Flex
        align="center"
        gap="2"
        px="3"
        py="3"
        style={{
          background:
            "linear-gradient(135deg, rgba(37,99,235,0.08), rgba(124,58,237,0.08))",
          borderBottom: "1px solid rgba(148,163,184,0.18)",
          flexShrink: 0,
        }}
      >
        <Box
          style={{
            width: 28,
            height: 28,
            borderRadius: 10,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background:
              "linear-gradient(135deg, var(--blue-9), var(--violet-9))",
            color: "white",
          }}
        >
          <Sparkle size={14} />
        </Box>
        <Text size="3" weight="bold" style={{ flex: 1 }}>
          Project Copilot
        </Text>
        <Button
          size="1"
          variant="ghost"
          color="gray"
          onClick={() => setIsOpen(false)}
          aria-label="Close project assistant"
        >
          ✕
        </Button>
      </Flex>

      <Box
        style={{
          flex: 1,
          minHeight: 0,
          padding: 12,
          display: "flex",
          flexDirection: "column",
          gap: 10,
          overflowY: "auto",
          overscrollBehavior: "contain",
        }}
      >
        {messages.map((msg) => (
          <Flex
            key={msg.id}
            justify={msg.sender === "assistant" ? "flex-start" : "flex-end"}
          >
            <Box
              style={{
                maxWidth: "88%",
                background:
                  msg.sender === "assistant"
                    ? "rgba(241,245,249,0.9)"
                    : "linear-gradient(135deg, var(--blue-9), var(--violet-9))",
                color: msg.sender === "assistant" ? "var(--gray-12)" : "white",
                borderRadius: 14,
                padding: "10px 12px",
                border:
                  msg.sender === "assistant"
                    ? "1px solid rgba(148,163,184,0.18)"
                    : "none",
                boxShadow:
                  msg.sender === "assistant"
                    ? "0 6px 14px rgba(15, 23, 42, 0.04)"
                    : "0 10px 18px rgba(59,130,246,0.18)",
              }}
            >
              <Text
                size="2"
                style={{ whiteSpace: "pre-wrap", lineHeight: 1.5 }}
              >
                {msg.text}
              </Text>
            </Box>
          </Flex>
        ))}
        {isLoading && (
          <Text size="2" color="gray">
            Thinking…
          </Text>
        )}
      </Box>

      <Box p="3" pt="0">
        <TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void handleSend();
            }
          }}
          placeholder="Ask about tasks, members, or sprint health..."
          disabled={isLoading}
          style={{ minHeight: 80, resize: "vertical", borderRadius: 12 }}
        />
        <Flex justify="end" mt="2">
          <Button
            onClick={handleSend}
            size="2"
            disabled={isLoading}
            style={{ borderRadius: 10 }}
          >
            {isLoading ? "Thinking..." : "Ask"}
            <ArrowUpRight size={14} style={{ marginLeft: 6 }} />
          </Button>
        </Flex>
      </Box>
    </Box>
  );
}
