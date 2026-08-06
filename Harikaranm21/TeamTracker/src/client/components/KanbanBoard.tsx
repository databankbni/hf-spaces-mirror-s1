/**
 * KanbanBoard — drag-and-drop board with four status columns.
 * Includes quick member filter chips (like Jira) to show one person's tasks.
 * All mutations are delegated up to App via callbacks (optimistic updates live there).
 * Month filtering is handled upstream in App — this component receives pre-filtered tasks.
 * @module components/KanbanBoard
 */
import React, { useState } from 'react';
import { Box, Flex, Text, Button, ScrollArea, Badge } from '@radix-ui/themes';
import { Plus } from '@phosphor-icons/react';
import { TaskCard } from './TaskCard';
import type { Task, TaskStatus, Member } from '../../shared/types';

const COLUMNS: { status: TaskStatus; label: string; color: string }[] = [
  { status: 'todo', label: 'To Do', color: 'var(--gray-9)' },
  { status: 'in_progress', label: 'In Progress', color: 'var(--blue-9)' },
  { status: 'done', label: 'Done', color: 'var(--green-9)' },
];

export interface KanbanBoardProps {
  tasks: Task[];
  members: Member[];
  isEditor: boolean;
  onEditTask: (task: Task) => void;
  onDeleteTask: (id: number) => void;
  onMoveTask: (id: number, status: TaskStatus, position: number) => void;
  onCreateTask: (status: TaskStatus) => void;
}

export function KanbanBoard({
  tasks, members, isEditor, onEditTask, onDeleteTask, onMoveTask, onCreateTask
}: KanbanBoardProps): React.ReactElement {
  const [dragOverCol, setDragOverCol] = useState<TaskStatus | null>(null);
  const [filterMemberId, setFilterMemberId] = useState<number | null>(null);

  const filteredTasks = filterMemberId === null
    ? tasks
    : tasks.filter(t => t.assignee_id === filterMemberId);

  const tasksByStatus = (status: TaskStatus): Task[] =>
    filteredTasks.filter((t) => t.status === status);

  const handleDragStart = (e: React.DragEvent, taskId: number): void => {
    if (!isEditor) return;
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('taskId', String(taskId));
  };

  const handleDragOver = (e: React.DragEvent, status: TaskStatus): void => {
    if (!isEditor) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setDragOverCol(status);
  };

  const handleDrop = (e: React.DragEvent, status: TaskStatus): void => {
    if (!isEditor) return;
    e.preventDefault();
    const taskId = Number(e.dataTransfer.getData('taskId'));
    setDragOverCol(null);
    if (!taskId) return;
    const colTasks = tasksByStatus(status);
    onMoveTask(taskId, status, colTasks.length);
  };

  return (
    <Flex direction="column" gap="3" style={{ height: '100%' }}>
      {/* Quick member filters */}
      {members.length > 0 && (
        <Flex align="center" gap="2" style={{ flexShrink: 0, flexWrap: 'wrap' }}>
          <Text size="1" color="gray" style={{ flexShrink: 0 }}>Filter:</Text>
          <Button
            size="1"
            variant={filterMemberId === null ? 'solid' : 'soft'}
            color={filterMemberId === null ? 'accent' : 'gray'}
            onClick={() => setFilterMemberId(null)}
            style={{ borderRadius: 999 }}
          >
            All
          </Button>
          {members.map(m => (
            <Button
              key={m.id}
              size="1"
              variant={filterMemberId === m.id ? 'solid' : 'soft'}
              color="gray"
              onClick={() => setFilterMemberId(filterMemberId === m.id ? null : m.id)}
              style={{
                borderRadius: 999,
                borderLeft: `3px solid ${m.avatar_color}`,
                background: filterMemberId === m.id ? m.avatar_color + 'cc' : m.avatar_color + '22',
                color: filterMemberId === m.id ? 'white' : 'inherit',
              }}
            >
              <Box
                style={{
                  width: 16, height: 16, borderRadius: '50%',
                  background: m.avatar_color, display: 'flex',
                  alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                }}
              >
                <Text size="1" style={{ color: 'white', fontSize: 9, fontWeight: 700 }}>
                  {m.name[0].toUpperCase()}
                </Text>
              </Box>
              {m.name}
            </Button>
          ))}
        </Flex>
      )}

      {/* Board columns */}
      <Flex gap="3" style={{ overflowX: 'auto', flex: 1, paddingBottom: 8 }}>
        {COLUMNS.map((col) => {
          const colTasks = tasksByStatus(col.status);
          const isDragOver = dragOverCol === col.status;

          return (
            <Box
              key={col.status}
              style={{
                minWidth: 260,
                width: 280,
                flexShrink: 0,
                display: 'flex',
                flexDirection: 'column',
                gap: 8,
              }}
            >
              <Flex
                align="center"
                gap="2"
                px="2"
                py="1"
                style={{ borderRadius: 'var(--radius-2)', background: 'var(--gray-a2)' }}
              >
                <Box style={{ width: 10, height: 10, borderRadius: '50%', background: col.color, flexShrink: 0 }} />
                <Text size="2" weight="medium" style={{ flex: 1 }}>{col.label}</Text>
                <Badge size="1" variant="soft" color="gray">{colTasks.length}</Badge>
              </Flex>

              <ScrollArea style={{ flex: 1, minHeight: 120, maxHeight: 'calc(100vh - 240px)' }}>
                <Flex
                  direction="column"
                  gap="2"
                  p="2"
                  style={{
                    minHeight: 80,
                    borderRadius: 'var(--radius-3)',
                    border: isDragOver ? '2px dashed var(--accent-8)' : '2px dashed transparent',
                    background: isDragOver ? 'var(--accent-a2)' : 'transparent',
                    transition: 'background 0.15s, border-color 0.15s',
                  }}
                  onDragOver={(e) => handleDragOver(e, col.status)}
                  onDragLeave={() => setDragOverCol(null)}
                  onDrop={(e) => handleDrop(e, col.status)}
                >
                  {colTasks.map((task) => (
                    <TaskCard
                      key={task.id}
                      task={task}
                      isEditor={isEditor}
                      onEdit={onEditTask}
                      onDelete={onDeleteTask}
                      onDragStart={handleDragStart}
                    />
                  ))}
                  {colTasks.length === 0 && !isDragOver && (
                    <Text size="1" color="gray" align="center" style={{ padding: '16px 0', opacity: 0.5 }}>
                      No tasks
                    </Text>
                  )}
                </Flex>
              </ScrollArea>

              {isEditor && (
                <Button
                  size="1"
                  variant="ghost"
                  color="gray"
                  title={`Add task to ${col.label}`}
                  onClick={() => onCreateTask(col.status)}
                  style={{ width: '100%' }}
                >
                  <Plus size={13} />
                  Add task
                </Button>
              )}
            </Box>
          );
        })}
      </Flex>
    </Flex>
  );
}
