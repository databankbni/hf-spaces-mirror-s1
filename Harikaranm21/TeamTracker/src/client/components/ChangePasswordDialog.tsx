/**
 * ChangePasswordDialog — lets logged-in users change their own password.
 * @module components/ChangePasswordDialog
 */
import React, { useState, useEffect } from 'react';
import { Dialog, Flex, Box, Text, TextField, Button } from '@radix-ui/themes';
import * as api from '../api';

interface Props {
  open: boolean;
  onClose: () => void;
}

export function ChangePasswordDialog({ open, onClose }: Props): React.ReactElement {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    if (open) { setCurrent(''); setNext(''); setConfirm(''); setError(''); setSuccess(false); }
  }, [open]);

  const handleSave = async (): Promise<void> => {
    if (!current || !next || !confirm) { setError('All fields are required'); return; }
    if (next.length < 8) { setError('New password must be at least 8 characters'); return; }
    if (next !== confirm) { setError('New passwords do not match'); return; }
    setSaving(true);
    setError('');
    try {
      await api.changeMyPassword(current, next);
      setSuccess(true);
      setTimeout(() => onClose(), 1500);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={o => !o && onClose()}>
      <Dialog.Content style={{ maxWidth: 380 }}>
        <Dialog.Title>Change Password</Dialog.Title>
        {success ? (
          <Text size="2" color="green" mt="3" style={{ display: 'block' }}>
            Password changed successfully!
          </Text>
        ) : (
          <Flex direction="column" gap="3" mt="3">
            <Box>
              <Text as="label" size="2" weight="medium" htmlFor="cp-cur">Current Password</Text>
              <TextField.Root id="cp-cur" mt="1" type="password" value={current}
                onChange={e => setCurrent(e.target.value)} />
            </Box>
            <Box>
              <Text as="label" size="2" weight="medium" htmlFor="cp-new">New Password</Text>
              <TextField.Root id="cp-new" mt="1" type="password" placeholder="Min 8 characters"
                value={next} onChange={e => setNext(e.target.value)} />
            </Box>
            <Box>
              <Text as="label" size="2" weight="medium" htmlFor="cp-con">Confirm New Password</Text>
              <TextField.Root id="cp-con" mt="1" type="password" value={confirm}
                onChange={e => setConfirm(e.target.value)} />
            </Box>
            {error && <Text size="2" color="red">{error}</Text>}
          </Flex>
        )}
        {!success && (
          <Flex gap="3" mt="4" justify="end">
            <Dialog.Close><Button variant="soft" color="gray" onClick={onClose}>Cancel</Button></Dialog.Close>
            <Button onClick={handleSave} loading={saving}>Change Password</Button>
          </Flex>
        )}
      </Dialog.Content>
    </Dialog.Root>
  );
}
