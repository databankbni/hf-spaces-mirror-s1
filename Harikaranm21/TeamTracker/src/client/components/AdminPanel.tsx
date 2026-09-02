/**
 * AdminPanel — manage users, approve pending registrations, data cleanup.
 * Only visible to admins.
 * @module components/AdminPanel
 */
import React, { useState, useEffect, useCallback } from "react";
import {
  Box,
  Flex,
  Text,
  Button,
  Badge,
  Select,
  IconButton,
  Tabs,
  Dialog,
  TextField,
} from "@radix-ui/themes";
import { Trash, CheckCircle, Key } from "@phosphor-icons/react";
import { DataCleanup } from "./DataCleanup";
import * as api from "../api";
import type { AuthUser, Team } from "../../shared/types";

const ROLE_COLORS: Record<string, "orange" | "blue" | "purple" | "gray"> = {
  pending: "orange",
  viewer: "gray",
  editor: "blue",
  admin: "purple",
};

export function AdminPanel(): React.ReactElement {
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [resetUserId, setResetUserId] = useState<number | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [resetError, setResetError] = useState("");
  const [resetSaving, setResetSaving] = useState(false);
  const [teams, setTeams] = useState<Team[]>([]);
  const [newTeamName, setNewTeamName] = useState("");

  const loadUsers = useCallback(async (): Promise<void> => {
    try {
      const data = await api.fetchAllUsers();
      setUsers(data as AuthUser[]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load users");
    }
  }, []);

  useEffect(() => {
    loadUsers().finally(() => setLoading(false));
    api
      .fetchTeams()
      .then(setTeams)
      .catch(() => setError("Failed to load teams"));
  }, [loadUsers]);

  const handleRoleChange = async (id: number, role: string): Promise<void> => {
    try {
      await api.updateUserRole(id, role);
      await loadUsers();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update role");
    }
  };

  const handleDelete = async (id: number, username: string): Promise<void> => {
    if (!confirm(`Remove user "${username}"?`)) return;
    try {
      await api.deleteUser(id);
      await loadUsers();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete user");
    }
  };

  const handleTeamChange = async (id: number, value: string): Promise<void> => {
    try {
      await api.updateUserTeam(id, value === "none" ? null : Number(value));
      await loadUsers();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update team");
    }
  };

  const handleCreateTeam = async (): Promise<void> => {
    if (!newTeamName.trim()) return;
    try {
      const team = await api.createTeam({ name: newTeamName.trim() });
      setTeams((current) =>
        [...current, team].sort((a, b) => a.name.localeCompare(b.name)),
      );
      setNewTeamName("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create team");
    }
  };

  const handleDeleteTeam = async (team: Team): Promise<void> => {
    if (
      !confirm(
        `Remove team "${team.name}"? Users and tasks will become unassigned.`,
      )
    )
      return;
    try {
      await api.deleteTeam(team.id);
      setTeams((current) => current.filter((t) => t.id !== team.id));
      await loadUsers();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete team");
    }
  };

  const handleResetPassword = async (): Promise<void> => {
    if (!newPassword || newPassword.length < 8) {
      setResetError("Min 8 characters");
      return;
    }
    setResetSaving(true);
    setResetError("");
    try {
      await api.adminResetPassword(resetUserId!, newPassword);
      setResetUserId(null);
      setNewPassword("");
    } catch (e) {
      setResetError(e instanceof Error ? e.message : "Failed");
    } finally {
      setResetSaving(false);
    }
  };

  const pendingCount = users.filter((u) => u.role === "pending").length;

  return (
    <Box>
      <Text size="4" weight="bold" mb="3" style={{ display: "block" }}>
        Admin
      </Text>
      <Tabs.Root defaultValue="users">
        <Tabs.List mb="4">
          <Tabs.Trigger value="users">
            Users{" "}
            {pendingCount > 0 && (
              <Badge color="orange" size="1" ml="1">
                {pendingCount} pending
              </Badge>
            )}
          </Tabs.Trigger>
          <Tabs.Trigger value="teams">Teams</Tabs.Trigger>
          <Tabs.Trigger value="cleanup">Data Cleanup</Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content value="users">
          {error && (
            <Text size="2" color="red" mb="3" style={{ display: "block" }}>
              {error}
            </Text>
          )}
          {loading ? (
            <Text size="2" color="gray">
              Loading users…
            </Text>
          ) : users.length === 0 ? (
            <Text size="2" color="gray">
              No users found.
            </Text>
          ) : (
            <Flex direction="column" gap="2">
              {users.map((user) => (
                <Box
                  key={user.id}
                  p="3"
                  style={{
                    background: "var(--color-panel-solid)",
                    border:
                      user.role === "pending"
                        ? "1px solid var(--orange-a6)"
                        : "1px solid var(--gray-a4)",
                    borderRadius: "var(--radius-3)",
                  }}
                >
                  <Flex justify="between" align="center" gap="3">
                    <Flex
                      direction="column"
                      gap="1"
                      style={{ flex: 1, minWidth: 0 }}
                    >
                      <Flex align="center" gap="2">
                        <Text size="3" weight="medium">
                          {user.username}
                        </Text>
                        <Badge
                          size="1"
                          color={ROLE_COLORS[user.role] ?? "gray"}
                          variant="soft"
                        >
                          {user.role}
                        </Badge>
                      </Flex>
                      <Text
                        size="1"
                        color="gray"
                        style={{ overflow: "hidden", textOverflow: "ellipsis" }}
                      >
                        {user.email}
                      </Text>
                    </Flex>
                    <Flex align="center" gap="2" style={{ flexShrink: 0 }}>
                      {user.role === "pending" && (
                        <Button
                          size="1"
                          color="green"
                          variant="soft"
                          title="Approve as viewer"
                          onClick={() => handleRoleChange(user.id, "viewer")}
                        >
                          <CheckCircle size={13} /> Approve
                        </Button>
                      )}
                      <Select.Root
                        value={user.role}
                        onValueChange={(role) =>
                          handleRoleChange(user.id, role)
                        }
                      >
                        <Select.Trigger size="1" style={{ minWidth: 90 }} />
                        <Select.Content>
                          <Select.Item value="pending">Pending</Select.Item>
                          <Select.Item value="viewer">Viewer</Select.Item>
                          <Select.Item value="editor">Editor</Select.Item>
                          <Select.Item value="admin">Admin</Select.Item>
                        </Select.Content>
                      </Select.Root>
                      <Select.Root
                        value={
                          user.team_id == null ? "none" : String(user.team_id)
                        }
                        onValueChange={(team) =>
                          handleTeamChange(user.id, team)
                        }
                      >
                        <Select.Trigger
                          size="1"
                          placeholder="Team"
                          style={{ minWidth: 120 }}
                        />
                        <Select.Content>
                          <Select.Item value="none">No team</Select.Item>
                          {teams.map((team) => (
                            <Select.Item key={team.id} value={String(team.id)}>
                              {team.name}
                            </Select.Item>
                          ))}
                        </Select.Content>
                      </Select.Root>
                      <IconButton
                        size="1"
                        variant="ghost"
                        color="gray"
                        title="Reset password"
                        aria-label="Reset password"
                        onClick={() => {
                          setResetUserId(user.id);
                          setNewPassword("");
                          setResetError("");
                        }}
                      >
                        <Key size={14} />
                      </IconButton>
                      <IconButton
                        size="1"
                        variant="ghost"
                        color="red"
                        title="Delete user"
                        aria-label="Delete user"
                        onClick={() => handleDelete(user.id, user.username)}
                      >
                        <Trash size={14} />
                      </IconButton>
                    </Flex>
                  </Flex>
                </Box>
              ))}
            </Flex>
          )}
        </Tabs.Content>

        <Tabs.Content value="teams">
          <Flex gap="2" mb="3">
            <TextField.Root
              placeholder="New team name"
              value={newTeamName}
              onChange={(e) => setNewTeamName(e.target.value)}
            />
            <Button onClick={handleCreateTeam}>Create Team</Button>
          </Flex>
          <Flex direction="column" gap="2">
            {teams.map((team) => (
              <Flex
                key={team.id}
                justify="between"
                align="center"
                p="3"
                style={{
                  background: "var(--color-panel-solid)",
                  border: "1px solid var(--gray-a4)",
                  borderRadius: "var(--radius-3)",
                }}
              >
                <Text size="3" weight="medium">
                  {team.name}
                </Text>
                <IconButton
                  size="1"
                  variant="ghost"
                  color="red"
                  title="Delete team"
                  aria-label="Delete team"
                  onClick={() => handleDeleteTeam(team)}
                >
                  <Trash size={14} />
                </IconButton>
              </Flex>
            ))}
            {teams.length === 0 && (
              <Text size="2" color="gray">
                No teams created yet.
              </Text>
            )}
          </Flex>
        </Tabs.Content>

        <Tabs.Content value="cleanup">
          <DataCleanup />
        </Tabs.Content>
      </Tabs.Root>

      {/* Admin reset password dialog */}
      <Dialog.Root
        open={resetUserId !== null}
        onOpenChange={(o) => !o && setResetUserId(null)}
      >
        <Dialog.Content style={{ maxWidth: 360 }}>
          <Dialog.Title>Reset Password</Dialog.Title>
          <Text size="2" color="gray" mb="3" style={{ display: "block" }}>
            Set a new password for this user. Share it with them securely.
          </Text>
          <Box>
            <Text as="label" size="2" weight="medium" htmlFor="rp-new">
              New Password
            </Text>
            <TextField.Root
              id="rp-new"
              mt="1"
              type="password"
              placeholder="Min 8 characters"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
          </Box>
          {resetError && (
            <Text size="2" color="red" mt="2">
              {resetError}
            </Text>
          )}
          <Flex gap="3" mt="4" justify="end">
            <Dialog.Close>
              <Button
                variant="soft"
                color="gray"
                onClick={() => setResetUserId(null)}
              >
                Cancel
              </Button>
            </Dialog.Close>
            <Button onClick={handleResetPassword} loading={resetSaving}>
              Reset Password
            </Button>
          </Flex>
        </Dialog.Content>
      </Dialog.Root>
    </Box>
  );
}
