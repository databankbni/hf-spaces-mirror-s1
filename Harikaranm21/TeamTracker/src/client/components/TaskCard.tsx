/**
 * TaskCard — displays a single task on the Kanban board.
 * Edit/delete controls are hidden for read-only (non-editor) users.
 * @module components/TaskCard
 */
import React from "react";
import { Badge, Flex, Text, Box, IconButton } from "@radix-ui/themes";
import { PencilSimple, Trash, CalendarBlank } from "@phosphor-icons/react";
import type { Task } from "../../shared/types";
import { parseLabels } from "../utils/labels";
import { formatDueDate, isDueOverdue, isDueSoon } from "../utils/date";

const PRIORITY_COLORS: Record<string, "red" | "orange" | "blue"> = {
  high: "red",
  medium: "orange",
  low: "blue",
};

export interface TaskCardProps {
  task: Task;
  isEditor: boolean;
  canDelete?: boolean;
  onEdit: (task: Task) => void;
  onDelete: (id: number) => void;
  onDragStart: (e: React.DragEvent, taskId: number) => void;
}

export function TaskCard({
  task,
  isEditor,
  canDelete = isEditor,
  onEdit,
  onDelete,
  onDragStart,
}: TaskCardProps): React.ReactElement {
  const labels = parseLabels(task.labels);
  const dueDateLabel = formatDueDate(task.due_date);
  const overdue = isDueOverdue(task.due_date);
  const dueSoon = isDueSoon(task.due_date);

  return (
    <Box
      className="tt-task-card"
      draggable={isEditor}
      onDragStart={(e) => onDragStart(e, task.id)}
      style={{
        background: "var(--color-panel-solid)",
        border: "1px solid var(--gray-a4)",
        borderRadius: "var(--radius-3)",
        padding: "10px 12px",
        cursor: isEditor ? "grab" : "default",
        userSelect: "none",
        boxShadow: "0 1px 3px var(--gray-a3)",
      }}
    >
      <Flex direction="column" gap="2">
        <Flex justify="between" align="start" gap="1">
          <Text
            size="2"
            weight="medium"
            style={{ flex: 1, lineHeight: "1.4", color: "var(--gray-12)" }}
          >
            {task.title}
          </Text>
          {isEditor && (
            <Flex gap="1" style={{ flexShrink: 0 }}>
              <IconButton
                size="1"
                variant="ghost"
                color="gray"
                title="Edit task"
                aria-label="Edit task"
                onClick={() => onEdit(task)}
              >
                <PencilSimple size={13} />
              </IconButton>
              {canDelete && (
                <IconButton
                  size="1"
                  variant="ghost"
                  color="red"
                  title="Delete task"
                  aria-label="Delete task"
                  onClick={() => onDelete(task.id)}
                >
                  <Trash size={13} />
                </IconButton>
              )}
            </Flex>
          )}
        </Flex>

        {task.description && (
          <Text size="1" color="gray" style={{ lineHeight: "1.45" }}>
            {task.description.length > 80
              ? task.description.slice(0, 80) + "…"
              : task.description}
          </Text>
        )}

        <Flex gap="1" wrap="wrap" align="center">
          <Badge
            size="1"
            color={PRIORITY_COLORS[task.priority] ?? "gray"}
            variant="soft"
            style={{ textTransform: "capitalize" }}
          >
            {task.priority}
          </Badge>
          {labels.map((label) => (
            <Badge key={label} size="1" variant="surface" color="gray">
              {label}
            </Badge>
          ))}
        </Flex>

        {task.assignee_name && (
          <Flex align="center" gap="2" style={{ minHeight: 24 }}>
            <Box
              style={{
                width: 20,
                height: 20,
                borderRadius: "50%",
                background: task.assignee_color ?? "var(--accent-9)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
                boxShadow: "0 0 0 2px rgba(255,255,255,0.8)",
              }}
            >
              <Text
                size="1"
                style={{ color: "white", fontWeight: 600, fontSize: 10 }}
              >
                {task.assignee_name[0].toUpperCase()}
              </Text>
            </Box>
            <Text size="1" color="gray" style={{ flex: 1 }}>
              {task.assignee_name}
            </Text>
            {task.sprint_name && (
              <Text size="1" color="gray">
                {task.sprint_name}
              </Text>
            )}
          </Flex>
        )}

        {dueDateLabel && (
          <Flex align="center" gap="1">
            <CalendarBlank
              size={12}
              style={{
                color: overdue
                  ? "var(--red-10)"
                  : dueSoon
                    ? "var(--orange-10)"
                    : "var(--gray-9)",
              }}
            />
            <Text
              size="1"
              style={{
                color: overdue
                  ? "var(--red-10)"
                  : dueSoon
                    ? "var(--orange-10)"
                    : "var(--gray-9)",
              }}
            >
              {dueDateLabel}
            </Text>
          </Flex>
        )}
      </Flex>
    </Box>
  );
}
