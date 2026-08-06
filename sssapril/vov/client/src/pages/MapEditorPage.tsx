import { useState, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  ArrowLeftIcon, PlusIcon, TrashIcon, DownloadIcon,
  EyeIcon, EditIcon, ChevronRightIcon, ChevronDownIcon, MapIcon,
  SaveIcon, LayersIcon,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import RenderEngine from '../render-engine/RenderEngine';
import type { MapConfig, Territory, GridConfig } from '../render-engine/types';

// ── 工具函数 ──

const COLOR_POOL = [
  '#6366f1', '#0891b2', '#dc2626', '#059669', '#d97706',
  '#7c3aed', '#0284c7', '#be185d', '#65a30d', '#ea580c',
  '#4f46e5', '#0d9488', '#e11d48', '#16a34a', '#ca8a04',
];

function createEmptyMap(cols: number, rows: number, shape: 'square' | 'hex'): MapConfig {
  return {
    grid: { cols, rows, cell_shape: shape, cell_size: 36 },
    background: { color: '#f8fafc', grid_lines: true, grid_color: '#e2e8f0' },
    territories: [],
  };
}

function squareCellPos(row: number, col: number, cellSize: number) {
  return { x: col * cellSize, y: row * cellSize };
}

function hexCellPos(row: number, col: number, cellSize: number) {
  const w = cellSize * Math.sqrt(3);
  const h = cellSize * 2;
  const x = col * w + (row % 2 === 1 ? w / 2 : 0);
  const y = row * h * 0.75;
  return { x, y };
}

function hexPoints(cx: number, cy: number, size: number): string {
  const points: string[] = [];
  for (let i = 0; i < 6; i++) {
    const angle = (Math.PI / 180) * (60 * i - 30);
    points.push(`${cx + size * Math.cos(angle)},${cy + size * Math.sin(angle)}`);
  }
  return points.join(' ');
}

// ── SVG 路径解析与缩放 ──

// ── 编辑层级栈 ──

interface EditLayer {
  name: string;
  config: MapConfig;
  parentTerritoryId?: string; // 上层领地 ID
  parentOutline?: string; // 父领地轮廓 SVG path（编辑时叠加显示）
  parentBBox?: { x: number; y: number; width: number; height: number }; // 父领地包围盒
  validCells?: Set<string>; // 子地图中可选的格子集合（父领地格子映射的子格子）
}

// ── 编辑器轮廓计算 ──

/** 计算领地在编辑网格中的轮廓路径 */
function buildEditorOutlinePath(territory: Territory, grid: GridConfig): string {
  const cellSize = grid.cell_size ?? 36;
  const isHex = grid.cell_shape === 'hex';
  const cellSet = new Set(territory.cells.map(([r, c]) => `${r},${c}`));
  const pk = (x: number, y: number) => `${x.toFixed(4)},${y.toFixed(4)}`;

  const nextPoint = new Map<string, string>();

  for (const [row, col] of territory.cells) {
    if (isHex) {
      const pos = hexCellPos(row, col, cellSize);
      const cx = pos.x + (cellSize * Math.sqrt(3)) / 2;
      const cy = pos.y + cellSize;
      const vertices: [number, number][] = [];
      for (let i = 0; i < 6; i++) {
        const angle = (Math.PI / 180) * (60 * i - 30);
        vertices.push([cx + cellSize * Math.cos(angle), cy + cellSize * Math.sin(angle)]);
      }
      const neighborEdges: [number, number, number][] = row % 2 === 0
        ? [[0, 1, 0], [1, 0, 1], [1, -1, 2], [0, -1, 3], [-1, -1, 4], [-1, 0, 5]]
        : [[0, 1, 0], [1, 1, 1], [1, 0, 2], [0, -1, 3], [-1, 0, 4], [-1, 1, 5]];
      for (const [dr, dc, edgeIdx] of neighborEdges) {
        if (cellSet.has(`${row + dr},${col + dc}`)) continue;
        const v1 = vertices[edgeIdx];
        const v2 = vertices[(edgeIdx + 1) % 6];
        nextPoint.set(pk(v1[0], v1[1]), pk(v2[0], v2[1]));
      }
    } else {
      const pos = squareCellPos(row, col, cellSize);
      const x = pos.x, y = pos.y, s = cellSize;
      if (!cellSet.has(`${row - 1},${col}`)) nextPoint.set(pk(x, y), pk(x + s, y));
      if (!cellSet.has(`${row},${col + 1}`)) nextPoint.set(pk(x + s, y), pk(x + s, y + s));
      if (!cellSet.has(`${row + 1},${col}`)) nextPoint.set(pk(x + s, y + s), pk(x, y + s));
      if (!cellSet.has(`${row},${col - 1}`)) nextPoint.set(pk(x, y + s), pk(x, y));
    }
  }

  if (nextPoint.size === 0) return '';

  const visited = new Set<string>();
  const contours: string[] = [];
  for (const [startKey] of nextPoint) {
    if (visited.has(startKey)) continue;
    const points: string[] = [];
    let current = startKey;
    while (!visited.has(current)) {
      visited.add(current);
      points.push(current);
      const next = nextPoint.get(current);
      if (!next) break;
      current = next;
    }
    if (points.length >= 3) contours.push(`M${points.join('L')}Z`);
  }
  return contours.join(' ');
}

/** 计算领地包围盒 */
function calcTerritoryBBox(territory: Territory, grid: GridConfig) {
  const cellSize = grid.cell_size ?? 36;
  const isHex = grid.cell_shape === 'hex';
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const [r, c] of territory.cells) {
    const pos = isHex ? hexCellPos(r, c, cellSize) : squareCellPos(r, c, cellSize);
    const w = isHex ? cellSize * Math.sqrt(3) : cellSize;
    const h = isHex ? cellSize * 2 : cellSize;
    minX = Math.min(minX, pos.x);
    minY = Math.min(minY, pos.y);
    maxX = Math.max(maxX, pos.x + w);
    maxY = Math.max(maxY, pos.y + h);
  }
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
}

