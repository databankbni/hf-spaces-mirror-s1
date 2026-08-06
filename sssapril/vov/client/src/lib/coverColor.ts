/**
 * 项目封面渐变色适配 — 把数据库中的高饱和度色（如紫色）映射到报纸色系。
 *
 * 背景：项目表 `cover_color` 字段最初允许的 6 个高饱和度 tailwind 渐变 class
 * （紫幻 / 蓝海 / 橙火 / 绿野 / 玫瑰 / 金辉）现在和报纸风格冲突。
 *
 * 策略：
 * - 如果传入的 coverColor 不含任何"高饱和度"关键字（即已经是低饱和度报纸色）→ 原样返回
 * - 否则视为脏数据 → 用项目 ID 哈希到 5 个报纸色之一，确保视觉统一
 *
 * 这样：
 * - 历史脏数据（紫色等）显示时自动变成报纸色
 * - 新建/编辑项目时如果用户在 CreateProjectModal 选了报纸色 → 原样使用
 * - 集中处理，不在多个 UI 组件里散写 if-else
 */

/** 报纸色系的 5 个封面色 — 与 themes/colors.ts 的 5 个色系对应 */
const PAPER_COVERS = [
  'from-[#1f1b16]/15 to-[#1f1b16]/5',  // 墨黑
  'from-[#7a4f2c]/20 to-[#7a4f2c]/5',  // 棕褐
  'from-[#5a7038]/20 to-[#5a7038]/5',  // 橄榄
  'from-[#7a2932]/20 to-[#7a2932]/5',  // 酒红
  'from-[#3f4d5a]/20 to-[#3f4d5a]/5',  // 青灰
]

/** 视觉上"刺眼"的高饱和度 tailwind 色名 — 出现在 coverColor 中就视为脏数据 */
const VIVID_KEYWORDS = [
  'violet', 'purple', 'fuchsia', 'pink', 'rose',
  'indigo', 'blue-5', 'blue-6', 'sky-', 'cyan-5', 'cyan-6', 'teal-',
  'green-5', 'green-6', 'emerald-', 'lime-',
  'yellow-4', 'yellow-5', 'amber-', 'orange-5', 'orange-6',
  'red-5', 'red-6',
]

/** 默认 fallback — 用最贴近黑白的报纸中性色 */
const DEFAULT_PAPER_COVER = PAPER_COVERS[0]

/** 判断 coverColor 是否为高饱和度脏数据 */
function isVivid(coverColor: string): boolean {
  return VIVID_KEYWORDS.some(k => coverColor.includes(k))
}

/** 项目 ID 哈希到 5 个报纸色之一 — 同 ID 永远同色 */
function hashToPaperIndex(seed: string): number {
  let hash = 0
  for (let i = 0; i < seed.length; i++) {
    hash = ((hash << 5) - hash + seed.charCodeAt(i)) | 0
  }
  return Math.abs(hash) % PAPER_COVERS.length
}

/**
 * 把数据库里的 coverColor 规整成报纸色。
 *
 * @param coverColor 数据库存的 tailwind 渐变 class
 * @param projectId 项目 ID — 用于哈希到稳定的报纸色
 * @returns 报纸风格的渐变 class
 */
export function paperCoverColor(coverColor: string | null | undefined, projectId?: string): string {
  // 空值 → 默认
  if (!coverColor) {
    return projectId ? PAPER_COVERS[hashToPaperIndex(projectId)] : DEFAULT_PAPER_COVER
  }

  // 已经是低饱和度报纸色 → 原样返回
  if (!isVivid(coverColor)) {
    return coverColor
  }

  // 高饱和度脏数据 → 哈希到报纸色
  return projectId ? PAPER_COVERS[hashToPaperIndex(projectId)] : DEFAULT_PAPER_COVER
}

/** 报纸色 palette 列表 — 供 CreateProjectModal 的色板使用 */
export const PAPER_COVER_OPTIONS = [
  { label: '墨黑', value: PAPER_COVERS[0] },
  { label: '棕褐', value: PAPER_COVERS[1] },
  { label: '橄榄', value: PAPER_COVERS[2] },
  { label: '酒红', value: PAPER_COVERS[3] },
  { label: '青灰', value: PAPER_COVERS[4] },
]
