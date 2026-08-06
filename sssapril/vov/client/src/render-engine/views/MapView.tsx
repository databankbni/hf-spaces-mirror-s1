import { useState, useRef, useCallback, useMemo, useEffect } from 'react';
import { zoom, zoomIdentity, ZoomBehavior } from 'd3-zoom';
import { select } from 'd3-selection';
import {
  ChevronRightIcon, ZoomInIcon, ZoomOutIcon, Maximize2Icon,
  ExpandIcon, MapIcon, XIcon, InfoIcon, LayersIcon,
} from 'lucide-react';
import type { ViewComponentProps, MapConfig, Territory, MapConnection, GridConfig } from '../types';

// ── 面包屑项（含父级裁剪信息） ──

interface BreadcrumbItem {
  name: string;
  config: MapConfig;
  parentClip?: {
    path: string;
    bbox: { x: number; y: number; width: number; height: number };
  };
}

// ── 工具函数 ──

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

function territoryCenter(cells: [number, number][], grid: GridConfig): { x: number; y: number } {
  const cellSize = grid.cell_size ?? 40;
  const isHex = grid.cell_shape === 'hex';
  const posFn = isHex ? hexCellPos : squareCellPos;

  // 计算每个格子的中心点
  const centers: { x: number; y: number }[] = [];
  for (const [r, c] of cells) {
    const pos = posFn(r, c, cellSize);
    const cx = isHex ? pos.x + (cellSize * Math.sqrt(3)) / 2 : pos.x + cellSize / 2;
    const cy = isHex ? pos.y + cellSize : pos.y + cellSize / 2;
    centers.push({ x: cx, y: cy });
  }

  // 算术平均中心
  const avgX = centers.reduce((s, p) => s + p.x, 0) / centers.length;
  const avgY = centers.reduce((s, p) => s + p.y, 0) / centers.length;

  // 构建领地轮廓顶点用于点在多边形内检测
  const cellSet = new Set(cells.map(([r, c]) => `${r},${c}`));
  const outlineVertices = getOutlineVertices(cells, grid, cellSet);

  // 如果有轮廓顶点，检测质心是否在领地内
  if (outlineVertices.length >= 3) {
    if (pointInPolygon(avgX, avgY, outlineVertices)) {
      return { x: avgX, y: avgY };
    }
    // 质心不在领地内（凹形），找离质心最近的格子中心
    let bestDist = Infinity;
    let best = centers[0];
    for (const c of centers) {
      // 只考虑在领地内部的格子中心（一定在内部）
      const dist = (c.x - avgX) ** 2 + (c.y - avgY) ** 2;
      if (dist < bestDist) {
        bestDist = dist;
        best = c;
      }
    }
    return best;
  }

  return { x: avgX, y: avgY };
}

// ── 轮廓提取核心算法 ──────────────────────────────────────────

/** 有向边：领地在右侧（顺时针顺序） */
interface TerritoryEdge {
  from: string;
  to: string;
  fromCoords: [number, number];
  toCoords: [number, number];
}

/**
 * 从领地格子提取闭合轮廓（核心算法）。
 *
 * 流程：
 *  1) 遍历每个格子，根据 grid.cell_shape（square/hex）生成顶点和邻居方向表，
 *     把"没有同领地的邻居"作为一条有向外部边。
 *  2) 构建 from→edges 索引和已用边集合。
 *  3) 从任意未用边出发，按"最右转"原则追踪下一条边，直到回到起点。
 *     任何长度 ≥ 3 的闭合环都是一个轮廓。
 *
 * @returns 多个轮廓（顺时针），每个轮廓是顶点数组。外轮廓 + 内轮廓（孔）。
 */
