import type { TransformConfig, FilterCondition, FieldMapping } from './types';

/**
 * 对原始数据应用 TransformConfig 转换规则
 */
export function applyTransform(
  transform: TransformConfig | undefined,
  data: unknown
): unknown {
  if (!transform || data == null) return data;

  let result = data;

  // 处理数组数据
  if (Array.isArray(result)) {
    result = result.map(item => transformItem(item, transform));
    if (transform.sort) {
      result = sortItems(result as Record<string, unknown>[], transform.sort.field, transform.sort.order);
    }
    if (transform.filter && transform.filter.length > 0) {
      result = filterItems(result as Record<string, unknown>[], transform.filter);
    }
    return result;
  }

  // 处理单个对象
  if (typeof result === 'object') {
    return transformItem(result as Record<string, unknown>, transform);
  }

  return result;
}

function transformItem(
  item: Record<string, unknown>,
  transform: TransformConfig
): Record<string, unknown> {
  let result = { ...item };

  // 1. 选取字段
  if (transform.pick && transform.pick.length > 0) {
    const picked: Record<string, unknown> = {};
    for (const key of transform.pick) {
      if (key in result) {
        picked[key] = result[key];
      }
    }
    result = picked;
  }

  // 2. 字段重命名
  if (transform.rename) {
    const renamed: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(result)) {
      const newKey = transform.rename[key] || key;
      renamed[newKey] = value;
    }
    result = renamed;
  }

  // 3. 字段映射（枚举值转换、日期格式化、截断）
  if (transform.map) {
    for (const [field, mapping] of Object.entries(transform.map)) {
      if (field in result) {
        result[field] = applyFieldMapping(result[field], mapping);
      }
    }
  }

  return result;
}

function applyFieldMapping(value: unknown, mapping: FieldMapping): unknown {
  if (value == null) return value;

  // 枚举值映射
  if (mapping.enum && typeof value === 'string') {
    return mapping.enum[value] ?? value;
  }

  // 日期格式化
  if (mapping.date_format && typeof value === 'string') {
    try {
      const date = new Date(value);
      if (!isNaN(date.getTime())) {
        return formatDate(date, mapping.date_format);
      }
    } catch {
      // 格式化失败返回原值
    }
  }

  // 截断
  if (mapping.truncate && typeof value === 'string' && value.length > mapping.truncate) {
    return value.slice(0, mapping.truncate) + '...';
  }

  return value;
}

function formatDate(date: Date, format: string): string {
  const pad = (n: number) => n.toString().padStart(2, '0');
  const replacements: Record<string, string> = {
    'YYYY': date.getFullYear().toString(),
    'MM': pad(date.getMonth() + 1),
    'DD': pad(date.getDate()),
    'HH': pad(date.getHours()),
    'mm': pad(date.getMinutes()),
    'ss': pad(date.getSeconds()),
  };
  let result = format;
  for (const [token, value] of Object.entries(replacements)) {
    result = result.replace(token, value);
  }
  return result;
}

function sortItems(
  items: Record<string, unknown>[],
  field: string,
  order: 'asc' | 'desc'
): Record<string, unknown>[] {
  return [...items].sort((a, b) => {
    const va = a[field];
    const vb = b[field];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    const cmp = va < vb ? -1 : va > vb ? 1 : 0;
    return order === 'desc' ? -cmp : cmp;
  });
}

function filterItems(
  items: Record<string, unknown>[],
  conditions: FilterCondition[]
): Record<string, unknown>[] {
  return items.filter(item =>
    conditions.every(cond => matchFilter(item, cond))
  );
}

function matchFilter(item: Record<string, unknown>, cond: FilterCondition): boolean {
  const val = item[cond.field];
  switch (cond.operator) {
    case 'eq':
      return val === cond.value;
    case 'neq':
      return val !== cond.value;
    case 'contains':
      return String(val ?? '').includes(String(cond.value));
    case 'gt':
      return val != null && val > cond.value;
    case 'lt':
      return val != null && val < cond.value;
    case 'in':
      return Array.isArray(cond.value) && cond.value.includes(val);
    default:
      return true;
  }
}

/**
 * 从嵌套对象中按路径提取数据
 * 如 data_path = "data.items" → 从 { data: { items: [...] } } 提取 items
 */
export function extractDataByPath(data: unknown, dataPath?: string): unknown {
  if (!dataPath || data == null) return data;

  const segments = dataPath.split('.');
  let result = data;
  for (const seg of segments) {
    if (result == null || typeof result !== 'object') return null;
    result = (result as Record<string, unknown>)[seg];
  }
  // Fallback：如果指定路径返回 null，尝试在 data 中查找第一个数组
  if (result == null && data && typeof data === 'object') {
    for (const val of Object.values(data as Record<string, unknown>)) {
      if (Array.isArray(val)) return val;
    }
  }
  return result;
}

/**
 * 解析模板字符串中的变量
 * 如 "/projects/{project_id}/tasks" + { project_id: "abc" } → "/projects/abc/tasks"
 */
export function resolveTemplate(
  template: string,
  vars: Record<string, string | undefined>
): string {
  return template.replace(/\{(\w+)\}/g, (_, key) => vars[key] ?? `{${key}}`);
}

export function resolveTemplateMap(
  map: Record<string, unknown> | undefined,
  vars: Record<string, string | undefined>
): Record<string, unknown> | undefined {
  if (!map) return undefined;
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(map)) {
    result[key] = typeof value === 'string' ? resolveTemplate(value, vars) : value;
  }
  return result;
}
