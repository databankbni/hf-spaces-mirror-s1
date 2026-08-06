/**
 * TaskComments — threaded comments on a task.
 * Anyone can read; logged-in users can post; authors and admins can delete.
 * @module components/TaskComments
 */
import React, { useState, useEffect } from 'react';
import { Box, Flex, Text, TextArea, Button, IconButton, Separator } from '@radix-ui/themes';
import { Trash } from '@phosphor-icons/react';
import * as api from '../api';
import { useAuth } from '../hooks/useAuth';

interface TaskCommentsProps {
  taskId: number;
}

export function TaskComments({ taskId }: TaskCommentsProps): React.ReactElement {
  const { user } = useAuth();
  const [comments, setComments] = useState<api.Comment[]>([]);
  const [body, setBody] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.fetchComments(taskId).then(setComments).catch(() => setComments([]));
  }, [taskId]);

  const handleSubmit = async (): Promise<void> => {
    if (!body.trim()) return;
    setSaving(true);
    setError('');
    try {
      const comment = await api.createComment(taskId, body.trim());
      setComments(prev => [...prev, comment]);
      setBody('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to post');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (commentId: number): Promise<void> => {
    await api.deleteComment(taskId, commentId);
    setComments(prev => prev.filter(c => c.id !== commentId));
  };

  const formatTime = (iso: string): string => {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) +
      ' at ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <Box mt="4">
      <Separator size="4" mb="3" />
      <Text size="2" weight="medium" mb="2" style={{ display: 'block' }}>
        Comments {comments.length > 0 && `(${comments.length})`}
      </Text>

      {/* Comment list */}
      <Flex direction="column" gap="2" mb="3">
        {comments.length === 0 && (
          <Text size="1" color="gray">No comments yet.</Text>
        )}
        {comments.map(c => (
          <Box
            key={c.id}
            p="2"
            style={{ background: 'var(--gray-a2)', borderRadius: 'var(--radius-2)' }}
          >
            <Flex justify="between" align="start">
              <Box style={{ flex: 1 }}>
                <Flex align="center" gap="2" mb="1">
                  <Text size="1" weight="medium">{c.username}</Text>
                  <Text size="1" color="gray">{formatTime(c.created_at)}</Text>
                </Flex>
                <Text size="2" style={{ whiteSpace: 'pre-wrap' }}>{c.body}</Text>
              </Box>
              {user && (user.id === c.user_id || user.role === 'admin') && (
                <IconButton
                  size="1"
                  variant="ghost"
                  color="red"
                  title="Delete comment"
                  onClick={() => handleDelete(c.id)}
                  style={{ flexShrink: 0, marginLeft: 8 }}
                >
                  <Trash size={11} />
                </IconButton>
              )}
            </Flex>
          </Box>
        ))}
      </Flex>

      {/* Add comment */}
      {user && (user.role === 'editor' || user.role === 'admin') && (
        <Box>
          <TextArea
            placeholder="Add a comment…"
            value={body}
            onChange={e => setBody(e.target.value)}
            rows={2}
            onKeyDown={e => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit();
            }}
          />
          {error && <Text size="1" color="red">{error}</Text>}
          <Flex justify="end" mt="1">
            <Button size="1" onClick={handleSubmit} loading={saving} disabled={!body.trim()}>
              Post
            </Button>
          </Flex>
        </Box>
      )}
    </Box>
  );
}