function extractTerritoryContours(
  cells: [number, number][],
  grid: GridConfig,
  cellSet: Set<string>,
): [number, number][][] {
  const cellSize = grid.cell_size ?? 40;
  const isHex = grid.cell_shape === 'hex';
  const pk = (x: number, y: number) => `${x.toFixed(4)},${y.toFixed(4)}`;

  // 1) 收集所有外部有向边
  const edges: TerritoryEdge[] = [];

  for (const [row, col] of cells) {
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
        edges.push({ from: pk(v1[0], v1[1]), to: pk(v2[0], v2[1]), fromCoords: v1, toCoords: v2 });
      }
    } else {
      const pos = squareCellPos(row, col, cellSize);
      const x = pos.x, y = pos.y, s = cellSize;
      if (!cellSet.has(`${row - 1},${col}`))
        edges.push({ from: pk(x, y), to: pk(x + s, y), fromCoords: [x, y], toCoords: [x + s, y] });
      if (!cellSet.has(`${row},${col + 1}`))
        edges.push({ from: pk(x + s, y), to: pk(x + s, y + s), fromCoords: [x + s, y], toCoords: [x + s, y + s] });
      if (!cellSet.has(`${row + 1},${col}`))
        edges.push({ from: pk(x + s, y + s), to: pk(x, y + s), fromCoords: [x + s, y + s], toCoords: [x, y + s] });
      if (!cellSet.has(`${row},${col - 1}`))
        edges.push({ from: pk(x, y + s), to: pk(x, y), fromCoords: [x, y + s], toCoords: [x, y] });
    }
  }

  if (edges.length === 0) return [];

  // 2) 构建 from → edges 索引
  const fromIndex = new Map<string, TerritoryEdge[]>();
  for (const e of edges) {
    if (!fromIndex.has(e.from)) fromIndex.set(e.from, []);
    fromIndex.get(e.from)!.push(e);
  }

  // 3) 追踪轮廓：在每个顶点选择最右转的下一条边（顺时针）
  const usedEdges = new Set<number>();
  const contours: [number, number][][] = [];

  for (let startIdx = 0; startIdx < edges.length; startIdx++) {
    if (usedEdges.has(startIdx)) continue;

    const contour: [number, number][] = [];
    let currentEdge = edges[startIdx];
    usedEdges.add(startIdx);
    contour.push(currentEdge.fromCoords);

    while (currentEdge.to !== edges[startIdx].from) {
      const fromKey = currentEdge.to;
      const candidates = fromIndex.get(fromKey) ?? [];

      // 选择最右转的下一条边（相对于当前方向的顺时针最右转）
      const dx = currentEdge.toCoords[0] - currentEdge.fromCoords[0];
      const dy = currentEdge.toCoords[1] - currentEdge.fromCoords[1];
      const currentAngle = Math.atan2(dy, dx);

      let bestCandidate = -1;
      let bestAngle = -Infinity;

      for (let i = 0; i < candidates.length; i++) {
        const c = candidates[i];
        const cIdx = edges.indexOf(c);
        if (usedEdges.has(cIdx) && c.to !== edges[startIdx].from) continue;

        const cdx = c.toCoords[0] - c.fromCoords[0];
        const cdy = c.toCoords[1] - c.fromCoords[1];
        const cAngle = Math.atan2(cdy, cdx);

        // 计算从当前方向到候选方向的顺时针转角
        let turnAngle = currentAngle - cAngle;
        if (turnAngle <= 0) turnAngle += 2 * Math.PI;

        if (turnAngle > bestAngle) {
          bestAngle = turnAngle;
          bestCandidate = i;
        }
      }

      if (bestCandidate === -1) break;

      const nextEdge = candidates[bestCandidate];
      const nextIdx = edges.indexOf(nextEdge);
      usedEdges.add(nextIdx);
      contour.push(nextEdge.fromCoords);
      currentEdge = nextEdge;
    }

    if (contour.length >= 3) {
      contours.push(contour);
    }
  }

  return contours;
}

/** 从领地格子提取轮廓顶点（顺时针排列，多轮廓首尾拼接成一个扁平数组） */
function getOutlineVertices(
  cells: [number, number][],
  grid: GridConfig,
  cellSet: Set<string>,
): [number, number][] {
  const contours = extractTerritoryContours(cells, grid, cellSet);
  // 兼容历史签名：把所有轮廓的顶点扁平地拼成一个数组
  const flat: [number, number][] = [];
  for (const contour of contours) {
    for (const v of contour) flat.push(v);
  }
  return flat;
}

