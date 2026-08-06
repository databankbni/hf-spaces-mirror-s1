/**
 * SprintPanel — monthly work periods.
 * Status is automatically derived: if end_date is in the past the sprint is displayed as
 * completed regardless of the stored value (the server will persist this on next maintain call).
 * @module components/SprintPanel
 */
import React, { useState } from 'react';
import {
  Box, Flex, Text, Button, Badge, Dialog,
  TextField, Select, IconButton
} from '@radix-ui/themes';
import { Plus, Trash, PencilSimple } from '@phosphor-icons/react';
import type { Sprint, CreateSprintInput } from '../../shared/types';
import * as api from '../api';
import { useConfirm } from '../hooks/useConfirm';

export interface SprintPanelProps {
  sprints: Sprint[];
  isEditor: boolean;
  onSprintsChange: () => void;
}

const STATUS_COLORS: Record<string, 'blue' | 'green'> = {
  active: 'blue',
  completed: 'green',
};

const STATUS_LABELS: Record<string, string> = {
  active: 'Active',
  completed: 'Completed',
};

/**
 * Derives the display status from the sprint's end_date in real time.
 * If today is past the end_date, it's completed regardless of stored status.
 */
function deriveDisplayStatus(sprint: Sprint): 'active' | 'completed' {
  if (sprint.status === 'completed') return 'completed';
  // Compare against today's date (YYYY-MM-DD) without time zone issues
  const pad = (n: number) => String(n).padStart(2, '0');
  const now = new Date();
  const todayStr = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  return sprint.end_date < todayStr ? 'completed' : 'active';
}

