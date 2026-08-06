import { Skeleton } from './ui/skeleton'

interface SkeletonCardProps {
  /** 是否显示头像/图标区域 */
  showAvatar?: boolean
  /** 额外的 className */
  className?: string
}

/** 通用卡片骨架屏，用于列表加载态 */
export default function SkeletonCard({ showAvatar = true, className = '' }: SkeletonCardProps) {
  return (
    <div className={`bg-card border border-border rounded-2xl p-5 ${className}`}>
      {showAvatar && (
        <div className="flex items-center gap-3 mb-4">
          <Skeleton className="w-10 h-10 rounded-xl" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-3 w-16" />
          </div>
        </div>
      )}
      <div className="space-y-2">
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-3/4" />
      </div>
      <div className="flex gap-2 mt-4">
        <Skeleton className="h-5 w-16 rounded-full" />
        <Skeleton className="h-5 w-12 rounded-full" />
      </div>
    </div>
  )
}

/** 首页项目卡片骨架屏 */
export function ProjectSkeletonCard() {
  return (
    <div className="bg-card border border-border rounded-2xl overflow-hidden">
      <Skeleton className="h-24 w-full rounded-none" />
      <div className="p-5 space-y-3">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-2/3" />
        <div className="flex gap-2 mt-2">
          <Skeleton className="h-5 w-16 rounded-full" />
          <Skeleton className="h-5 w-20 rounded-full" />
        </div>
      </div>
    </div>
  )
}