/** 射线法检测点是否在多边形内部 */
function pointInPolygon(px: number, py: number, polygon: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i][0], yi = polygon[i][1];
    const xj = polygon[j][0], yj = polygon[j][1];
    if ((yi > py) !== (yj > py) && px < (xj - xi) * (py - yi) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

function canvasSize(grid: GridConfig): { width: number; height: number } {
  const cellSize = grid.cell_size ?? 40;
  if (grid.cell_shape === 'hex') {
    const w = cellSize * Math.sqrt(3);
    const h = cellSize * 2;
    return {
      width: grid.cols * w + w / 2 + cellSize,
      height: (grid.rows - 1) * h * 0.75 + h + cellSize,
    };
  }
  return {
    width: grid.cols * cellSize,
    height: grid.rows * cellSize,
  };
}

/** 计算领地的像素包围盒 */
function territoryBBox(territory: Territory, grid: GridConfig) {
  const cellSize = grid.cell_size ?? 40;
  const isHex = grid.cell_shape === 'hex';
  const posFn = isHex ? hexCellPos : squareCellPos;
  const cellW = isHex ? cellSize * Math.sqrt(3) : cellSize;
  const cellH = isHex ? cellSize * 2 : cellSize;

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const [r, c] of territory.cells) {
    const pos = posFn(r, c, cellSize);
    minX = Math.min(minX, pos.x);
    minY = Math.min(minY, pos.y);
    maxX = Math.max(maxX, pos.x + cellW);
    maxY = Math.max(maxY, pos.y + cellH);
  }
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
}

/** 生成领地的闭合轮廓路径（追踪外边界，形成连续闭合 path） */
function buildTerritoryPath(territory: Territory, grid: GridConfig): string {
  const cellSet = new Set(territory.cells.map(([r, c]) => `${r},${c}`));
  const contours = extractTerritoryContours(territory.cells, grid, cellSet);

  if (contours.length === 0) return '';

  // 每个轮廓包成一个闭合子路径，再用空格连接形成最终的 SVG path
  const paths: string[] = [];
  for (const contour of contours) {
    if (contour.length < 3) continue;
    const points = contour.map(([x, y]) => `${x},${y}`).join('L');
    paths.push(`M${points}Z`);
  }

  return paths.join(' ');
}

/** 生成领地填充路径 */
function buildTerritoryFillPath(territory: Territory, grid: GridConfig): string {
  const cellSize = grid.cell_size ?? 40;
  const isHex = grid.cell_shape === 'hex';
  if (isHex) {
    return territory.cells.map(([row, col]) => {
      const pos = hexCellPos(row, col, cellSize);
      const cx = pos.x + (cellSize * Math.sqrt(3)) / 2;
      const cy = pos.y + cellSize;
      return `M${hexPoints(cx, cy, cellSize).split(' ').join('L')}Z`;
    }).join(' ');
  }
  return territory.cells.map(([row, col]) => {
    const pos = squareCellPos(row, col, cellSize);
    return `M${pos.x},${pos.y}L${pos.x + cellSize},${pos.y}L${pos.x + cellSize},${pos.y + cellSize}L${pos.x},${pos.y + cellSize}Z`;
  }).join(' ');
}

/** SVG 填充图案 */
function PatternDef({ id, pattern, color }: { id: string; pattern: string; color: string }) {
  switch (pattern) {
    case 'striped':
      return (
        <pattern id={id} patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
          <rect width="6" height="6" fill={color} />
          <line x1="0" y1="0" x2="0" y2="6" stroke="rgba(255,255,255,0.25)" strokeWidth="2" />
        </pattern>
      );
    case 'dotted':
      return (
        <pattern id={id} patternUnits="userSpaceOnUse" width="8" height="8">
          <rect width="8" height="8" fill={color} />
          <circle cx="4" cy="4" r="1.5" fill="rgba(255,255,255,0.35)" />
        </pattern>
      );
    case 'crosshatch':
      return (
        <pattern id={id} patternUnits="userSpaceOnUse" width="6" height="6">
          <rect width="6" height="6" fill={color} />
          <path d="M0,0 l6,6 M6,0 l-6,6" stroke="rgba(255,255,255,0.2)" strokeWidth="0.8" />
        </pattern>
      );
    default:
      return null;
  }
}

// ── 领地详情抽屉 ──

