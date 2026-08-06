/**
 * TaskDialog — create/edit task modal using Radix Dialog.
 * @module components/TaskDialog
 */
import React, { useState, useEffect } from 'react';
import {
  Dialog, Flex, Button, TextField, TextArea,
  Select, Text, Box
} from '@radix-ui/themes';
import type { Task, Member, Sprint, TaskStatus, TaskPriority, CreateTaskInput } from '../../shared/types';
import { formatDueDate, isDueOverdue, isDueSoon } from '../utils/date';
import { TaskComments } from './TaskComments';

export interface TaskDialogProps {
  /** Whether the dialog is open */
  open: boolean;
  /** Task to edit; undefined = create mode */
  task?: Task;
  /** Initial status for new tasks */
  defaultStatus?: TaskStatus;
  members: Member[];
  sprints: Sprint[];
  onSave: (input: CreateTaskInput) => Promise<void>;
  onClose: () => void;
}

export function TaskDialog({
  open, task, defaultStatus, members, sprints, onSave, onClose
}: TaskDialogProps): React.ReactElement {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [status, setStatus] = useState<TaskStatus>('todo');
  const [priority, setPriority] = useState<TaskPriority>('medium');
  const [assigneeId, setAssigneeId] = useState<string>('none');
  const [sprintId, setSprintId] = useState<string>('none');
  const [labels, setLabels] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) {
      setTitle(task?.title ?? '');
      setDescription(task?.description ?? '');
      setStatus(task?.status ?? defaultStatus ?? 'todo');
      setPriority(task?.priority ?? 'medium');
      setAssigneeId(task?.assignee_id ? String(task.assignee_id) : 'none');
      setSprintId(task?.sprint_id ? String(task.sprint_id) : 'none');
      setLabels(task?.labels ?? '');
      setDueDate(task?.due_date ?? '');
      setError('');
    }
  }, [open, task, defaultStatus]);

  const handleSave = async (): Promise<void> => {
    if (!title.trim()) { setError('Title is required'); return; }
    setSaving(true);
    try {
      await onSave({
        title: title.trim(),
        description,
        status,
        priority,
        assignee_id: assigneeId === 'none' ? null : Number(assigneeId),
        sprint_id: sprintId === 'none' ? null : Number(sprintId),
        labels,
        due_date: dueDate || null,
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Content style={{ maxWidth: 520 }}>
        <Dialog.Title>{task ? 'Edit Task' : 'New Task'}</Dialog.Title>

        <Flex direction="column" gap="3" mt="3">
          <Box>
            <Text as="label" size="2" weight="medium" htmlFor="task-title">
              Title *
            </Text>
            <TextField.Root
              id="task-title"
              mt="1"
              placeholder="Task title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </Box>

          <Box>
            <Text as="label" size="2" weight="medium" htmlFor="task-desc">
              Description
            </Text>
            <TextArea
              id="task-desc"
              mt="1"
              placeholder="Optional description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
            />
          </Box>

          <Flex gap="3">
            <Box style={{ flex: 1 }}>
              <Text as="label" size="2" weight="medium">Status</Text>
              <Select.Root value={status} onValueChange={(v) => setStatus(v as TaskStatus)}>
                <Select.Trigger mt="1" style={{ width: '100%' }} />
                <Select.Content>
                  <Select.Item value="todo">To Do</Select.Item>
                  <Select.Item value="in_progress">In Progress</Select.Item>
                  <Select.Item value="done">Done</Select.Item>
                </Select.Content>
              </Select.Root>
            </Box>

            <Box style={{ flex: 1 }}>
              <Text as="label" size="2" weight="medium">Priority</Text>
              <Select.Root value={priority} onValueChange={(v) => setPriority(v as TaskPriority)}>
                <Select.Trigger mt="1" style={{ width: '100%' }} />
                <Select.Content>
                  <Select.Item value="high">High</Select.Item>
                  <Select.Item value="medium">Medium</Select.Item>
                  <Select.Item value="low">Low</Select.Item>
                </Select.Content>
              </Select.Root>
            </Box>
          </Flex>

          <Flex gap="3">
            <Box style={{ flex: 1 }}>
              <Text as="label" size="2" weight="medium">Assignee</Text>
              <Select.Root value={assigneeId} onValueChange={setAssigneeId}>
                <Select.Trigger mt="1" style={{ width: '100%' }} />
                <Select.Content>
                  <Select.Item value="none">Unassigned</Select.Item>
                  {members.map((m) => (
                    <Select.Item key={m.id} value={String(m.id)}>{m.name}</Select.Item>
                  ))}
                </Select.Content>
              </Select.Root>
            </Box>

            <Box style={{ flex: 1 }}>
              <Text as="label" size="2" weight="medium">Month</Text>
              <Select.Root value={sprintId} onValueChange={setSprintId}>
                <Select.Trigger mt="1" style={{ width: '100%' }} />
                <Select.Content>
                  <Select.Item value="none">No Month</Select.Item>
                  {sprints.map((s) => (
                    <Select.Item key={s.id} value={String(s.id)}>{s.name}</Select.Item>
                  ))}
                </Select.Content>
              </Select.Root>
            </Box>
          </Flex>

          <Box>
            <Text as="label" size="2" weight="medium" htmlFor="task-labels">
              Labels
            </Text>
            <TextField.Root
              id="task-labels"
              mt="1"
              placeholder="frontend, bug, feature (comma-separated)"
              value={labels}
              onChange={(e) => setLabels(e.target.value)}
            />
          </Box>

          <Box>
            <Text as="label" size="2" weight="medium" htmlFor="task-due">
              Due Date
            </Text>
            <TextField.Root
              id="task-due"
              mt="1"
              type="date"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
            />
          </Box>

          {error && <Text size="2" color="red">{error}</Text>}
        </Flex>

        {/* Comments — only show when editing an existing task */}
        {task && <TaskComments taskId={task.id} />}

        <Flex gap="3" mt="4" justify="end">
          <Dialog.Close>
            <Button variant="soft" color="gray" title="Cancel">Cancel</Button>
          </Dialog.Close>
          <Button
            title={task ? 'Save changes' : 'Create task'}
            onClick={handleSave}
            loading={saving}
          >
            {task ? 'Save Changes' : 'Create Task'}
          </Button>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
