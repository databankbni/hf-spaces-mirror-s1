import { useState, useRef } from 'react'
import { UploadIcon, FileUpIcon, AlertTriangleIcon } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from './ui/dialog'
import { Input } from './ui/input'
import type {
  ImportPreviewResult,
  ImportConflict,
  ConflictResolution,
  ImportExecuteResult,
} from '../types'

interface ImportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** 资源类型过滤提示 */
  type: 'skill' | 'agent' | 'project'
  /** 预览回调 */
  onPreview: (file: File) => void
  /** 预览结果 */
  previewResult?: ImportPreviewResult | null
  /** 是否正在预览 */
  previewing?: boolean
  /** 执行导入回调 */
  onExecute: (file: File, resolutions: ConflictResolution[]) => void
  /** 是否正在导入 */
  executing?: boolean
  /** 导入结果 */
  executeResult?: ImportExecuteResult | null
}

type Step = 'upload' | 'preview' | 'done'

const ACTION_LABELS: Record<string, string> = {
  overwrite: '覆盖',
  rename: '重命名',
  skip: '跳过',
}

const TYPE_LABELS: Record<string, string> = {
  skill: '技能',
  agent: 'Agent',
  project: '项目',
  group: '群聊',
  task: '任务',
  resource: '资料',
  tag: '标签',
}