function TerritoryDetailDrawer({
  territory, onClose, onExpandMap,
}: {
  territory: Territory;
  onClose: () => void;
  onExpandMap: (config: MapConfig, name: string, parentTerritory: Territory) => void;
}) {
  const info = territory.info;
  const hasSubMap = !!territory.sub_map;

  return (
    <div className="fixed inset-y-0 right-0 z-50 w-80 bg-card border-l border-border shadow-xl flex flex-col animate-in slide-in-from-right duration-200">
      <div className="flex items-center justify-between p-4 border-b border-border">
        <div className="flex items-center gap-2">
          {info?.icon && <span className="text-lg">{info.icon}</span>}
          <h3 className="font-semibold text-foreground">{info?.title || territory.name}</h3>
        </div>
        <button onClick={onClose} className="p-1 rounded-md hover:bg-accent transition-colors text-muted-foreground hover:text-foreground">
          <XIcon className="w-4 h-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {info?.subtitle && <p className="text-sm text-muted-foreground">{info.subtitle}</p>}
        {info?.description && (
          <div className="rounded-lg bg-muted/50 p-3">
            <p className="text-sm text-foreground leading-relaxed">{info.description}</p>
          </div>
        )}
        {info?.stats && Object.keys(info.stats).length > 0 && (
          <div>
            <div className="text-xs font-medium text-muted-foreground mb-2">统计数据</div>
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(info.stats).map(([key, val]) => (
                <div key={key} className="rounded-lg border border-border bg-background p-2.5">
                  <div className="text-[10px] text-muted-foreground mb-0.5">{key}</div>
                  <div className="text-sm font-semibold text-foreground">{val}</div>
                </div>
              ))}
            </div>
          </div>
        )}
        {info?.badges && info.badges.length > 0 && (
          <div>
            <div className="text-xs font-medium text-muted-foreground mb-2">标签</div>
            <div className="flex flex-wrap gap-1.5">
              {info.badges.map((b, i) => (
                <span key={i} className="text-xs px-2.5 py-1 rounded-full text-white font-medium" style={{ backgroundColor: b.color }}>{b.label}</span>
              ))}
            </div>
          </div>
        )}
        <div>
          <div className="text-xs font-medium text-muted-foreground mb-2">领地信息</div>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">ID</span>
              <span className="font-mono text-xs text-foreground">{territory.id}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">格子数</span>
              <span className="text-foreground">{territory.cells.length}</span>
            </div>
            {territory.style?.fill && (
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">颜色</span>
                <span className="flex items-center gap-1.5">
                  <span className="w-3 h-3 rounded-sm border border-border" style={{ backgroundColor: territory.style.fill }} />
                  <span className="font-mono text-xs">{territory.style.fill}</span>
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
      {hasSubMap && (
        <div className="p-4 border-t border-border">
          <button
            onClick={() => territory.sub_map && onExpandMap(territory.sub_map, territory.name, territory)}
            className="w-full flex items-center justify-center gap-2 rounded-lg bg-primary text-primary-foreground px-4 py-2.5 text-sm font-medium hover:bg-primary/90 transition-colors"
          >
            <LayersIcon className="w-4 h-4" />
            展开子地图
          </button>
        </div>
      )}
    </div>
  );
}

// ── 右键菜单 ──

function ContextMenu({
  x, y, territory, onClose, onExpandMap, onShowDetail,
}: {
  x: number; y: number;
  territory: Territory;
  onClose: () => void;
  onExpandMap: (config: MapConfig, name: string, parentTerritory: Territory) => void;
  onShowDetail: (territory: Territory) => void;
}) {
  const hasSubMap = !!territory.sub_map;
  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} onContextMenu={(e) => { e.preventDefault(); onClose(); }} />
      <div className="fixed z-50 rounded-lg border border-border bg-card shadow-lg py-1 min-w-[160px]" style={{ left: x, top: y }}>
        <button onClick={() => { onShowDetail(territory); onClose(); }} className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-accent transition-colors text-foreground">
          <InfoIcon className="w-3.5 h-3.5" /> 查看详情
        </button>
        {hasSubMap && (
          <button onClick={() => { if (territory.sub_map) onExpandMap(territory.sub_map, territory.name, territory); onClose(); }} className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-accent transition-colors text-foreground">
            <LayersIcon className="w-3.5 h-3.5" /> 展开子地图
          </button>
        )}
      </div>
    </>
  );
}

// ── 面包屑导航 ──

function MapBreadcrumb({ path, onNavigate }: { path: BreadcrumbItem[]; onNavigate: (index: number) => void }) {
  if (path.length <= 1) return null;
  return (
    <div className="flex items-center gap-1 text-xs">
      {path.map((item, i) => (
        <span key={i} className="flex items-center gap-1">
          {i > 0 && <ChevronRightIcon className="w-3 h-3 text-muted-foreground/50" />}
          <button
            onClick={() => onNavigate(i)}
            className={`px-1.5 py-0.5 rounded transition-colors ${
              i === path.length - 1 ? 'text-foreground font-medium bg-accent' : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
            }`}
          >
            {item.name}
          </button>
        </span>
      ))}
    </div>
  );
}

