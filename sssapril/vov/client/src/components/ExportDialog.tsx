import { useState, useEffect } from 'react'
import { DownloadIcon, FileDownIcon } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from './ui/dialog'
import { Checkbox } from './ui/checkbox'
import { Input } from './ui/input'
import type { ExportableItem, ExportRequestItem } from '../types'

interface ExportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** 资源类型 */
  type: 'skill' | 'agent' | 'project'
  /** 标题 */
  title: string
  /** 可导出列表（外部加载后传入） */
  items: ExportableItem[]
  /** 是否正在加载 */
  loading?: boolean
  /** 导出回调 */
  onExport: (items: ExportRequestItem[]) => void
  /** 是否正在导出 */
  exporting?: boolean
}

export default function ExportDialog({
  open,
  onOpenChange,
  type,
  title,
  items,
  loading,
  onExport,
  exporting,
}: ExportDialogProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [search, setSearch] = useState('')

  // 打开时默认全选
  useEffect(() => {
    if (open && items.length > 0) {
      setSelected(new Set(items.map((i) => i.id)))
      setSearch('')
    }
  }, [open, items])

  const filtered = items.filter((item) => {
    if (!search) return true
    const q = search.toLowerCase()
    return (
      item.name.toLowerCase().includes(q) ||
      (item.description || '').toLowerCase().includes(q)
    )
  })

  const toggleAll = () => {
    if (selected.size === filtered.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(filtered.map((i) => i.id)))
    }
  }

  const toggleOne = (id: string) => {
    const next = new Set(selected)
    if (next.has(id)) {
      next.delete(id)
    } else {
      next.add(id)
    }
    setSelected(next)
  }

  const handleExport = () => {
    const exportItems: ExportRequestItem[] = items
      .filter((i) => selected.has(i.id))
      .map((i) => ({ type, id: i.id }))
    onExport(exportItems)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-describedby={undefined} className="newspaper-bg border border-foreground/20 rounded-none shadow-none max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 font-newspaper-bold text-foreground text-base tracking-wide">
            <FileDownIcon className="w-5 h-5 opacity-60" />
            {title}
          </DialogTitle>
          <div className="my-2 h-px bg-foreground/20" />
          <DialogDescription className="font-newspaper opacity-40 text-sm">
            选择要导出的{type === 'skill' ? '技能' : type === 'agent' ? 'Agent' : '项目'}，导出为 ZIP 文件
          </DialogDescription>
        </DialogHeader>

        {/* 搜索 */}
        <Input
          placeholder="搜索..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="mb-2 bg-transparent border-foreground/15 font-newspaper rounded-none placeholder:font-newspaper placeholder:opacity-30 focus-visible:ring-0 focus-visible:border-foreground/30"
        />

        {/* 全选 */}
        <div className="flex items-center gap-2 pb-2 border-b border-foreground/10">
          <Checkbox
            checked={filtered.length > 0 && selected.size === filtered.length}
            onCheckedChange={toggleAll}
          />
          <span className="text-sm font-newspaper opacity-40">
            全选（{selected.size}/{items.length}）
          </span>
        </div>

        {/* 列表 */}
        <div className="max-h-64 overflow-y-auto">
          {loading ? (
            <div className="text-center py-8 font-newspaper opacity-40 text-sm">加载中...</div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-8 font-newspaper opacity-40 text-sm">暂无数据</div>
          ) : (
            filtered.map((item) => (
              <label
                key={item.id}
                className="flex items-center gap-3 px-2 py-1.5 hover:bg-foreground/5 cursor-pointer border-b border-foreground/5 last:border-b-0"
              >
                <Checkbox
                  checked={selected.has(item.id)}
                  onCheckedChange={() => toggleOne(item.id)}
                />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-newspaper-bold truncate">{item.name}</div>
                  {item.description && (
                    <div className="text-xs font-newspaper opacity-40 truncate">{item.description}</div>
                  )}
                </div>
              </label>
            ))
          )}
        </div>

        <DialogFooter>
          <button
            onClick={() => onOpenChange(false)}
            className="px-4 py-2 text-sm font-newspaper opacity-40 hover:opacity-70 transition-opacity"
          >
            取消
          </button>
          <button
            onClick={handleExport}
            disabled={selected.size === 0 || exporting}
            className="px-4 py-2 text-sm font-newspaper-bold text-foreground underline underline-offset-4 hover:opacity-70 transition-opacity disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <DownloadIcon className="w-4 h-4 mr-1 inline" />
            导出 ({selected.size})
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
