/**
 * useConfirm — replaces browser confirm() with a styled Radix AlertDialog.
 * @module hooks/useConfirm
 */
import React, { useState, useCallback, useRef } from 'react';
import { AlertDialog, Button, Flex } from '@radix-ui/themes';

interface ConfirmOptions {
  title?: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  confirmColor?: 'red' | 'orange' | 'gray';
}

interface ConfirmState extends ConfirmOptions {
  open: boolean;
  resolve: ((value: boolean) => void) | null;
}

export function useConfirm(): {
  confirm: (opts: ConfirmOptions) => Promise<boolean>;
  ConfirmDialog: React.ReactElement;
} {
  const [state, setState] = useState<ConfirmState>({
    open: false,
    description: '',
    resolve: null,
  });
  const resolveRef = useRef<((value: boolean) => void) | null>(null);

  const confirm = useCallback((opts: ConfirmOptions): Promise<boolean> => {
    return new Promise((resolve) => {
      resolveRef.current = resolve;
      setState({ ...opts, open: true, resolve });
    });
  }, []);

  const handleAnswer = (answer: boolean): void => {
    setState((s) => ({ ...s, open: false }));
    resolveRef.current?.(answer);
    resolveRef.current = null;
  };

  const ConfirmDialog = (
    <AlertDialog.Root open={state.open} onOpenChange={(o) => !o && handleAnswer(false)}>
      <AlertDialog.Content style={{ maxWidth: 400 }}>
        <AlertDialog.Title>{state.title ?? 'Are you sure?'}</AlertDialog.Title>
        <AlertDialog.Description>{state.description}</AlertDialog.Description>
        <Flex gap="3" mt="4" justify="end">
          <AlertDialog.Cancel>
            <Button variant="soft" color="gray" onClick={() => handleAnswer(false)}>
              {state.cancelLabel ?? 'Cancel'}
            </Button>
          </AlertDialog.Cancel>
          <AlertDialog.Action>
            <Button color={state.confirmColor ?? 'red'} onClick={() => handleAnswer(true)}>
              {state.confirmLabel ?? 'Confirm'}
            </Button>
          </AlertDialog.Action>
        </Flex>
      </AlertDialog.Content>
    </AlertDialog.Root>
  );

  return { confirm, ConfirmDialog };
}