// ── 图例 ──

function MapLegendView({ legend }: { legend: MapConfig['legend'] }) {
  if (!legend?.items?.length) return null;
  const positionClass = {
    'top-right': 'top-3 right-3',
    'bottom-right': 'bottom-3 right-3',
    'top-left': 'top-3 left-3',
    'bottom-left': 'bottom-3 left-3',
  }[legend.position ?? 'bottom-right'];
  return (
    <div className={`absolute ${positionClass} border border-foreground/15 p-2.5 text-xs font-newspaper`}>
      {legend.items.map((item, i) => (
        <div key={i} className="flex items-center gap-2 mb-1 last:mb-0">
          <span className="w-3.5 h-3.5 rounded flex-shrink-0 border border-white/10" style={{ backgroundColor: item.color }} />
          <span className="text-muted-foreground">{item.label}</span>
        </div>
      ))}
    </div>
  );
}

// ── 连接线层 ──

function ConnectionLayer({ connections, territories, grid }: {
  connections: MapConnection[]; territories: Territory[]; grid: GridConfig;
}) {
  const territoryMap = useMemo(() => {
    const map = new Map<string, Territory>();
    for (const t of territories) map.set(t.id, t);
    return map;
  }, [territories]);

  return (
    <g className="map-connections">
      {connections.map((conn, i) => {
        const source = territoryMap.get(conn.source);
        const target = territoryMap.get(conn.target);
        if (!source || !target) return null;
        const sc = territoryCenter(source.cells, grid);
        const tc = territoryCenter(target.cells, grid);
        const midX = (sc.x + tc.x) / 2;
        const midY = (sc.y + tc.y) / 2 - 20;
        return (
          <g key={i}>
            <path d={`M${sc.x},${sc.y} Q${midX},${midY} ${tc.x},${tc.y}`} fill="none"
              stroke={conn.color ?? '#94a3b8'} strokeWidth={1.5} opacity={0.5}
              strokeDasharray={conn.style === 'dashed' ? '6,3' : conn.style === 'dotted' ? '2,2' : undefined} />
            {conn.directed && (
              <polygon points="-4,-2.5 4,0 -4,2.5" fill={conn.color ?? '#94a3b8'}
                transform={`translate(${tc.x},${tc.y}) rotate(${Math.atan2(tc.y - midY, tc.x - midX) * 180 / Math.PI})`} />
            )}
            {conn.label && (
              <text x={midX} y={midY - 6} textAnchor="middle" className="text-[9px] fill-muted-foreground"
                style={{ paintOrder: 'stroke', stroke: 'rgba(255,255,255,0.8)', strokeWidth: 2 }}>{conn.label}</text>
            )}
          </g>
        );
      })}
    </g>
  );
}

// ── 主组件 ──

