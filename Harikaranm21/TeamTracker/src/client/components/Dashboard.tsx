/**
 * Dashboard — metrics and reporting view with charts.
 * Includes a month filter dropdown so all stats/charts reflect a single month.
 * @module components/Dashboard
 */
import React, { useEffect, useState } from 'react';
import { Box, Flex, Text, Card, Select } from '@radix-ui/themes';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell
} from 'recharts';
import type { DashboardStats, VelocityDataPoint, AssigneeDistribution, StatusDistribution, Sprint } from '../../shared/types';
import * as api from '../api';

const STATUS_LABELS: Record<string, string> = {
  todo: 'To Do',
  in_progress: 'In Progress',
  done: 'Done',
};

const CHART_COLORS = ['#6E56CF', '#E5484D', '#46A758', '#0091FF', '#F76B15', '#AB4ABA'];

interface StatCardProps {
  label: string;
  value: number;
  color?: string;
}

function StatCard({ label, value, color }: StatCardProps): React.ReactElement {
  return (
    <Card style={{ flex: 1, minWidth: 130 }}>
      <Flex direction="column" gap="1" p="2">
        <Text size="1" color="gray">{label}</Text>
        <Text size="6" weight="bold" style={{ color: color ?? 'var(--gray-12)' }}>
          {value}
        </Text>
      </Flex>
    </Card>
  );
}