export default function ImportDialog({
  open,
  onOpenChange,
  type,
  onPreview,
  previewResult,
  previewing,
  onExecute,
  executing,
  executeResult,
}: ImportDialogProps) {
  const [step, setStep] = useState<Step>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [resolutions, setResolutions] = useState<Map<number, ConflictResolution>>(new Map())
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f) {
      setFile(f)
      setStep('preview')
      setResolutions(new Map())
      onPreview(f)
    }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    const f = e.dataTransfer.files[0]
    if (f && f.name.endsWith('.zip')) {
      setFile(f)
      setStep('preview')
      setResolutions(new Map())
      onPreview(f)
    }
  }

  const setResolution = (index: number, action: ConflictResolution['action'], newName?: string) => {
    const next = new Map(resolutions)
    next.set(index, { item_index: index, action, new_name: newName })
    setResolutions(next)
  }

  const handleExecute = () => {
    if (!file) return
    // 没有冲突的项默认 create
    const allResolutions: ConflictResolution[] = []
    if (previewResult) {
      // 为每个冲突项设置解决方案，没有冲突的默认 create
      const conflictIndices = new Set(previewResult.conflicts.map((_, i) => {
        // 找到冲突对应的 item index
        const conflict = previewResult.conflicts[i]
        return previewResult.items.findIndex(
          (item) => (item.name || item.title) === conflict.name
        )
      }))

      for (const [idx, res] of resolutions) {
        allResolutions.push(res)
      }
    }
    onExecute(file, allResolutions)
    setStep('done')
  }

  const reset = () => {
    setStep('upload')
    setFile(null)
    setResolutions(new Map())
  }

  const handleClose = (v: boolean) => {
    if (!v) reset()
    onOpenChange(v)
  }

  const conflicts = previewResult?.conflicts || []
  const items = previewResult?.items || []

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent aria-describedby={undefined} className="newspaper-bg border border-foreground/20 rounded-none shadow-none max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 font-newspaper-bold text-foreground text-base tracking-wide">
            <FileUpIcon className="w-5 h-5 opacity-60" />
            导入{type === 'skill' ? '技能' : type === 'agent' ? 'Agent' : '项目'}
          </DialogTitle>
          <div className="my-2 h-px bg-foreground/20" />
          <DialogDescription className="font-newspaper opacity-40 text-sm">
            上传 ZIP 文件导入资源
          </DialogDescription>
        </DialogHeader>

        {step === 'upload' && (
          <div
            className="border-2 border-dashed border-foreground/15 p-12 text-center cursor-pointer hover:border-foreground/30 transition-colors"
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleDrop}
          >
            <UploadIcon className="w-10 h-10 mx-auto mb-3 opacity-30" />
            <p className="text-sm font-newspaper opacity-50">
              点击选择或拖放 ZIP 文件到此处
            </p>
            <input
              ref={fileInputRef}
              type="file"
              accept=".zip"
              className="hidden"
              onChange={handleFileChange}
            />
          </div>
        )}

        {step === 'preview' && (
          <>
            {previewing ? (
              <div className="text-center py-8 font-newspaper opacity-40 text-sm">解析中...</div>
            ) : previewResult ? (
              <div className="space-y-4">
                {/* 概览 */}
                <div className="flex gap-3 flex-wrap font-newspaper text-sm">
                  <span className="opacity-60">共 {items.length} 项</span>
                  {conflicts.length > 0 && (
                    <span className="opacity-60">/ {conflicts.length} 个冲突</span>
                  )}
                </div>

                {/* 资源列表 */}
                <div className="max-h-48 overflow-y-auto border border-foreground/10 p-2">
                  {items.map((item, i) => {
                    const conflict = conflicts.find(
                      (c) => c.name === (item.name || item.title)
                    )
                    return (
                      <div
                        key={i}
                        className="flex items-center gap-2 px-2 py-1 text-sm border-b border-foreground/5 last:border-b-0"
                      >
                        <span className="text-xs font-newspaper opacity-40 shrink-0">
                          [{TYPE_LABELS[item.type] || item.type}]
                        </span>
                        <span className="font-newspaper truncate">{item.name || item.title}</span>
                        {conflict && (
                          <AlertTriangleIcon className="w-4 h-4 opacity-50 shrink-0" />
                        )}
                      </div>
                    )
                  })}
                </div>

                {/* 冲突解决 */}
                {conflicts.length > 0 && (
                  <div className="space-y-2">
                    <h4 className="text-sm font-newspaper-bold">冲突解决</h4>
                    {conflicts.map((conflict, i) => {
                      const current = resolutions.get(i)
                      return (
                        <div
                          key={i}
                          className="flex items-center gap-2 p-2 border border-foreground/10 text-sm"
                        >
                          <span className="font-newspaper-bold truncate flex-1">{conflict.name}</span>
                          <div className="flex gap-1 shrink-0">
                            {(['overwrite', 'rename', 'skip'] as const).map((action) => (
                              <button
                                key={action}
                                className={`px-2 py-1 text-xs font-newspaper transition-opacity ${
                                  current?.action === action
                                    ? 'underline underline-offset-2 opacity-80'
                                    : 'opacity-40 hover:opacity-60'
                                }`}
                                onClick={() => setResolution(i, action, conflict.suggested_new_name)}
                              >
                                {ACTION_LABELS[action]}
                              </button>
                            ))}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            ) : null}
          </>
        )}

        {step === 'done' && executeResult && (
          <div className="space-y-3">
            <div className="text-sm font-newspaper opacity-60">{executeResult.summary}</div>
            {executeResult.created.length > 0 && (
              <div>
                <div className="text-xs font-newspaper opacity-40 mb-1">创建:</div>
                <div className="flex flex-wrap gap-1">
                  {executeResult.created.map((item, i) => (
                    <span key={i} className="text-xs font-newspaper opacity-50">{item}</span>
                  ))}
                </div>
              </div>
            )}
            {executeResult.updated.length > 0 && (
              <div>
                <div className="text-xs font-newspaper opacity-40 mb-1">更新:</div>
                <div className="flex flex-wrap gap-1">
                  {executeResult.updated.map((item, i) => (
                    <span key={i} className="text-xs font-newspaper opacity-50">{item}</span>
                  ))}
                </div>
              </div>
            )}
            {executeResult.errors.length > 0 && (
              <div>
                <div className="text-xs font-newspaper opacity-40 mb-1">错误:</div>
                <div className="flex flex-wrap gap-1">
                  {executeResult.errors.map((item, i) => (
                    <span key={i} className="text-xs font-newspaper opacity-50">{item}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          {step === 'upload' && (
            <button
              onClick={() => handleClose(false)}
              className="px-4 py-2 text-sm font-newspaper opacity-40 hover:opacity-70 transition-opacity"
            >
              取消
            </button>
          )}
          {step === 'preview' && (
            <>
              <button
                onClick={reset}
                className="px-4 py-2 text-sm font-newspaper opacity-40 hover:opacity-70 transition-opacity"
              >
                返回
              </button>
              <button
                onClick={handleExecute}
                disabled={previewing || executing}
                className="px-4 py-2 text-sm font-newspaper-bold text-foreground underline underline-offset-4 hover:opacity-70 transition-opacity disabled:opacity-30 disabled:cursor-not-allowed"
              >
                {executing ? '导入中...' : '确认导入'}
              </button>
            </>
          )}
          {step === 'done' && (
            <button
              onClick={() => handleClose(false)}
              className="px-4 py-2 text-sm font-newspaper-bold text-foreground underline underline-offset-4 hover:opacity-70 transition-opacity"
            >
              完成
            </button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