export function SprintPanel({ sprints, isEditor, onSprintsChange }: SprintPanelProps): React.ReactElement {
  const { confirm, ConfirmDialog } = useConfirm();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editSprint, setEditSprint] = useState<Sprint | undefined>();
  const [name, setName] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [status, setStatus] = useState<'active' | 'completed'>('active');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const openCreate = (): void => {
    setEditSprint(undefined);
    setName('');
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, '0');
    const lastDay = new Date(y, now.getMonth() + 1, 0).getDate();
    setStartDate(`${y}-${m}-01`);
    setEndDate(`${y}-${m}-${lastDay}`);
    setStatus('active');
    setError('');
    setDialogOpen(true);
  };

  const openEdit = (sprint: Sprint): void => {
    setEditSprint(sprint);
    setName(sprint.name);
    setStartDate(sprint.start_date);
    setEndDate(sprint.end_date);
    setStatus(sprint.status === 'completed' ? 'completed' : 'active');
    setError('');
    setDialogOpen(true);
  };

  const handleSave = async (): Promise<void> => {
    if (!name.trim() || !startDate || !endDate) {
      setError('All fields are required');
      return;
    }
    if (endDate < startDate) {
      setError('End date must be after start date');
      return;
    }
    setSaving(true);
    try {
      const input: CreateSprintInput = {
        name: name.trim(),
        start_date: startDate,
        end_date: endDate,
        status,
      };
      if (editSprint) {
        await api.updateSprint(editSprint.id, input);
      } else {
        await api.createSprint(input);
      }
      onSprintsChange();
      setDialogOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number): Promise<void> => {
    const ok = await confirm({
      title: 'Delete month',
      description: 'Tasks assigned to this month will become unscheduled.',
      confirmLabel: 'Delete',
    });
    if (!ok) return;
    await api.deleteSprint(id).catch(console.error);
    onSprintsChange();
  };

  const formatDateRange = (start: string, end: string): string => {
    const s = new Date(start + 'T00:00:00');
    const e = new Date(end + 'T00:00:00');
    return `${s.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })} → ${e.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}`;
  };

  // Sort: active first, then by start date desc
  const sorted = [...sprints].sort((a, b) => {
    if (a.status !== 'completed' && b.status === 'completed') return -1;
    if (a.status === 'completed' && b.status !== 'completed') return 1;
    return b.start_date.localeCompare(a.start_date);
  });

  return (
    <Box>
      {ConfirmDialog}
      <Flex justify="between" align="center" mb="3">
        <Text size="4" weight="bold">Months</Text>
        {isEditor && (
          <Button size="2" title="Create month" onClick={openCreate}>
            <Plus size={15} /> New Month
          </Button>
        )}
      </Flex>

      <Flex direction="column" gap="2">
        {sorted.length === 0 && (
          <Text size="2" color="gray">No months yet. Create one to start planning.</Text>
        )}
        {sorted.map((sprint) => {
          const displayStatus = deriveDisplayStatus(sprint);
          return (
            <Box
              key={sprint.id}
              p="3"
              style={{
                background: 'var(--color-panel-solid)',
                border: displayStatus === 'active'
                  ? '1px solid var(--blue-a6)'
                  : '1px solid var(--gray-a4)',
                borderRadius: 'var(--radius-3)',
              }}
            >
              <Flex justify="between" align="center">
                <Flex direction="column" gap="1">
                  <Flex align="center" gap="2">
                    <Text size="3" weight="medium">{sprint.name}</Text>
                    <Badge size="1" color={STATUS_COLORS[displayStatus]} variant="soft">
                      {STATUS_LABELS[displayStatus]}
                    </Badge>
                  </Flex>
                  <Text size="1" color="gray">
                    {formatDateRange(sprint.start_date, sprint.end_date)}
                  </Text>
                </Flex>
                {isEditor && (
                  <Flex gap="1" align="center">
                    <IconButton
                      size="1"
                      variant="ghost"
                      color="gray"
                      title="Edit month"
                      aria-label="Edit month"
                      onClick={() => openEdit(sprint)}
                    >
                      <PencilSimple size={14} />
                    </IconButton>
                    <IconButton
                      size="1"
                      variant="ghost"
                      color="red"
                      title="Delete month"
                      aria-label="Delete month"
                      onClick={() => handleDelete(sprint.id)}
                    >
                      <Trash size={14} />
                    </IconButton>
                  </Flex>
                )}
              </Flex>
            </Box>
          );
        })}
      </Flex>

      <Dialog.Root open={dialogOpen} onOpenChange={(o) => !o && setDialogOpen(false)}>
        <Dialog.Content style={{ maxWidth: 420 }}>
          <Dialog.Title>{editSprint ? 'Edit Month' : 'New Month'}</Dialog.Title>
          <Flex direction="column" gap="3" mt="3">
            <Box>
              <Text as="label" size="2" weight="medium" htmlFor="sprint-name">Name *</Text>
              <TextField.Root
                id="sprint-name"
                mt="1"
                placeholder="July 2026"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </Box>
            <Flex gap="3">
              <Box style={{ flex: 1 }}>
                <Text as="label" size="2" weight="medium" htmlFor="sprint-start">Start Date *</Text>
                <TextField.Root
                  id="sprint-start"
                  mt="1"
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                />
              </Box>
              <Box style={{ flex: 1 }}>
                <Text as="label" size="2" weight="medium" htmlFor="sprint-end">End Date *</Text>
                <TextField.Root
                  id="sprint-end"
                  mt="1"
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                />
              </Box>
            </Flex>
            <Box>
              <Text as="label" size="2" weight="medium">Status</Text>
              <Select.Root value={status} onValueChange={(v) => setStatus(v as 'active' | 'completed')}>
                <Select.Trigger mt="1" style={{ width: '100%' }} />
                <Select.Content>
                  <Select.Item value="active">Active</Select.Item>
                  <Select.Item value="completed">Completed</Select.Item>
                </Select.Content>
              </Select.Root>
            </Box>
            {error && <Text size="2" color="red">{error}</Text>}
          </Flex>
          <Flex gap="3" mt="4" justify="end">
            <Dialog.Close>
              <Button variant="soft" color="gray">Cancel</Button>
            </Dialog.Close>
            <Button onClick={handleSave} loading={saving}>
              {editSprint ? 'Save' : 'Create Month'}
            </Button>
          </Flex>
        </Dialog.Content>
      </Dialog.Root>
    </Box>
  );
}
