/**
 * MembersPanel — manage team members (create, edit, delete).
 * @module components/MembersPanel
 */
import React, { useState } from 'react';
import { Box, Flex, Text, Button, Dialog, TextField, IconButton } from '@radix-ui/themes';
import { Plus, Trash, PencilSimple } from '@phosphor-icons/react';
import type { Member, CreateMemberInput } from '../../shared/types';
import * as api from '../api';
import { useConfirm } from '../hooks/useConfirm';

export interface MembersPanelProps {
  members: Member[];
  isEditor: boolean;
  onMembersChange: () => void;
}

export function MembersPanel({ members, isEditor, onMembersChange }: MembersPanelProps): React.ReactElement {
  const { confirm, ConfirmDialog } = useConfirm();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingMember, setEditingMember] = useState<Member | undefined>();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const openCreate = (): void => {
    setEditingMember(undefined);
    setName('');
    setEmail('');
    setError('');
    setDialogOpen(true);
  };

  const openEdit = (member: Member): void => {
    setEditingMember(member);
    setName(member.name);
    setEmail(member.email);
    setError('');
    setDialogOpen(true);
  };

  const handleSave = async (): Promise<void> => {
    if (!name.trim() || !email.trim()) {
      setError('Name and email are required');
      return;
    }
    setSaving(true);
    try {
      if (editingMember) {
        await api.updateMember(editingMember.id, { name: name.trim(), email: email.trim() });
      } else {
        const input: CreateMemberInput = { name: name.trim(), email: email.trim() };
        await api.createMember(input);
      }
      onMembersChange();
      setDialogOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number): Promise<void> => {
    const ok = await confirm({
      title: 'Remove team member',
      description: 'Their tasks will become unassigned.',
      confirmLabel: 'Remove',
    });
    if (!ok) return;
    await api.deleteMember(id).catch(console.error);
    onMembersChange();
  };

  return (
    <Box>
      {ConfirmDialog}
      <Flex justify="between" align="center" mb="3">
        <Text size="4" weight="bold">Team Members</Text>
        {isEditor && (
          <Button size="2" title="Add team member" onClick={openCreate}>
            <Plus size={15} /> Add Member
          </Button>
        )}
      </Flex>

      <Flex direction="column" gap="2">
        {members.length === 0 && (
          <Text size="2" color="gray">No members yet. Add your team to get started.</Text>
        )}
        {members.map((member) => (
          <Box
            key={member.id}
            p="3"
            style={{
              background: 'var(--color-panel-solid)',
              border: '1px solid var(--gray-a4)',
              borderRadius: 'var(--radius-3)',
            }}
          >
            <Flex justify="between" align="center">
              <Flex align="center" gap="3">
                <Box
                  style={{
                    width: 36, height: 36, borderRadius: '50%',
                    background: member.avatar_color,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    flexShrink: 0,
                  }}
                >
                  <Text style={{ color: 'white', fontWeight: 700, fontSize: 15 }}>
                    {member.name[0].toUpperCase()}
                  </Text>
                </Box>
                <Box>
                  <Text size="3" weight="medium">{member.name}</Text>
                  <Text size="1" color="gray" style={{ display: 'block' }}>{member.email}</Text>
                </Box>
              </Flex>
              {isEditor && (
                <Flex gap="1">
                  <IconButton
                    size="1"
                    variant="ghost"
                    color="gray"
                    title="Edit member"
                    aria-label="Edit member"
                    onClick={() => openEdit(member)}
                  >
                    <PencilSimple size={14} />
                  </IconButton>
                  <IconButton
                    size="1"
                    variant="ghost"
                    color="red"
                    title="Remove member"
                    aria-label="Remove member"
                    onClick={() => handleDelete(member.id)}
                  >
                    <Trash size={14} />
                  </IconButton>
                </Flex>
              )}
            </Flex>
          </Box>
        ))}
      </Flex>

      <Dialog.Root open={dialogOpen} onOpenChange={(o) => !o && setDialogOpen(false)}>
        <Dialog.Content style={{ maxWidth: 400 }}>
          <Dialog.Title>{editingMember ? 'Edit Member' : 'Add Team Member'}</Dialog.Title>
          <Flex direction="column" gap="3" mt="3">
            <Box>
              <Text as="label" size="2" weight="medium" htmlFor="member-name">Name *</Text>
              <TextField.Root
                id="member-name" mt="1" placeholder="Jane Smith"
                value={name} onChange={(e) => setName(e.target.value)}
              />
            </Box>
            <Box>
              <Text as="label" size="2" weight="medium" htmlFor="member-email">Email *</Text>
              <TextField.Root
                id="member-email" mt="1" type="email" placeholder="jane@example.com"
                value={email} onChange={(e) => setEmail(e.target.value)}
              />
            </Box>
            {error && <Text size="2" color="red">{error}</Text>}
          </Flex>
          <Flex gap="3" mt="4" justify="end">
            <Dialog.Close>
              <Button variant="soft" color="gray">Cancel</Button>
            </Dialog.Close>
            <Button onClick={handleSave} loading={saving}>
              {editingMember ? 'Save Changes' : 'Add Member'}
            </Button>
          </Flex>
        </Dialog.Content>
      </Dialog.Root>
    </Box>
  );
}
