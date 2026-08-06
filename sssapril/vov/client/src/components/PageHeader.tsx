import { ArrowLeftIcon } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

interface PageHeaderProps {
  /** 左上角返回按钮目标路径，不传则不显示 */
  backTo?: string
  /** 品牌小字（如 "Agent 世界"） */
  brand?: string
  /** 品牌图标 */
  brandIcon?: React.ReactNode
  /** 页面大标题 */
  title: string
  /** 标题下方描述 */
  description?: string
  /** 右侧操作区 */
  actions?: React.ReactNode
}

export default function PageHeader({ backTo, brand, brandIcon, title, description, actions }: PageHeaderProps) {
  const navigate = useNavigate()

  return (
    <div className="mb-8 md:mb-10">
      {/* 返回按钮 */}
      {backTo && (
        <button
          onClick={() => navigate(backTo)}
          className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors mb-4"
        >
          <ArrowLeftIcon className="w-4 h-4" />返回
        </button>
      )}

      <div className="flex items-end justify-between">
        <div>
          {/* 品牌行 */}
          {brand && (
            <div className="flex items-center gap-2 mb-1.5">
              {brandIcon && (
                <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
                  {brandIcon}
                </div>
              )}
              <span className="text-sm font-medium text-muted-foreground tracking-wide">{brand}</span>
            </div>
          )}

          {/* 标题 + 描述 */}
          <h1 className="text-2xl md:text-3xl font-bold text-foreground tracking-tight">{title}</h1>
          {description && (
            <p className="text-muted-foreground text-sm mt-1">{description}</p>
          )}
        </div>

        {/* 操作区 */}
        {actions && (
          <div className="flex items-center gap-2">
            {actions}
          </div>
        )}
      </div>
    </div>
  )
}