export default function MapView({ data, options, style }: ViewComponentProps) {
  // 兼容多种结构：options.map（标准）、options 本身、或 data 中包含 MapConfig
  const opts = options as Record<string, unknown> | undefined;
  const mapConfig = options?.map
    ?? (opts?.grid && opts?.territories ? opts as unknown as import('../types').MapConfig : undefined)
    ?? (data && typeof data === 'object' && 'grid' in (data as Record<string, unknown>) && 'territories' in (data as Record<string, unknown>) ? data as import('../types').MapConfig : undefined);
  const [breadcrumb, setBreadcrumb] = useState<BreadcrumbItem[]>([]);
  const [hoveredTerritory, setHoveredTerritory] = useState<string | null>(null);
  const [selectedTerritory, setSelectedTerritory] = useState<Territory | null>(null);
  const [drawerTerritory, setDrawerTerritory] = useState<Territory | null>(null);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; territory: Territory } | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const gRef = useRef<SVGGElement>(null);
  const zoomRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);

  const currentMap = breadcrumb.length > 0 ? breadcrumb[breadcrumb.length - 1].config : mapConfig;
  const hasMap = !!(currentMap?.grid && currentMap?.territories);
  const parentClip = breadcrumb.length > 0 ? breadcrumb[breadcrumb.length - 1].parentClip : null;

  // 初始化 D3 zoom
  useEffect(() => {
    if (!svgRef.current || !gRef.current || !hasMap) return;
    const svg = select(svgRef.current);
    const g = select(gRef.current);
    const zoomBehavior = zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 8])
      .on('zoom', (event) => { g.attr('transform', event.transform.toString()); });
    svg.call(zoomBehavior);
    zoomRef.current = zoomBehavior;
    return () => { svg.on('.zoom', null); };
  }, [currentMap, hasMap]);

  // 层级导航（含父级裁剪信息）
  const navigateTo = useCallback((
    config: MapConfig,
    name: string,
    parentTerritory?: Territory,
  ) => {
    let parentClip: BreadcrumbItem['parentClip'];
    if (parentTerritory && currentMap) {
      const grid = currentMap.grid;
      parentClip = {
        path: buildTerritoryPath(parentTerritory, grid),
        bbox: territoryBBox(parentTerritory, grid),
      };
    }
    setBreadcrumb(prev => [...prev, { name, config, parentClip }]);
    setHoveredTerritory(null);
    setSelectedTerritory(null);
    setDrawerTerritory(null);
    setContextMenu(null);
    if (svgRef.current && zoomRef.current) {
      zoomRef.current.transform(select(svgRef.current), zoomIdentity);
    }
  }, [currentMap]);

  const navigateBack = useCallback((index: number) => {
    setBreadcrumb(prev => prev.slice(0, index + 1));
    setHoveredTerritory(null);
    setSelectedTerritory(null);
    setDrawerTerritory(null);
    setContextMenu(null);
    if (svgRef.current && zoomRef.current) {
      zoomRef.current.transform(select(svgRef.current), zoomIdentity);
    }
  }, []);

  // 领地交互
  const handleTerritoryHover = useCallback((territory: Territory) => {
    if (contextMenu) return;
    setHoveredTerritory(territory.id);
  }, [contextMenu]);

  const handleTerritoryLeave = useCallback(() => { setHoveredTerritory(null); }, []);

  const handleTerritoryClick = useCallback((territory: Territory) => {
    setSelectedTerritory(territory);
    setDrawerTerritory(territory);
    setContextMenu(null);
  }, []);

  const handleTerritoryContextMenu = useCallback((territory: Territory, event: React.MouseEvent) => {
    event.preventDefault();
    setContextMenu({ x: event.clientX, y: event.clientY, territory });
    setSelectedTerritory(territory);
  }, []);

  // 缩放控制
  const handleZoomIn = useCallback(() => {
    if (svgRef.current && zoomRef.current) zoomRef.current.scaleBy(select(svgRef.current), 1.5);
  }, []);
  const handleZoomOut = useCallback(() => {
    if (svgRef.current && zoomRef.current) zoomRef.current.scaleBy(select(svgRef.current), 0.67);
  }, []);
  const handleZoomReset = useCallback(() => {
    if (svgRef.current && zoomRef.current) zoomRef.current.transform(select(svgRef.current), zoomIdentity);
  }, []);

  // 全屏
  const toggleFullscreen = useCallback(() => {
    if (!containerRef.current) return;
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen().then(() => setIsFullscreen(true)).catch(() => {});
    } else {
      document.exitFullscreen().then(() => setIsFullscreen(false)).catch(() => {});
    }
  }, []);

  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', handler);
    return () => document.removeEventListener('fullscreenchange', handler);
  }, []);

  // 空状态
  if (!hasMap) {
    return <div className="py-8 text-center text-sm text-muted-foreground">{options?.empty_text || '未配置地图数据'}</div>;
  }

  const grid = currentMap.grid;
  const territories = currentMap.territories;
  const connections = currentMap.connections ?? [];
  const cellSize = grid.cell_size ?? 40;
  const isHex = grid.cell_shape === 'hex';
  const { width: naturalW, height: naturalH } = canvasSize(grid);

  // 背景
  const bg = currentMap.background;
  const bgColor = bg?.color ?? '#f8fafc';

  // ── 子地图裁剪与缩放计算 ──
  let viewBox: string;
  let contentTransform = '';

  if (parentClip) {
    // 子地图：viewBox 使用父领地的包围盒，内容缩放适配
    const pad = cellSize;
    const vb = parentClip.bbox;
    viewBox = `${vb.x - pad} ${vb.y - pad} ${vb.width + pad * 2} ${vb.height + pad * 2}`;
    // 将子地图自然尺寸缩放到父领地包围盒
    const scaleX = vb.width / naturalW;
    const scaleY = vb.height / naturalH;
    const scale = Math.min(scaleX, scaleY);
    const tx = vb.x + (vb.width - naturalW * scale) / 2;
    const ty = vb.y + (vb.height - naturalH * scale) / 2;
    contentTransform = `translate(${tx},${ty}) scale(${scale})`;
  } else {
    viewBox = `0 0 ${naturalW} ${naturalH}`;
  }

  // 自适应高度（弹窗模式下填满容器）
  const autoHeight = style?.popup ? '100%' : Math.max(400, Math.min(naturalH + 40, 700));

  return (
    <div
      ref={containerRef}
      style={style?.popup ? { height: '100%' } : undefined}
      className={`relative group overflow-hidden ${isFullscreen ? 'fixed inset-0 z-50 bg-background' : ''} ${style?.bordered ? 'rounded-xl border border-border bg-card' : ''}`}
    >
      {/* 顶部工具栏 */}
      <div className={`flex items-center justify-between px-4 py-2.5 border-b border-foreground/15`}>
        <div className="flex-1 min-w-0">
          {breadcrumb.length > 0 ? (
            <MapBreadcrumb
              path={[{ name: '根地图', config: mapConfig! }, ...breadcrumb]}
              onNavigate={(i) => i === 0 ? setBreadcrumb([]) : navigateBack(i - 1)}
            />
          ) : (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <MapIcon className="w-3.5 h-3.5" />
              <span>根地图</span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button onClick={handleZoomOut} className="p-1.5 rounded-md hover:bg-accent transition-colors text-muted-foreground hover:text-foreground" title="缩小">
            <ZoomOutIcon className="w-3.5 h-3.5" />
          </button>
          <button onClick={handleZoomReset} className="p-1.5 rounded-md hover:bg-accent transition-colors text-muted-foreground hover:text-foreground" title="重置视图">
            <Maximize2Icon className="w-3.5 h-3.5" />
          </button>
          <button onClick={handleZoomIn} className="p-1.5 rounded-md hover:bg-accent transition-colors text-muted-foreground hover:text-foreground" title="放大">
            <ZoomInIcon className="w-3.5 h-3.5" />
          </button>
          <div className="w-px h-4 bg-border mx-1" />
          <button onClick={toggleFullscreen} className="p-1.5 rounded-md hover:bg-accent transition-colors text-muted-foreground hover:text-foreground" title={isFullscreen ? '退出全屏' : '全屏'}>
            <ExpandIcon className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* 地图主体 */}
      <div className={`relative ${isFullscreen ? 'flex-1' : ''}`} style={{ height: isFullscreen ? 'calc(100vh - 45px)' : (style?.height ?? autoHeight) }}>
        <svg
          ref={svgRef}
          width="100%"
          height="100%"
          viewBox={viewBox}
          preserveAspectRatio="xMidYMid meet"
          className="cursor-grab active:cursor-grabbing"
          style={{ backgroundColor: bgColor }}
        >
          <defs>
            <filter id="territory-glow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
            {parentClip && (
              <clipPath id="parent-clip">
                <path d={parentClip.path} />
              </clipPath>
            )}
            {territories
              .filter(t => t.style?.pattern && t.style.pattern !== 'solid')
              .map(t => (
                <PatternDef key={t.id} id={`pattern-${t.id}`} pattern={t.style!.pattern!} color={t.style!.fill ?? '#94a3b8'} />
              ))}
          </defs>

          {/* 裁剪组：子地图内容被裁剪到父领地轮廓内 */}
          <g clipPath={parentClip ? 'url(#parent-clip)' : undefined}>
            {/* D3 zoom 组 */}
            <g ref={gRef}>
              {/* 子地图内容缩放组 */}
              <g transform={contentTransform || undefined}>

                {/* ── 领地填充层（仅 hover/select 时显示） ── */}
                <g className="map-territories-fill">
                  {territories.map(t => {
                    const isHovered = hoveredTerritory === t.id;
                    const isSelected = selectedTerritory?.id === t.id;
                    if (!isHovered && !isSelected) return null; // 展示模式：默认不填充

                    const fillPath = buildTerritoryFillPath(t, grid);
                    const fill = t.style?.pattern && t.style.pattern !== 'solid'
                      ? `url(#pattern-${t.id})`
                      : t.style?.fill ?? '#6366f1';
                    const opacity = isHovered ? 0.35 : 0.25;

                    return (
                      <path key={`fill-${t.id}`} d={fillPath} fill={fill} opacity={opacity}
                        style={{ transition: 'opacity 0.2s ease' }} />
                    );
                  })}
                </g>

                {/* ── 领地边框层（主要视觉元素） ── */}
                <g className="map-territories-border">
                  {territories.map(t => {
                    const borderPath = buildTerritoryPath(t, grid);
                    const isHovered = hoveredTerritory === t.id;
                    const isSelected = selectedTerritory?.id === t.id;
                    const isActive = isHovered || isSelected;
                    const baseFill = t.style?.fill ?? '#6366f1';
                    const stroke = isActive ? baseFill : `${baseFill}88`; // 非激活时半透明
                    const strokeWidth = isActive ? 2.5 : 1.5;

                    return (
                      <path key={`border-${t.id}`} d={borderPath} fill="none"
                        stroke={stroke} strokeWidth={strokeWidth} strokeLinejoin="round"
                        style={{ transition: 'stroke 0.2s, stroke-width 0.2s' }} />
                    );
                  })}
                </g>

                {/* ── 选中领地光晕 ── */}
                {selectedTerritory && (
                  <path d={buildTerritoryFillPath(selectedTerritory, grid)} fill="none"
                    stroke={selectedTerritory.style?.fill ?? '#6366f1'} strokeWidth={3}
                    filter="url(#territory-glow)" opacity={0.6} />
                )}

                {/* ── 连接线层 ── */}
                {connections.length > 0 && (
                  <ConnectionLayer connections={connections} territories={territories} grid={grid} />
                )}

                {/* ── 标签层 ── */}
                <g className="map-labels">
                  {territories.map(t => {
                    const center = territoryCenter(t.cells, grid);
                    const cx = center.x;
                    const cy = center.y;
                    const labelY = t.style?.label_position === 'top' ? cy - cellSize * 0.3 : cy;
                    const isHovered = hoveredTerritory === t.id;
                    const isSelected = selectedTerritory?.id === t.id;
                    const isActive = isHovered || isSelected;
                    const baseFill = t.style?.fill ?? '#6366f1';

                    return (
                      <g key={`label-${t.id}`}>
                        {/* 交互热区 */}
                        <path d={buildTerritoryFillPath(t, grid)} fill="transparent" cursor="pointer"
                          onMouseEnter={() => handleTerritoryHover(t)}
                          onMouseLeave={handleTerritoryLeave}
                          onClick={() => handleTerritoryClick(t)}
                          onContextMenu={(e) => handleTerritoryContextMenu(t, e)} />
                        {/* 名称标签 */}
                        <text x={cx} y={labelY} textAnchor="middle" dominantBaseline="middle"
                          className="pointer-events-none select-none"
                          fontSize={isActive ? 12 : 11} fontWeight={600}
                          fill={isActive ? baseFill : '#334155'}
                          style={{
                            paintOrder: 'stroke',
                            stroke: isActive ? 'rgba(255,255,255,0.9)' : 'rgba(255,255,255,0.7)',
                            strokeWidth: 2.5,
                            strokeLinejoin: 'round',
                            transition: 'font-size 0.15s, fill 0.15s',
                          }}>
                          {t.name}
                        </text>
                        {/* 展开指示器 */}
                        {t.sub_map && (
                          <g transform={`translate(${cx + (t.name.length * 3) + 10}, ${labelY - 6})`}>
                            <circle r={6} fill="rgba(255,255,255,0.8)" stroke={baseFill} strokeWidth={1} />
                            <text x={0} y={0} textAnchor="middle" dominantBaseline="middle" fontSize={9} fontWeight={700} fill={baseFill}>+</text>
                          </g>
                        )}
                      </g>
                    );
                  })}
                </g>

              </g>
            </g>
          </g>
        </svg>

        {/* 图例 */}
        {currentMap.legend && <MapLegendView legend={currentMap.legend} />}
      </div>

      {/* 领地详情抽屉 */}
      {drawerTerritory && (
        <>
          <div className="fixed inset-0 z-40 bg-black/20" onClick={() => setDrawerTerritory(null)} />
          <TerritoryDetailDrawer
            territory={drawerTerritory}
            onClose={() => setDrawerTerritory(null)}
            onExpandMap={navigateTo}
          />
        </>
      )}

      {/* 右键菜单 */}
      {contextMenu && (
        <ContextMenu
          x={contextMenu.x} y={contextMenu.y} territory={contextMenu.territory}
          onClose={() => setContextMenu(null)}
          onExpandMap={navigateTo}
          onShowDetail={(t) => { setDrawerTerritory(t); setSelectedTerritory(t); }}
        />
      )}
    </div>
  );
}