export function Dashboard(): React.ReactElement {
  const [sprints, setSprints] = useState<Sprint[]>([]);
  const [selectedSprintId, setSelectedSprintId] = useState<number | null>(null);

  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [velocity, setVelocity] = useState<VelocityDataPoint[]>([]);
  const [assigneeDist, setAssigneeDist] = useState<AssigneeDistribution[]>([]);
  const [statusDist, setStatusDist] = useState<StatusDistribution[]>([]);
  const [loading, setLoading] = useState(true);
  const [statsLoading, setStatsLoading] = useState(false);

  // Load sprints for the filter dropdown once
  useEffect(() => {
    // Trigger maintenance so past months are completed and current month exists,
    // then fetch the up-to-date sprint list and default to the active month.
    api.maintainSprints()
      .catch(console.error)
      .finally(() => {
        api.fetchSprints()
          .then((data) => {
            setSprints(data);
            // Default to the active month; if none, fall back to the most recent month
            const active = data.find((s) => s.status === 'active');
            if (active) {
              setSelectedSprintId(active.id);
            } else if (data.length > 0) {
              // Most recent by start_date
              const latest = [...data].sort((a, b) => b.start_date.localeCompare(a.start_date))[0];
              setSelectedSprintId(latest.id);
            }
          })
          .catch(console.error);
      });
  }, []);

  // Load velocity chart once (always all-months)
  useEffect(() => {
    api.fetchVelocity().then(setVelocity).catch(console.error);
  }, []);

  // Re-fetch stats/charts whenever the sprint filter changes
  useEffect(() => {
    const id = selectedSprintId ?? undefined;
    setStatsLoading(true);
    Promise.all([
      api.fetchDashboardStats(id),
      api.fetchAssigneeDistribution(id),
      api.fetchStatusDistribution(id),
    ]).then(([s, a, sd]) => {
      setStats(s);
      setAssigneeDist(a);
      setStatusDist(sd);
    }).catch(console.error).finally(() => {
      setStatsLoading(false);
      setLoading(false);
    });
  }, [selectedSprintId]);

  if (loading) {
    return (
      <Flex align="center" justify="center" style={{ height: 200 }}>
        <Text color="gray">Loading dashboard…</Text>
      </Flex>
    );
  }

  const statusChartData = statusDist.map((d) => ({
    name: STATUS_LABELS[d.status] ?? d.status,
    count: d.count,
  }));

  const selectedSprint = sprints.find((s) => s.id === selectedSprintId);

  return (
    <Flex direction="column" gap="5">
      {/* Header row with title + month filter */}
      <Flex align="center" justify="between" gap="3" wrap="wrap">
        <Text size="5" weight="bold">Dashboard</Text>

        <Flex align="center" gap="2">
          <Text size="2" color="gray" style={{ flexShrink: 0 }}>Month:</Text>
          <Select.Root
            value={selectedSprintId == null ? 'all' : String(selectedSprintId)}
            onValueChange={(val) => setSelectedSprintId(val === 'all' ? null : Number(val))}
          >
            <Select.Trigger
              placeholder="All months"
              style={{ minWidth: 160 }}
            />
            <Select.Content>
              <Select.Item value="all">All months</Select.Item>
              {[...sprints]
                .sort((a, b) => b.start_date.localeCompare(a.start_date))
                .map((s) => (
                  <Select.Item key={s.id} value={String(s.id)}>
                    {s.name}
                  </Select.Item>
                ))}
            </Select.Content>
          </Select.Root>

          {selectedSprint && (
            <Text size="1" color="gray">{selectedSprint.name}</Text>
          )}
        </Flex>
      </Flex>

      {/* Stats row */}
      {stats && (
        <Box style={{ opacity: statsLoading ? 0.5 : 1, transition: 'opacity 0.2s' }}>
          <Flex gap="3" wrap="wrap">
            <StatCard label="Total Tasks" value={stats.totalTasks} />
            <StatCard label="Open Tasks" value={stats.openTasks} color="var(--blue-10)" />
            <StatCard label="In Progress" value={stats.inProgressTasks} color="var(--orange-10)" />
            <StatCard label="Completed" value={stats.completedTasks} color="var(--green-10)" />
            {selectedSprintId == null && (
              <>
                <StatCard label="Team Members" value={stats.totalMembers} />
                <StatCard label="Active Month" value={stats.activeSprints} color="var(--purple-10)" />
              </>
            )}
          </Flex>
        </Box>
      )}

      {/* Charts */}
      <Box style={{ opacity: statsLoading ? 0.5 : 1, transition: 'opacity 0.2s' }}>
        <Flex gap="4" wrap="wrap">
          {/* Velocity chart — always all-months, no filter applied */}
          {selectedSprintId == null && (
            <Box style={{ flex: '2 1 400px' }}>
              <Text size="3" weight="medium" mb="2" style={{ display: 'block' }}>
                Monthly Velocity
              </Text>
              {velocity.length === 0 ? (
                <Text size="2" color="gray">No data yet. Create months and assign tasks.</Text>
              ) : (
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={velocity} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--gray-a5)" />
                    <XAxis dataKey="sprint_name" tick={{ fontSize: 12 }} />
                    <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="total" name="Total" fill="var(--gray-a8)" radius={[3, 3, 0, 0]} />
                    <Bar dataKey="completed" name="Completed" fill="#46A758" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </Box>
          )}

          {/* Status distribution */}
          <Box style={{ flex: '1 1 220px' }}>
            <Text size="3" weight="medium" mb="2" style={{ display: 'block' }}>
              Tasks by Status
              {selectedSprint && <Text size="2" color="gray" style={{ fontWeight: 400 }}> — {selectedSprint.name}</Text>}
            </Text>
            {statusChartData.length === 0 ? (
              <Text size="2" color="gray">No tasks {selectedSprint ? `in ${selectedSprint.name}` : 'yet'}.</Text>
            ) : (
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie
                    data={statusChartData}
                    dataKey="count"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    outerRadius={80}
                    label={({ name, count }) => `${name}: ${count}`}
                    labelLine={false}
                  >
                    {statusChartData.map((_, i) => (
                      <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            )}
          </Box>
        </Flex>
      </Box>

      {/* Assignee distribution */}
      <Box style={{ opacity: statsLoading ? 0.5 : 1, transition: 'opacity 0.2s' }}>
        <Text size="3" weight="medium" mb="2" style={{ display: 'block' }}>
          Work Distribution by Assignee
          {selectedSprint && <Text size="2" color="gray" style={{ fontWeight: 400 }}> — {selectedSprint.name}</Text>}
        </Text>
        {assigneeDist.length === 0 ? (
          <Text size="2" color="gray">No members yet.</Text>
        ) : (
          <ResponsiveContainer width="100%" height={Math.max(180, assigneeDist.length * 40)}>
            <BarChart
              data={assigneeDist}
              layout="vertical"
              margin={{ top: 4, right: 24, left: 80, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="var(--gray-a5)" />
              <XAxis type="number" tick={{ fontSize: 12 }} allowDecimals={false} />
              <YAxis dataKey="name" type="category" tick={{ fontSize: 12 }} width={80} />
              <Tooltip />
              <Bar dataKey="count" name="Tasks" radius={[0, 3, 3, 0]}>
                {assigneeDist.map((entry, i) => (
                  <Cell key={i} fill={entry.color ?? CHART_COLORS[i % CHART_COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </Box>
    </Flex>
  );
}
