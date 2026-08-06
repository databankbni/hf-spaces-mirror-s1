import { useState } from 'react';
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from './ui/alert-dialog';
import { cn } from '@/lib/utils';

interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
  title: string;
  description: string;
  confirmText?: string;
  cancelText?: string;
  destructive?: boolean;
}

export default function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmText = '确认',
  cancelText = '取消',
  destructive = false,
}: ConfirmDialogProps) {
  const [loading, setLoading] = useState(false);

  const handleConfirm = async () => {
    setLoading(true);
    try {
      await onConfirm();
      onClose();
    } catch (error) {
      // Don't close on error — let caller handle it
      console.error('ConfirmDialog action failed:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <AlertDialog open={open} onOpenChange={(v) => { if (!v && !loading) onClose(); }}>
      <AlertDialogContent className="newspaper-bg border border-foreground/20 rounded-none shadow-none">
        <AlertDialogHeader>
          <AlertDialogTitle className="font-newspaper-bold text-foreground text-base tracking-wide">
            {title}
          </AlertDialogTitle>
          <div className="my-2 h-px bg-foreground/20" />
          <AlertDialogDescription className="font-newspaper opacity-60 text-sm">
            {description}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel
            onClick={() => { if (!loading) onClose(); }}
            disabled={loading}
            className="font-newspaper opacity-40 hover:opacity-70 bg-transparent border-foreground/15 rounded-none"
          >
            {cancelText}
          </AlertDialogCancel>
          <button
            onClick={handleConfirm}
            disabled={loading}
            className={cn(
              'px-4 py-2 text-sm font-newspaper-bold transition-opacity rounded-none',
              destructive
                ? 'text-foreground underline underline-offset-4 opacity-60 hover:opacity-80'
                : 'text-foreground underline underline-offset-4 hover:opacity-70',
              loading && 'opacity-30 cursor-not-allowed',
            )}
          >
            {loading ? '处理中...' : confirmText}
          </button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