// ── 主组件 ──

export default function MapEditorPage() {
  const [searchParams] = useSearchParams();
  const projectId = searchParams.get('projectId');
  const resourceId = searchParams.get('resourceId');

  const [mode, setMode] = useState<'edit' | 'preview'>('edit');
  const [cols, setCols] = useState(10);
  const [rows, setRows] = useState(8);
  const [shape, setShape] = useState<'square' | 'hex'>('square');
  const [rootConfig, setRootConfig] = useState<MapConfig>(createEmptyMap(10, 8, 'square'));
  const [editStack, setEditStack] = useState<EditLayer[]>([]);
  const [selectedTerritoryId, setSelectedTerritoryId] = useState<string | null>(null);
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set(['stats', 'badges', 'submap']));

  // 当前编辑的地图配置
  const currentLayer = editStack.length > 0 ? editStack[editStack.length - 1] : null;
  const currentConfig = currentLayer?.config ?? rootConfig;
  const setCurrentConfig = currentLayer
    ? (config: MapConfig) => setEditStack(prev => {
        const next = [...prev];
        next[next.length - 1] = { ...next[next.length - 1], config };
        return next;
      })
    : setRootConfig;

  const selectedTerritory = currentConfig.territories.find(t => t.id === selectedTerritoryId);

  // ── 领地管理 ──

  const addTerritory = useCallback(() => {
    const id = `t_${Date.now()}`;
    const colorIdx = currentConfig.territories.length % COLOR_POOL.length;
    const color = COLOR_POOL[colorIdx];
    const newTerritory: Territory = {
      id,
      name: `领地 ${currentConfig.territories.length + 1}`,
      cells: [],
      style: { fill: color, stroke: color },
      info: { title: `领地 ${currentConfig.territories.length + 1}` },
    };
    setCurrentConfig({ ...currentConfig, territories: [...currentConfig.territories, newTerritory] });
    setSelectedTerritoryId(id);
  }, [currentConfig, setCurrentConfig]);

  const removeTerritory = useCallback((id: string) => {
    setCurrentConfig({ ...currentConfig, territories: currentConfig.territories.filter(t => t.id !== id) });
    if (selectedTerritoryId === id) setSelectedTerritoryId(null);
  }, [currentConfig, setCurrentConfig, selectedTerritoryId]);

  const updateTerritory = useCallback((id: string, updates: Partial<Territory>) => {
    setCurrentConfig({
      ...currentConfig,
      territories: currentConfig.territories.map(t => t.id === id ? { ...t, ...updates } : t),
    });
  }, [currentConfig, setCurrentConfig]);

  // ── 格子点击 ──

  const toggleCell = useCallback((row: number, col: number) => {
    if (!selectedTerritoryId) return;
    // 子地图模式下，检查格子是否在可选范围内
    if (currentLayer?.validCells && !currentLayer.validCells.has(`${row},${col}`)) return;
    setCurrentConfig({
      ...currentConfig,
      territories: currentConfig.territories.map(t => {
        if (t.id !== selectedTerritoryId) return t;
        const hasCell = t.cells.some(([r, c]) => r === row && c === col);
        let newCells: [number, number][];
        if (hasCell) {
          newCells = t.cells.filter(([r, c]) => !(r === row && c === col));
        } else {
          const occupied = currentConfig.territories.some(
            other => other.id !== t.id && other.cells.some(([r, c]) => r === row && c === col)
          );
          if (occupied) return t;
          newCells = [...t.cells, [row, col]];
        }
        return { ...t, cells: newCells };
      }),
    });
  }, [selectedTerritoryId, currentConfig, setCurrentConfig, currentLayer]);

  // ── 重建地图 ──

  const rebuildMap = useCallback(() => {
    const newConfig = createEmptyMap(cols, rows, shape);
    if (currentLayer) {
      setCurrentConfig(newConfig);
    } else {
      setRootConfig(newConfig);
    }
    setSelectedTerritoryId(null);
  }, [cols, rows, shape, currentLayer, setCurrentConfig]);

  // ── 分层地图 ──

  const enterSubMap = useCallback((territory: Territory) => {
    const zoomFactor = 4;
    const parentGrid = currentConfig.grid;
    const bbox = calcTerritoryBBox(territory, parentGrid);

    const isHex = parentGrid.cell_shape === 'hex';
    const parentCellSize = parentGrid.cell_size ?? 36;
    const parentCellW = isHex ? parentCellSize * Math.sqrt(3) : parentCellSize;

    const subCellSize = 36;

    // 从包围盒推算子地图网格尺寸
    const spanCols = Math.max(2, Math.round(bbox.width / parentCellW));
    const spanRows = Math.max(2, Math.round(bbox.height / (isHex ? parentCellSize * 2 : parentCellSize)));
    const subCols = spanCols * zoomFactor;
    const subRows = spanRows * zoomFactor;

    // 父领地轮廓（用于编辑器参考线显示）
    const parentOutline = buildEditorOutlinePath(territory, parentGrid);
    const parentBBox = bbox;

    // 确定可编辑区域：每个父格子 → 4×4 子格子区块
    const minParentRow = Math.min(...territory.cells.map(([r]) => r));
    const minParentCol = Math.min(...territory.cells.map(([, c]) => c));
    const validCells = new Set<string>();
    for (const [r, c] of territory.cells) {
      const sr0 = (r - minParentRow) * zoomFactor;
      const sc0 = (c - minParentCol) * zoomFactor;
      for (let dr = 0; dr < zoomFactor; dr++) {
        for (let dc = 0; dc < zoomFactor; dc++) {
          validCells.add(`${sr0 + dr},${sc0 + dc}`);
        }
      }
    }

    const subMap = territory.sub_map ?? createEmptyMap(subCols, subRows, 'square');
    if (!territory.sub_map) {
      updateTerritory(territory.id, { sub_map: subMap });
    }
    setEditStack(prev => [...prev, {
      name: territory.name,
      config: subMap,
      parentTerritoryId: territory.id,
      parentOutline,
      parentBBox,
      validCells,
    }]);
    setSelectedTerritoryId(null);
  }, [updateTerritory, currentConfig]);

  const goBackLayer = useCallback((index: number) => {
    // 保存当前层修改到父领地的 sub_map
    if (editStack.length > 0) {
      const current = editStack[editStack.length - 1];
      if (current.parentTerritoryId) {
        // 找到父层配置并更新
        const parentConfig = index > 0 ? editStack[index - 1].config : rootConfig;
        const updatedParent = {
          ...parentConfig,
          territories: parentConfig.territories.map(t =>
            t.id === current.parentTerritoryId ? { ...t, sub_map: current.config } : t
          ),
        };
        if (index > 0) {
          setEditStack(prev => {
            const next = [...prev];
            next[index - 1] = { ...next[index - 1], config: updatedParent };
            return next.slice(0, index);
          });
        } else {
          setRootConfig(updatedParent);
          setEditStack([]);
        }
      } else {
        setEditStack(prev => prev.slice(0, index));
      }
    }
    setSelectedTerritoryId(null);
  }, [editStack, rootConfig]);

  const removeSubMap = useCallback((territoryId: string) => {
    updateTerritory(territoryId, { sub_map: undefined });
  }, [updateTerritory]);

  // ── 同步 editStack 到 rootConfig（预览/导出前调用） ──

  const syncEditStackToRoot = useCallback((): MapConfig => {
    if (editStack.length === 0) return rootConfig;
    // 从底层向上合并：先合并最深层的 sub_map 到其父层，再逐层向上
    const layers = editStack.map(l => ({ ...l, config: { ...l.config } }));

    for (let i = layers.length - 1; i > 0; i--) {
      const layer = layers[i];
      const parentLayer = layers[i - 1];
      if (layer.parentTerritoryId) {
        parentLayer.config = {
          ...parentLayer.config,
          territories: parentLayer.config.territories.map(t =>
            t.id === layer.parentTerritoryId ? { ...t, sub_map: layer.config } : t
          ),
        };
      }
    }

    // 合并第 0 层到 rootConfig
    let config = { ...rootConfig };
    if (layers[0].parentTerritoryId) {
      config = {
        ...config,
        territories: config.territories.map(t =>
          t.id === layers[0].parentTerritoryId ? { ...t, sub_map: layers[0].config } : t
        ),
      };
    }
    return config;
  }, [rootConfig, editStack]);

  // ── 导出 JSON ──

  const exportJson = useCallback(() => {
    const syncedConfig = syncEditStackToRoot();
    const spec = {
      version: 1,
      view_type: 'map' as const,
      title: '自定义地图',
      data: {},
      options: { map: syncedConfig },
    };
    const json = JSON.stringify(spec, null, 2);
    navigator.clipboard.writeText(json).then(() => alert('RenderSpec JSON 已复制到剪贴板！')).catch(() => {
      const blob = new Blob([json], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = 'map-spec.json'; a.click();
      URL.revokeObjectURL(url);
    });
  }, [rootConfig]);

  // ── 保存到项目资料 ──

  const saveToProject = useCallback(async () => {
    if (!projectId) return;
    const content = JSON.stringify(syncEditStackToRoot());
    try {
      if (resourceId) {
        // 更新
        const res = await fetch(`/api/v1/resources/${resourceId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content }),
        });
        if (!res.ok) throw new Error('保存失败');
        alert('地图已更新！');
      } else {
        // 新建
        const res = await fetch('/api/v1/resources', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: '地图',
            content,
            content_type: 'map',
            type: 'map',
            project_id: projectId,
            created_by: 'user',
          }),
        });
        if (!res.ok) throw new Error('保存失败');
        alert('地图已保存到项目资料！');
      }
    } catch (e) {
      alert('保存失败: ' + (e as Error).message);
    }
  }, [projectId, resourceId, rootConfig]);

  // ── 构建编辑网格 ──

  const cellSize = currentConfig.grid.cell_size ?? 36;
  const isHex = currentConfig.grid.cell_shape === 'hex';
  const cellW = isHex ? cellSize * Math.sqrt(3) : cellSize;
  const gridCols = currentConfig.grid.cols;
  const gridRows = currentConfig.grid.rows;
  const svgWidth = isHex ? gridCols * cellW + cellW / 2 + cellSize : gridCols * cellSize;
  const svgHeight = isHex ? (gridRows - 1) * cellSize * 2 * 0.75 + cellSize * 2 + cellSize : gridRows * cellSize;

  const cellTerritoryMap = new Map<string, string>();
  for (const t of currentConfig.territories) {
    for (const [r, c] of t.cells) {
      cellTerritoryMap.set(`${r},${c}`, t.id);
    }
  }

  // ── 统计信息编辑辅助 ──

  const [newStatKey, setNewStatKey] = useState('');
  const [newStatVal, setNewStatVal] = useState('');
  const [newBadgeLabel, setNewBadgeLabel] = useState('');
  const [newBadgeColor, setNewBadgeColor] = useState('#6366f1');

  // ── 拖拽选择 ──
  const [isDragging, setIsDragging] = useState(false);
  const [dragMode, setDragMode] = useState<'add' | 'remove'>('add');
  const [dragVisited, setDragVisited] = useState<Set<string>>(new Set());

  const handleCellPointerDown = useCallback((row: number, col: number) => {
    if (!selectedTerritoryId) return;
    if (currentLayer?.validCells && !currentLayer.validCells.has(`${row},${col}`)) return;
    setIsDragging(true);
    const t = currentConfig.territories.find(t => t.id === selectedTerritoryId);
    const hasCell = t?.cells.some(([r, c]) => r === row && c === col) ?? false;
    setDragMode(hasCell ? 'remove' : 'add');
    setDragVisited(new Set([`${row},${col}`]));
    toggleCell(row, col);
  }, [selectedTerritoryId, currentConfig, currentLayer, toggleCell]);

  const handleCellPointerEnter = useCallback((row: number, col: number) => {
    if (!isDragging || !selectedTerritoryId) return;
    if (currentLayer?.validCells && !currentLayer.validCells.has(`${row},${col}`)) return;
    const key = `${row},${col}`;
    if (dragVisited.has(key)) return;
    setDragVisited(prev => new Set(prev).add(key));
    const t = currentConfig.territories.find(t => t.id === selectedTerritoryId);
    const hasCell = t?.cells.some(([r, c]) => r === row && c === col) ?? false;
    if (dragMode === 'add' && !hasCell) {
      toggleCell(row, col);
    } else if (dragMode === 'remove' && hasCell) {
      toggleCell(row, col);
    }
  }, [isDragging, selectedTerritoryId, currentConfig, currentLayer, dragVisited, dragMode, toggleCell]);

  const handlePointerUp = useCallback(() => {
    setIsDragging(false);
    setDragVisited(new Set());
  }, []);

  const addStat = useCallback(() => {
    if (!selectedTerritoryId || !newStatKey.trim()) return;
    const t = currentConfig.territories.find(t => t.id === selectedTerritoryId);
    if (!t) return;
    const currentStats = t.info?.stats ?? {};
    updateTerritory(selectedTerritoryId, {
      info: { ...t.info, title: t.info?.title ?? t.name, stats: { ...currentStats, [newStatKey.trim()]: newStatVal || '0' } },
    });
    setNewStatKey('');
    setNewStatVal('');
  }, [selectedTerritoryId, currentConfig, updateTerritory, newStatKey, newStatVal]);

  const removeStat = useCallback((key: string) => {
    if (!selectedTerritoryId) return;
    const t = currentConfig.territories.find(t => t.id === selectedTerritoryId);
    if (!t?.info?.stats) return;
    const newStats = { ...t.info.stats };
    delete newStats[key];
    updateTerritory(selectedTerritoryId, { info: { ...t.info, title: t.info?.title ?? t.name, stats: newStats } });
  }, [selectedTerritoryId, currentConfig, updateTerritory]);

  const addBadge = useCallback(() => {
    if (!selectedTerritoryId || !newBadgeLabel.trim()) return;
    const t = currentConfig.territories.find(t => t.id === selectedTerritoryId);
    if (!t) return;
    updateTerritory(selectedTerritoryId, {
      info: { ...t.info, title: t.info?.title ?? t.name, badges: [...(t.info?.badges ?? []), { label: newBadgeLabel.trim(), color: newBadgeColor }] },
    });
    setNewBadgeLabel('');
  }, [selectedTerritoryId, currentConfig, updateTerritory, newBadgeLabel, newBadgeColor]);

  const removeBadge = useCallback((index: number) => {
    if (!selectedTerritoryId) return;
    const t = currentConfig.territories.find(t => t.id === selectedTerritoryId);
    if (!t?.info?.badges) return;
    updateTerritory(selectedTerritoryId, {
      info: { ...t.info, title: t.info?.title ?? t.name, badges: t.info.badges.filter((_, i) => i !== index) },
    });
  }, [selectedTerritoryId, currentConfig, updateTerritory]);

  return (
    <div className="min-h-screen bg-background">
      {/* 顶部导航 */}
      <div className="border-b border-border bg-card">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link to={projectId ? `/project/${projectId}` : '/render-demo'} className="p-1.5 rounded-md hover:bg-accent text-muted-foreground hover:text-foreground">
              <ArrowLeftIcon className="w-4 h-4" />
            </Link>
            <h1 className="text-lg font-semibold text-foreground">地图编辑器</h1>
            {projectId && <span className="text-xs text-muted-foreground bg-accent px-2 py-0.5 rounded">项目: {projectId.slice(0, 8)}...</span>}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setMode(mode === 'edit' ? 'preview' : 'edit')}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium bg-accent text-foreground hover:bg-accent/80 transition-colors"
            >
              {mode === 'edit' ? <EyeIcon className="w-3.5 h-3.5" /> : <EditIcon className="w-3.5 h-3.5" />}
              {mode === 'edit' ? '预览' : '编辑'}
            </button>
            <button onClick={exportJson} className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium bg-accent text-foreground hover:bg-accent/80 transition-colors">
              <DownloadIcon className="w-3.5 h-3.5" /> 导出 JSON
            </button>
            {projectId && (
              <button onClick={saveToProject} className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors">
                <SaveIcon className="w-3.5 h-3.5" /> 保存到项目资料
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 py-4 flex gap-4">
        {/* 左侧面板 */}
        <div className="w-72 flex-shrink-0 space-y-4 overflow-y-auto max-h-[calc(100vh-80px)] pr-1">
          {/* 层级面包屑 */}
          {editStack.length > 0 && (
            <div className="rounded-xl border border-border bg-card p-3">
              <div className="flex items-center gap-1 text-xs flex-wrap">
                <button onClick={() => goBackLayer(0)} className="text-muted-foreground hover:text-foreground transition-colors">根地图</button>
                {editStack.map((layer, i) => (
                  <span key={i} className="flex items-center gap-1">
                    <ChevronRightIcon className="w-3 h-3 text-muted-foreground/50" />
                    <button
                      onClick={() => i < editStack.length - 1 ? goBackLayer(i + 1) : undefined}
                      className={i === editStack.length - 1 ? 'text-foreground font-medium' : 'text-muted-foreground hover:text-foreground transition-colors'}
                    >
                      {layer.name}
                    </button>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* 网格设置 */}
          <div className="rounded-xl border border-border bg-card p-4">
            <h3 className="text-sm font-semibold text-foreground mb-3">网格设置</h3>
            <div className="space-y-2.5">
              <div className="flex items-center justify-between">
                <label className="text-xs text-muted-foreground">列数</label>
                <input type="number" min={3} max={30} value={currentConfig.grid.cols}
                  onChange={e => setCurrentConfig({ ...currentConfig, grid: { ...currentConfig.grid, cols: Math.max(3, Math.min(30, parseInt(e.target.value) || 10)) } })}
                  className="w-16 px-2 py-1 text-sm border border-border rounded-md bg-background text-foreground text-center" />
              </div>
              <div className="flex items-center justify-between">
                <label className="text-xs text-muted-foreground">行数</label>
                <input type="number" min={3} max={20} value={currentConfig.grid.rows}
                  onChange={e => setCurrentConfig({ ...currentConfig, grid: { ...currentConfig.grid, rows: Math.max(3, Math.min(20, parseInt(e.target.value) || 8)) } })}
                  className="w-16 px-2 py-1 text-sm border border-border rounded-md bg-background text-foreground text-center" />
              </div>
              {editStack.length === 0 && (
                <div className="flex items-center justify-between">
                  <label className="text-xs text-muted-foreground">形状</label>
                  <select value={currentConfig.grid.cell_shape} onChange={e => setCurrentConfig({ ...currentConfig, grid: { ...currentConfig.grid, cell_shape: e.target.value as 'square' | 'hex' } })}
                    className="px-2 py-1 text-sm border border-border rounded-md bg-background text-foreground">
                    <option value="square">方格</option>
                    <option value="hex">六边形</option>
                  </select>
                </div>
              )}
              <button onClick={rebuildMap} className="w-full mt-1 px-3 py-1.5 rounded-md text-xs font-medium bg-accent text-foreground hover:bg-accent/80 transition-colors">
                重建当前层地图
              </button>
            </div>
          </div>

          {/* 领地列表 */}
          <div className="rounded-xl border border-border bg-card p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-foreground">领地列表</h3>
              <button onClick={addTerritory} className="flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors">
                <PlusIcon className="w-3 h-3" /> 新增
              </button>
            </div>
            <div className="space-y-1.5 max-h-48 overflow-y-auto">
              {currentConfig.territories.length === 0 && (
                <p className="text-xs text-muted-foreground text-center py-3">点击"新增"创建领地</p>
              )}
              {currentConfig.territories.map(t => (
                <div key={t.id}
                  onClick={() => setSelectedTerritoryId(t.id)}
                  className={`flex items-center gap-2 px-2.5 py-2 rounded-lg cursor-pointer transition-colors ${
                    selectedTerritoryId === t.id ? 'bg-accent ring-1 ring-primary/30' : 'hover:bg-accent/50'
                  }`}
                >
                  <span className="w-4 h-4 rounded flex-shrink-0 border border-white/20" style={{ backgroundColor: t.style?.fill ?? '#94a3b8' }} />
                  <span className="text-sm text-foreground flex-1 truncate">{t.name}</span>
                  <span className="text-[10px] text-muted-foreground">{t.cells.length}格</span>
                  {t.sub_map && <LayersIcon className="w-3 h-3 text-primary" />}
                  <button onClick={(e) => { e.stopPropagation(); removeTerritory(t.id); }}
                    className="p-0.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors">
                    <TrashIcon className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* 选中领地属性编辑 */}
          {selectedTerritory && (
            <div className="rounded-xl border border-border bg-card p-4 space-y-0">
              <h3 className="text-sm font-semibold text-foreground mb-3">领地属性</h3>

              {/* ── basic: 名称 + 颜色 ── */}
              <div className={collapsedSections.has('basic') ? '' : 'border-b border-border pb-3 mb-3'}>
                <button
                  onClick={() => setCollapsedSections(prev => { const next = new Set(prev); next.has('basic') ? next.delete('basic') : next.add('basic'); return next; })}
                  className="flex items-center gap-1.5 w-full text-left mb-1"
                >
                  {collapsedSections.has('basic') ? <ChevronRightIcon className="w-3.5 h-3.5 text-muted-foreground" /> : <ChevronDownIcon className="w-3.5 h-3.5 text-muted-foreground" />}
                  <span className="text-xs font-medium text-foreground">基本信息</span>
                </button>
                {!collapsedSections.has('basic') && (
                  <div className="space-y-2.5 pl-5">
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">名称</label>
                      <input type="text" value={selectedTerritory.name}
                        onChange={e => updateTerritory(selectedTerritory.id, { name: e.target.value, info: { ...selectedTerritory.info, title: e.target.value } })}
                        className="w-full px-2.5 py-1.5 text-sm border border-border rounded-md bg-background text-foreground" />
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">颜色</label>
                      <div className="flex items-center gap-2">
                        <input type="color" value={selectedTerritory.style?.fill ?? '#6366f1'}
                          onChange={e => updateTerritory(selectedTerritory.id, { style: { ...selectedTerritory.style, fill: e.target.value, stroke: e.target.value } })}
                          className="w-8 h-8 rounded border border-border cursor-pointer" />
                        <div className="flex items-center gap-1.5 flex-wrap">
                          {COLOR_POOL.slice(0, 8).map(c => (
                            <button key={c} onClick={() => updateTerritory(selectedTerritory.id, { style: { ...selectedTerritory.style, fill: c, stroke: c } })}
                              className={`w-5 h-5 rounded border-2 ${selectedTerritory.style?.fill === c ? 'border-foreground scale-110' : 'border-transparent'}`}
                              style={{ backgroundColor: c }} />
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* ── meta: 图标 + 副标题 + 描述 ── */}
              <div className={collapsedSections.has('meta') ? '' : 'border-b border-border pb-3 mb-3'}>
                <button
                  onClick={() => setCollapsedSections(prev => { const next = new Set(prev); next.has('meta') ? next.delete('meta') : next.add('meta'); return next; })}
                  className="flex items-center gap-1.5 w-full text-left mb-1"
                >
                  {collapsedSections.has('meta') ? <ChevronRightIcon className="w-3.5 h-3.5 text-muted-foreground" /> : <ChevronDownIcon className="w-3.5 h-3.5 text-muted-foreground" />}
                  <span className="text-xs font-medium text-foreground">元信息</span>
                </button>
                {!collapsedSections.has('meta') && (
                  <div className="space-y-2.5 pl-5">
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">图标 (emoji)</label>
                      <input type="text" value={selectedTerritory.info?.icon ?? ''}
                        onChange={e => updateTerritory(selectedTerritory.id, { info: { ...selectedTerritory.info, title: selectedTerritory.info?.title ?? selectedTerritory.name, icon: e.target.value } })}
                        className="w-full px-2.5 py-1.5 text-sm border border-border rounded-md bg-background text-foreground"
                        placeholder="👑 ⚔️ 🏰 ..." />
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">副标题</label>
                      <input type="text" value={selectedTerritory.info?.subtitle ?? ''}
                        onChange={e => updateTerritory(selectedTerritory.id, { info: { ...selectedTerritory.info, title: selectedTerritory.info?.title ?? selectedTerritory.name, subtitle: e.target.value } })}
                        className="w-full px-2.5 py-1.5 text-sm border border-border rounded-md bg-background text-foreground"
                        placeholder="人口 1200万 | 面积 12格" />
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">描述</label>
                      <textarea value={selectedTerritory.info?.description ?? ''}
                        onChange={e => updateTerritory(selectedTerritory.id, { info: { ...selectedTerritory.info, title: selectedTerritory.info?.title ?? selectedTerritory.name, description: e.target.value } })}
                        className="w-full px-2.5 py-1.5 text-sm border border-border rounded-md bg-background text-foreground resize-none"
                        rows={2} placeholder="领地描述..." />
                    </div>
                  </div>
                )}
              </div>

              {/* ── stats: 统计数据 ── */}
              <div className={collapsedSections.has('stats') ? '' : 'border-b border-border pb-3 mb-3'}>
                <button
                  onClick={() => setCollapsedSections(prev => { const next = new Set(prev); next.has('stats') ? next.delete('stats') : next.add('stats'); return next; })}
                  className="flex items-center gap-1.5 w-full text-left mb-1"
                >
                  {collapsedSections.has('stats') ? <ChevronRightIcon className="w-3.5 h-3.5 text-muted-foreground" /> : <ChevronDownIcon className="w-3.5 h-3.5 text-muted-foreground" />}
                  <span className="text-xs font-medium text-foreground">统计数据</span>
                </button>
                {!collapsedSections.has('stats') && (
                  <div className="space-y-1.5 pl-5">
                    {selectedTerritory.info?.stats && Object.entries(selectedTerritory.info.stats).map(([key, val]) => (
                      <div key={key} className="bg-accent/50 rounded-md px-2 py-1.5">
                        <div className="text-[10px] text-muted-foreground mb-0.5">{key}</div>
                        <div className="flex items-center justify-between">
                          <span className="text-xs text-foreground">{val}</span>
                          <button onClick={() => removeStat(key)} className="text-muted-foreground hover:text-destructive"><TrashIcon className="w-3 h-3" /></button>
                        </div>
                      </div>
                    ))}
                    {(!selectedTerritory.info?.stats || Object.keys(selectedTerritory.info.stats).length === 0) && (
                      <p className="text-[10px] text-muted-foreground text-center py-1">暂无统计数据</p>
                    )}
                    <div className="space-y-1 mt-1">
                      <input type="text" value={newStatKey} onChange={e => setNewStatKey(e.target.value)}
                        className="w-full px-2 py-1 text-xs border border-border rounded bg-background text-foreground" placeholder="键名" />
                      <div className="flex items-center gap-1.5">
                        <input type="text" value={newStatVal} onChange={e => setNewStatVal(e.target.value)}
                          className="flex-1 px-2 py-1 text-xs border border-border rounded bg-background text-foreground" placeholder="值" />
                        <button onClick={addStat} className="p-1 rounded hover:bg-accent"><PlusIcon className="w-3 h-3" /></button>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* ── badges: 标签 ── */}
              <div className={collapsedSections.has('badges') ? '' : 'border-b border-border pb-3 mb-3'}>
                <button
                  onClick={() => setCollapsedSections(prev => { const next = new Set(prev); next.has('badges') ? next.delete('badges') : next.add('badges'); return next; })}
                  className="flex items-center gap-1.5 w-full text-left mb-1"
                >
                  {collapsedSections.has('badges') ? <ChevronRightIcon className="w-3.5 h-3.5 text-muted-foreground" /> : <ChevronDownIcon className="w-3.5 h-3.5 text-muted-foreground" />}
                  <span className="text-xs font-medium text-foreground">标签</span>
                </button>
                {!collapsedSections.has('badges') && (
                  <div className="pl-5">
                    <div className="flex flex-wrap gap-1 mb-1.5">
                      {selectedTerritory.info?.badges?.map((b, i) => (
                        <span key={i} className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full text-white" style={{ backgroundColor: b.color }}>
                          {b.label}
                          <button onClick={() => removeBadge(i)} className="hover:text-white/70"><XIcon className="w-2.5 h-2.5" /></button>
                        </span>
                      ))}
                    </div>
                    <div className="flex items-center gap-1.5">
                      <input type="text" value={newBadgeLabel} onChange={e => setNewBadgeLabel(e.target.value)}
                        className="flex-1 px-2 py-1 text-xs border border-border rounded bg-background text-foreground" placeholder="标签名" />
                      <input type="color" value={newBadgeColor} onChange={e => setNewBadgeColor(e.target.value)}
                        className="w-6 h-6 rounded border border-border cursor-pointer" />
                      <button onClick={addBadge} className="p-1 rounded hover:bg-accent"><PlusIcon className="w-3 h-3" /></button>
                    </div>
                  </div>
                )}
              </div>

              {/* ── submap: 子地图 ── */}
              <div>
                <button
                  onClick={() => setCollapsedSections(prev => { const next = new Set(prev); next.has('submap') ? next.delete('submap') : next.add('submap'); return next; })}
                  className="flex items-center gap-1.5 w-full text-left mb-1"
                >
                  {collapsedSections.has('submap') ? <ChevronRightIcon className="w-3.5 h-3.5 text-muted-foreground" /> : <ChevronDownIcon className="w-3.5 h-3.5 text-muted-foreground" />}
                  <span className="text-xs font-medium text-foreground">子地图</span>
                </button>
                {!collapsedSections.has('submap') && (
                  <div className="pl-5">
                    {selectedTerritory.sub_map ? (
                      <div className="space-y-1.5">
                        <button onClick={() => enterSubMap(selectedTerritory)}
                          className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors">
                          <LayersIcon className="w-3.5 h-3.5" /> 编辑子地图
                        </button>
                        <button onClick={() => removeSubMap(selectedTerritory.id)}
                          className="w-full px-3 py-1.5 rounded-md text-xs text-destructive hover:bg-destructive/10 transition-colors">
                          删除子地图
                        </button>
                      </div>
                    ) : (
                      <button onClick={() => enterSubMap(selectedTerritory)}
                        className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium bg-accent text-foreground hover:bg-accent/80 transition-colors">
                        <PlusIcon className="w-3.5 h-3.5" /> 创建子地图
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* 右侧地图区域 */}
        <div className="flex-1 min-w-0">
          {mode === 'edit' ? (
            <div className="rounded-xl border border-border bg-card overflow-hidden">
              <div className="px-4 py-2.5 border-b border-border/50 flex items-center justify-between">
                <span className="text-xs text-muted-foreground">
                  {selectedTerritoryId
                    ? `正在编辑: ${selectedTerritory?.name ?? ''} — 点击格子分配/取消`
                    : '请先选择或创建一个领地'}
                </span>
                <span className="text-xs text-muted-foreground">{gridCols}×{gridRows} {isHex ? '六边形' : '方格'}</span>
              </div>
              <div className="p-4 overflow-auto" style={{ maxHeight: 'calc(100vh - 180px)' }}>
                <svg width="100%" viewBox={`0 0 ${svgWidth} ${svgHeight}`} style={{ backgroundColor: '#f8fafc' }}
                  onPointerUp={handlePointerUp} onPointerLeave={handlePointerUp}>
                  {/* 父领地轮廓参考线（从 validCells 构建） */}
                  {currentLayer?.validCells && currentLayer.validCells.size > 0 && (() => {
                    const outlineCells: [number, number][] = [];
                    for (const key of currentLayer.validCells) {
                      const [r, c] = key.split(',').map(Number);
                      outlineCells.push([r, c]);
                    }
                    const outlineTerritory: Territory = { id: '', name: '', cells: outlineCells };
                    const outlineGrid: GridConfig = { cols: gridCols, rows: gridRows, cell_shape: currentConfig.grid.cell_shape, cell_size: cellSize };
                    const outlinePath = buildEditorOutlinePath(outlineTerritory, outlineGrid);
                    return (
                      <path d={outlinePath} fill="none" stroke="#6366f1" strokeWidth={2}
                        strokeDasharray="6 4" opacity={0.3} />
                    );
                  })()}
                  {Array.from({ length: gridRows }, (_, row) =>
                    Array.from({ length: gridCols }, (_, col) => {
                      const territoryId = cellTerritoryMap.get(`${row},${col}`);
                      const isSelected = territoryId === selectedTerritoryId;
                      const territory = territoryId ? currentConfig.territories.find(t => t.id === territoryId) : null;
                      const fill = territory?.style?.fill ?? 'transparent';
                      const fillOpacity = isSelected ? 0.5 : territoryId ? 0.3 : 0;
                      const isValid = !currentLayer?.validCells || currentLayer.validCells.has(`${row},${col}`);
                      const disabled = !isValid;

                      if (isHex) {
                        const pos = hexCellPos(row, col, cellSize);
                        const cx = pos.x + cellW / 2;
                        const cy = pos.y + cellSize;
                        return (
                          <polygon key={`${row}-${col}`}
                            points={hexPoints(cx, cy, cellSize)}
                            fill={disabled ? '#f1f5f9' : fill}
                            fillOpacity={disabled ? 1 : fillOpacity}
                            stroke={disabled ? '#e2e8f0' : territoryId ? (isSelected ? fill : `${fill}88`) : '#e2e8f0'}
                            strokeWidth={disabled ? 0.5 : territoryId ? (isSelected ? 2 : 1) : 0.5}
                            cursor={disabled ? 'not-allowed' : 'pointer'}
                            onPointerDown={disabled ? undefined : () => handleCellPointerDown(row, col)}
                            onPointerEnter={disabled ? undefined : () => handleCellPointerEnter(row, col)}
                            style={{ transition: 'fill-opacity 0.15s' }} />
                        );
                      }
                      const pos = squareCellPos(row, col, cellSize);
                      return (
                        <rect key={`${row}-${col}`}
                          x={pos.x} y={pos.y} width={cellSize} height={cellSize}
                          fill={disabled ? '#f1f5f9' : fill}
                          fillOpacity={disabled ? 1 : fillOpacity}
                          stroke={disabled ? '#e2e8f0' : territoryId ? (isSelected ? fill : `${fill}88`) : '#e2e8f0'}
                          strokeWidth={disabled ? 0.5 : territoryId ? (isSelected ? 2 : 1) : 0.5}
                          cursor={disabled ? 'not-allowed' : 'pointer'}
                          onPointerDown={disabled ? undefined : () => handleCellPointerDown(row, col)}
                          onPointerEnter={disabled ? undefined : () => handleCellPointerEnter(row, col)}
                          style={{ transition: 'fill-opacity 0.15s' }} />
                      );
                    })
                  )}
                </svg>
              </div>
            </div>
          ) : (
            <RenderEngine spec={{
              version: 1,
              view_type: 'map',
              title: '预览',
              data: {},
              options: { map: syncEditStackToRoot() },
              style: { bordered: true },
            }} />
          )}
        </div>
      </div>
    </div>
  );
}

function XIcon({ className }: { className?: string }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M18 6 6 18" /><path d="m6 6 12 12" />
    </svg>
  );
}
