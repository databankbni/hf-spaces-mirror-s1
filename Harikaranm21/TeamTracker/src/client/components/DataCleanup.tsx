/**
 * DataCleanup — admin panel for bulk deleting old data to free storage.
 * Only accessible to admins.
 * @module components/DataCleanup
 */
import React, { useState, useEffect } from 'react';
import { Box, Flex, Text, Button, Card, Badge, Select, Callout } from '@radix-ui/themes';
import { Trash, CheckCircle, Info } from '@phosphor-icons/react';
import * as api from '../api';
import { useConfirm } from '../hooks/useConfirm';

export function DataCleanup(): React.ReactElement {
  const [stats, setStats] = useState<api.CleanupStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');
  const [calendarMonths, setCalendarMonths] = useState('3');
  const { confirm, ConfirmDialog } = useConfirm();

  const loadStats = async () => {
    try {
      const s = await api.fetchAdminStats();
      setStats(s);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => { loadStats(); }, []);

  const run = async (label: string, action: () => Promise<{ message: string }>) => {
    const ok = await confirm({
      title: `${label}`,
      description: 'This cannot be undone. Make sure you have backed up anything important.',
      confirmLabel: 'Delete',
      confirmColor: 'red',
    });
    if (!ok) return;
    try {
      const result = await action();
      setMessage(result.message);
      await loadStats();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Failed');
    }
  };

  return (
    <Box>
      {ConfirmDialog}
      <Text size="4" weight="bold" mb="3" style={{ display: 'block' }}>Data Cleanup</Text>

      <Callout.Root color="blue" mb="4">
        <Callout.Icon><Info size={16} /></Callout.Icon>
        <Callout.Text>
          SQLite databases are very compact — a team of 20 people using this app for years would use less than 50MB.
          Only clean up if you genuinely want to remove old data.
        </Callout.Text>
      </Callout.Root>

      {message && (
        <Callout.Root color="green" mb="4">
          <Callout.Icon><CheckCircle size={16} /></Callout.Icon>
          <Callout.Text>{message}</Callout.Text>
        </Callout.Root>
      )}

      {/* Stats */}
      {loading ? (
        <Text color="gray">Loading stats…</Text>
      ) : stats && (
        <Flex gap="3" wrap="wrap" mb="5">
          {[
            { label: 'Total Tasks', value: stats.tasks, sub: `${stats.doneTasks} completed`, color: 'gray' },
            { label: 'Months', value: stats.months, sub: `${stats.completedMonths} completed`, color: 'gray' },
            { label: 'Calendar Events', value: stats.calendarEvents, sub: 'all users', color: 'gray' },
            { label: 'Team Members', value: stats.members, color: 'gray' },
            { label: 'Users', value: stats.users, color: 'gray' },
          ].map(stat => (
            <Card key={stat.label} style={{ minWidth: 130 }}>
              <Flex direction="column" gap="1" p="2">
                <Text size="1" color="gray">{stat.label}</Text>
                <Text size="5" weight="bold">{stat.value}</Text>
                {stat.sub && <Text size="1" color="gray">{stat.sub}</Text>}
              </Flex>
            </Card>
          ))}
        </Flex>
      )}

      {/* Cleanup actions */}
      <Flex direction="column" gap="3">
        <Card>
          <Flex justify="between" align="center" p="3">
            <Box>
              <Text size="3" weight="medium">Delete completed tasks</Text>
              <Text size="1" color="gray" style={{ display: 'block' }}>
                Removes all tasks with status "Done" ({stats?.doneTasks ?? 0} tasks)
              </Text>
            </Box>
            <Button color="red" variant="soft" onClick={() => run('Delete completed tasks', api.cleanupDoneTasks)}>
              <Trash size={14} /> Delete
            </Button>
          </Flex>
        </Card>

        <Card>
          <Flex justify="between" align="center" p="3">
            <Box>
              <Text size="3" weight="medium">Delete completed months</Text>
              <Text size="1" color="gray" style={{ display: 'block' }}>
                Removes all months marked Completed ({stats?.completedMonths ?? 0} months). Tasks become unassigned.
              </Text>
            </Box>
            <Button color="red" variant="soft" onClick={() => run('Delete completed months', api.cleanupCompletedMonths)}>
              <Trash size={14} /> Delete
            </Button>
          </Flex>
        </Card>

        <Card>
          <Flex justify="between" align="center" p="3">
            <Box style={{ flex: 1 }}>
              <Text size="3" weight="medium">Delete old calendar events</Text>
              <Text size="1" color="gray" style={{ display: 'block' }}>
                Removes calendar events older than the selected period (all users)
              </Text>
            </Box>
            <Flex align="center" gap="2">
              <Select.Root value={calendarMonths} onValueChange={setCalendarMonths}>
                <Select.Trigger style={{ minWidth: 110 }} />
                <Select.Content>
                  <Select.Item value="1">1 month ago</Select.Item>
                  <Select.Item value="3">3 months ago</Select.Item>
                  <Select.Item value="6">6 months ago</Select.Item>
                  <Select.Item value="12">1 year ago</Select.Item>
                </Select.Content>
              </Select.Root>
              <Button color="red" variant="soft" onClick={() => run('Delete old calendar events', () => api.cleanupOldCalendar(Number(calendarMonths)))}>
                <Trash size={14} /> Delete
              </Button>
            </Flex>
          </Flex>
        </Card>

        <Card style={{ border: '1px solid var(--red-a6)' }}>
          <Flex justify="between" align="center" p="3">
            <Box>
              <Text size="3" weight="medium" color="red">Clean everything</Text>
              <Text size="1" color="gray" style={{ display: 'block' }}>
                Delete done tasks + completed months + calendar events older than {calendarMonths} month(s)
              </Text>
            </Box>
            <Button color="red" onClick={() => run('Clean all old data', () => api.cleanupAll(Number(calendarMonths)))}>
              <Trash size={14} /> Clean All
            </Button>
          </Flex>
        </Card>
      </Flex>
    </Box>
  );
}
