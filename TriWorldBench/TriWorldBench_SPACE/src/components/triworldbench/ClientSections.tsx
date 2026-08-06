"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { FaMedal } from "react-icons/fa";
import {
  TRIWORLD_COLORS,
  TRIWORLD_RADAR_DIMS,
  TRIWORLD_VIS_PANELS,
  type TriWorldBoardEntry,
} from "./metrics";
import { hasLocalizedText, type LocalizedText } from "@/lib/i18n";
import { LocalizedMarkdown } from "./LocalizedMarkdown";

const CLEAN_CASES = [
  "blocks_ranking_rgb.mp4",
  "click_bell.mp4",
  "grab_roller.mp4",
  "move_can_pot.mp4",
  "move_pillbottle_pad.mp4",
  "pick_dual_bottles.mp4",
  "place_cans_plasticbox.mp4",
  "place_dual_shoes.mp4",
  "place_object_stand.mp4",
  "scan_object.mp4",
  "stack_bowls_three.mp4",
  "turn_switch.mp4",
] as const;

const RANDOM_CASES = [
  "adjust-bottle.mp4",
  "blocks_ranking_size.mp4",
  "dump_bin_bigbin.mp4",
  "grab_roller.mp4",
  "handover_mic.mp4",
  "hanging_mug.mp4",
  "move_can_pot.mp4",
  "pick_diverse_bottles (2).mp4",
  "pick_diverse_bottles.mp4",
  "place_a2b_right.mp4",
  "place_bread_skillet.mp4",
  "place_fan.mp4",
] as const;

const CASE_TITLES_ZH: Record<string, string> = {
  "adjust-bottle.mp4": "调整瓶子",
  "blocks_ranking_rgb.mp4": "RGB 方块排序",
  "blocks_ranking_size.mp4": "按尺寸排序方块",
  "click_bell.mp4": "点击铃铛",
  "dump_bin_bigbin.mp4": "将小箱倒入大箱",
  "grab_roller.mp4": "抓取滚轮",
  "handover_mic.mp4": "递交麦克风",
  "hanging_mug.mp4": "悬挂杯子",
  "move_can_pot.mp4": "移动罐子到锅中",
  "move_pillbottle_pad.mp4": "移动药瓶到垫子",
  "pick_diverse_bottles (2).mp4": "抓取多种瓶子（二）",
  "pick_diverse_bottles.mp4": "抓取多种瓶子",
  "pick_dual_bottles.mp4": "抓取双瓶",
  "place_a2b_right.mp4": "从 A 到 B 放置到右侧",
  "place_bread_skillet.mp4": "将面包放入煎锅",
  "place_cans_plasticbox.mp4": "将罐子放入塑料盒",
  "place_dual_shoes.mp4": "放置双鞋",
  "place_fan.mp4": "放置风扇",
  "place_object_stand.mp4": "将物体放到支架",
  "scan_object.mp4": "扫描物体",
  "stack_bowls_three.mp4": "堆叠三个碗",
  "turn_switch.mp4": "拨动开关",
};

const RADAR_LINE_PATTERNS = [
  "none",
  "12 5",
  "4 4",
  "14 4 3 4",
  "2 4",
  "9 3 2 3",
  "18 6",
  "6 3",
  "16 3 2 3",
  "3 3 9 3",
  "20 4 4 4",
  "7 2",
  "11 2 2 2",
  "5 3 1 3",
  "22 5",
  "8 4 2 4",
  "13 3",
  "3 2",
  "15 5 3 2",
  "6 2 2 2",
  "10 5",
  "4 2 10 2",
  "17 3 4 3",
  "2 3 6 3",
] as const;

function DualText({ en, zh }: { en: React.ReactNode; zh: React.ReactNode }) {
  return (
    <>
      <span className="i18n-en">{en}</span>
      <span className="i18n-zh">{zh}</span>
    </>
  );
}

function fmt(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "TBA";
  }
  return Number(value).toFixed(2);
}

function formatCaseTitle(fileName: string): string {
  return fileName
    .replace(/\.mp4$/i, "")
    .replace(/\s*\(2\)$/, " 2")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function radarPoint(
  cx: number,
  cy: number,
  radius: number,
  axisIndex: number,
  axisCount: number,
  value: number
): [number, number] {
  const angle = -Math.PI / 2 + (axisIndex / axisCount) * Math.PI * 2;
  const scaled = Math.max(0, Math.min(100, value || 0)) / 100;
  return [
    cx + Math.cos(angle) * radius * scaled,
    cy + Math.sin(angle) * radius * scaled,
  ];
}

function radarPercentage(value: number | null | undefined, maxValue: number): number {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 0;
  return (Number(value) / maxValue) * 100;
}

function CaseGrid({
  category,
  cases,
  active,
}: {
  category: "clean" | "random";
  cases: ReadonlyArray<string>;
  active: boolean;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!active) return;

    const panel = panelRef.current;
    const grid = gridRef.current;
    if (!panel || !grid) return;

    const updatePanelHeight = () => {
      const items = Array.from(grid.querySelectorAll<HTMLElement>(".case-item"));
      if (!items.length) return;

      const rowHeights = new Map<number, number>();
      for (const item of items) {
        const rowTop = Math.round(item.offsetTop);
        rowHeights.set(rowTop, Math.max(rowHeights.get(rowTop) || 0, item.offsetHeight));
      }

      const firstTwoRows = [...rowHeights.entries()]
        .sort(([a], [b]) => a - b)
        .slice(0, 2)
        .map(([, height]) => height);
      if (!firstTwoRows.length) return;

      const rowGap = Number.parseFloat(window.getComputedStyle(grid).rowGap || "0") || 0;
      const measuredHeight =
        firstTwoRows.reduce((sum, height) => sum + height, 0) +
        rowGap * Math.max(0, firstTwoRows.length - 1);
      panel.style.setProperty("--case-panel-max-height", `${Math.ceil(measuredHeight)}px`);
    };

    updatePanelHeight();
    window.addEventListener("resize", updatePanelHeight);

    const videos = Array.from(grid.querySelectorAll("video"));
    videos.forEach((video) => {
      video.addEventListener("loadedmetadata", updatePanelHeight);
      video.addEventListener("loadeddata", updatePanelHeight);
    });

    const resizeObserver =
      "ResizeObserver" in window ? new ResizeObserver(updatePanelHeight) : null;
    if (resizeObserver) {
      Array.from(grid.children).forEach((child) => resizeObserver.observe(child));
    }

    return () => {
      window.removeEventListener("resize", updatePanelHeight);
      videos.forEach((video) => {
        video.removeEventListener("loadedmetadata", updatePanelHeight);
        video.removeEventListener("loadeddata", updatePanelHeight);
      });
      resizeObserver?.disconnect();
    };
  }, [active, cases]);

  return (
    <div
      ref={panelRef}
      className={`case-panel${active ? " is-active" : ""}`}
      data-cat={category}
    >
      <div ref={gridRef} className="case-grid">
        {cases.map((fileName) => (
          <figure className="case-item" key={`${category}-${fileName}`}>
            <video
              src={`/video-cases/${category}/${fileName}`}
              muted
              loop
              playsInline
              autoPlay
              preload="metadata"
              controls={false}
              controlsList="nodownload noplaybackrate noremoteplayback"
              disablePictureInPicture
              disableRemotePlayback
              draggable={false}
              onContextMenu={(event) => event.preventDefault()}
              onDragStart={(event) => event.preventDefault()}
            />
            <figcaption>
              <DualText en={formatCaseTitle(fileName)} zh={CASE_TITLES_ZH[fileName] || formatCaseTitle(fileName)} />
            </figcaption>
          </figure>
        ))}
      </div>
    </div>
  );
}

export interface TriWorldMetricText {
  code: string;
  label: LocalizedText;
  shortLabel: LocalizedText;
  title: LocalizedText;
  description?: LocalizedText;
  category?: string;
}

function labelFor(metricTexts: Record<string, TriWorldMetricText>, code: string, fallback: string): LocalizedText {
  return metricTexts[code]?.shortLabel || { en: fallback, zh: fallback };
}

function titleFor(metricTexts: Record<string, TriWorldMetricText>, code: string | null, fallback: string): LocalizedText {
  if (!code) return metricTexts.__overall__?.title || { en: fallback, zh: fallback };
  return metricTexts[code]?.title || { en: fallback, zh: fallback };
}

function panelLabelFor(metricTexts: Record<string, TriWorldMetricText>, code: string | null, fallback: string): LocalizedText {
  if (!code) return metricTexts.__overall__?.label || { en: fallback, zh: fallback };
  return metricTexts[code]?.label || { en: fallback, zh: fallback };
}

function radarLabelLines(value: string, maxLineLength = 16): string[] {
  const normalized = value.trim();
  if (!normalized || normalized.length <= maxLineLength) return [normalized];

  const words = normalized.split(/\s+/).filter(Boolean);
  if (words.length === 1) {
    const characters = Array.from(normalized);
    const splitAt = Math.ceil(characters.length / 2);
    return [characters.slice(0, splitAt).join(""), characters.slice(splitAt).join("")];
  }

  let bestSplit = 1;
  let bestScore = Number.POSITIVE_INFINITY;
  for (let split = 1; split < words.length; split += 1) {
    const firstLength = words.slice(0, split).join(" ").length;
    const secondLength = words.slice(split).join(" ").length;
    const score = Math.max(firstLength, secondLength) * 2 + Math.abs(firstLength - secondLength);
    if (score < bestScore) {
      bestScore = score;
      bestSplit = split;
    }
  }
  return [words.slice(0, bestSplit).join(" "), words.slice(bestSplit).join(" ")];
}

function radarLabelSpans(value: string, className: string, x: string): React.ReactNode[] {
  const lines = radarLabelLines(value);
  return lines.map((line, index) => (
    <tspan
      className={className}
      dy={index === 0 ? `${-0.55 * (lines.length - 1)}em` : "1.1em"}
      key={`${className}-${line}-${index}`}
      x={x}
    >
      {line}
    </tspan>
  ));
}

function OverallRadar({
  rows,
  allRows,
  highlightName,
  metricTexts,
  categoryTexts,
}: {
  rows: TriWorldBoardEntry[];
  allRows: TriWorldBoardEntry[];
  highlightName: string | null;
  metricTexts: Record<string, TriWorldMetricText>;
  categoryTexts: Record<string, LocalizedText>;
}) {
  const cx = 250;
  const cy = 250;
  const radius = 194;
  const ringFractions = [0.2, 0.4, 0.6, 0.8, 1];
  const highlighted = highlightName
    ? rows.find((row) => row.modelName === highlightName)
    : null;

  return (
    <svg viewBox="0 0 500 500" role="img" aria-label="overall capability radar">
      {ringFractions.map((fraction) => {
        const points = TRIWORLD_RADAR_DIMS.map((_, index) =>
          radarPoint(
            cx,
            cy,
            radius * fraction,
            index,
            TRIWORLD_RADAR_DIMS.length,
            100
          )
            .map((coordinate) => coordinate.toFixed(1))
            .join(",")
        ).join(" ");

        return (
          <g key={fraction}>
            <polygon className="twb-radar-ring" points={points} />
          </g>
        );
      })}

      {TRIWORLD_RADAR_DIMS.map((dimension, index) => {
        const [x, y] = radarPoint(cx, cy, radius, index, TRIWORLD_RADAR_DIMS.length, 100);
        const [labelX, labelY] = radarPoint(
          cx,
          cy,
          radius + 32,
          index,
          TRIWORLD_RADAR_DIMS.length,
          100
        );
        const label = categoryTexts[dimension.code] || labelFor(metricTexts, dimension.code, dimension.code);
        const angle = -Math.PI / 2 + (index / TRIWORLD_RADAR_DIMS.length) * Math.PI * 2;
        const horizontalDirection = Math.cos(angle);
        const labelAnchor = horizontalDirection > 0.25 ? "start" : horizontalDirection < -0.25 ? "end" : "middle";
        const tickOffsetX = -Math.sin(angle) * 6;
        const tickOffsetY = Math.cos(angle) * 6;
        const labelXValue = labelX.toFixed(1);
        return (
          <g key={dimension.code}>
            <line
              className="twb-radar-axis"
              x1={cx}
              y1={cy}
              x2={x.toFixed(1)}
              y2={y.toFixed(1)}
            />
            <text
              className={`twb-radar-label is-${labelAnchor}`}
              x={labelXValue}
              y={labelY.toFixed(1)}
            >
              {radarLabelSpans(label.en, "i18n-en", labelXValue)}
              {radarLabelSpans(label.zh, "i18n-zh", labelXValue)}
            </text>
            {ringFractions.map((fraction) => {
              const [tickX, tickY] = radarPoint(
                cx,
                cy,
                radius,
                index,
                TRIWORLD_RADAR_DIMS.length,
                fraction * 100
              );
              return (
                <text
                  className="twb-radar-scale"
                  key={`${dimension.code}-${fraction}`}
                  x={(tickX + tickOffsetX).toFixed(1)}
                  y={(tickY + tickOffsetY).toFixed(1)}
                >
                  {Math.round(dimension.maxValue * fraction)}
                </text>
              );
            })}
          </g>
        );
      })}

      {rows.map((row) => {
        const globalIndex = Math.max(0, allRows.findIndex((item) => item.modelName === row.modelName));
        const color = TRIWORLD_COLORS[globalIndex % TRIWORLD_COLORS.length];
        const dashPattern = RADAR_LINE_PATTERNS[globalIndex % RADAR_LINE_PATTERNS.length];
        const points = TRIWORLD_RADAR_DIMS.map((dimension, dimensionIndex) =>
          radarPoint(
            cx,
            cy,
            radius,
            dimensionIndex,
            TRIWORLD_RADAR_DIMS.length,
            radarPercentage(row.metrics[dimension.code], dimension.maxValue)
          )
            .map((coordinate) => coordinate.toFixed(1))
            .join(",")
        ).join(" ");
        const isHighlighted = highlightName === row.modelName;
        const isDimmed = Boolean(highlightName && !isHighlighted);

        return (
          <g
            className={`twb-radar-series${isHighlighted ? " is-hl" : ""}${isDimmed ? " is-dim" : ""}`}
            key={row.modelName}
            style={{ "--c": color, "--dash": dashPattern } as React.CSSProperties}
          >
            <polygon className="twb-radar-area" points={points} />
            <polyline className="twb-radar-line" points={`${points} ${points.split(" ")[0]}`} />
          </g>
        );
      })}

      {highlighted &&
        TRIWORLD_RADAR_DIMS.map((dimension, index) => {
          const [x, y] = radarPoint(
            cx,
            cy,
            radius,
            index,
            TRIWORLD_RADAR_DIMS.length,
            radarPercentage(highlighted.metrics[dimension.code], dimension.maxValue)
          );
          const color =
            TRIWORLD_COLORS[
              Math.max(0, allRows.findIndex((row) => row.modelName === highlighted.modelName)) %
                TRIWORLD_COLORS.length
            ];
          return (
            <g key={dimension.code}>
              <circle
                className="twb-radar-vtx"
                cx={x.toFixed(1)}
                cy={y.toFixed(1)}
                r="3.4"
                style={{ fill: color }}
              />
              <text
                className="twb-radar-vtx-val"
                x={x.toFixed(1)}
                y={(y - 7).toFixed(1)}
              >
                {fmt(highlighted.metrics[dimension.code])}
              </text>
            </g>
          );
        })}
    </svg>
  );
}

export function TriWorldCases() {
  const [activeCategory, setActiveCategory] = useState<"clean" | "random">("clean");

  return (
    <>
      <div className="case-tabs">
        <button
          type="button"
          className={`case-tab${activeCategory === "clean" ? " is-active" : ""}`}
          data-cat="clean"
          onClick={() => setActiveCategory("clean")}
        >
          <DualText en="Clean" zh="干净背景" />
        </button>
        <button
          type="button"
          className={`case-tab${activeCategory === "random" ? " is-active" : ""}`}
          data-cat="random"
          onClick={() => setActiveCategory("random")}
        >
          <DualText en="Random" zh="随机背景" />
        </button>
      </div>
      <CaseGrid category="clean" cases={CLEAN_CASES} active={activeCategory === "clean"} />
      <CaseGrid category="random" cases={RANDOM_CASES} active={activeCategory === "random"} />
    </>
  );
}

export function TriWorldVisualization({
  rows,
  metricTexts,
  categoryTexts,
  sectionNumber,
  titleText,
  descriptionText,
}: {
  rows: TriWorldBoardEntry[];
  metricTexts: Record<string, TriWorldMetricText>;
  categoryTexts: Record<string, LocalizedText>;
  sectionNumber: string;
  titleText: LocalizedText;
  descriptionText: LocalizedText;
}) {
  const [panelKey, setPanelKey] = useState<(typeof TRIWORLD_VIS_PANELS)[number]["key"]>("overall");
  const [highlightName, setHighlightName] = useState<string | null>(null);
  const [modelQuery, setModelQuery] = useState("");
  const rankingListRef = useRef<HTMLDivElement>(null);

  const visibleRows = useMemo(() => {
    const query = modelQuery.trim().toLocaleLowerCase();
    if (!query) return rows;
    return rows.filter((row) => row.modelName.toLocaleLowerCase().includes(query));
  }, [modelQuery, rows]);

  useEffect(() => {
    if (highlightName && !visibleRows.some((row) => row.modelName === highlightName)) {
      setHighlightName(null);
    }
  }, [highlightName, visibleRows]);

  const visiblePanels = useMemo(
    () => TRIWORLD_VIS_PANELS.filter((panel) =>
      hasLocalizedText(panelLabelFor(metricTexts, panel.code, panel.key))
    ),
    [metricTexts]
  );
  const activePanel =
    visiblePanels.find((panel) => panel.key === panelKey) ??
    visiblePanels[0] ??
    TRIWORLD_VIS_PANELS[0];
  const rankedRows = useMemo(() => {
    const sorted = [...visibleRows];
    if (activePanel.code) {
      sorted.sort(
        (a, b) =>
          (b.metrics[activePanel.code as string] ?? -Infinity) -
          (a.metrics[activePanel.code as string] ?? -Infinity)
      );
      return sorted.map((row, index) => ({
        ...row,
        value: row.metrics[activePanel.code as string] ?? null,
        visualRank: index + 1,
      }));
    }
    sorted.sort((a, b) => (b.score ?? -Infinity) - (a.score ?? -Infinity));
    return sorted.map((row, index) => ({ ...row, value: row.score, visualRank: index + 1 }));
  }, [activePanel.code, visibleRows]);

  useEffect(() => {
    if (!highlightName) return;

    const list = rankingListRef.current;
    const selectedRow = Array.from(list?.querySelectorAll<HTMLButtonElement>(".twb-bar-row") || [])
      .find((row) => row.dataset.model === highlightName);
    if (!list || !selectedRow) return;

    const listRect = list.getBoundingClientRect();
    const rowRect = selectedRow.getBoundingClientRect();
    list.scrollTop = Math.max(
      0,
      list.scrollTop + rowRect.top - listRect.top - (list.clientHeight - rowRect.height) / 2
    );
  }, [activePanel.key, highlightName, rankedRows]);

  const maxValue = Math.max(
    1,
    ...rankedRows.map((row) => (row.value === null ? 0 : Number(row.value)))
  );
  const activePanelTitle = titleFor(metricTexts, activePanel.code, activePanel.key);

  return (
    <section id="visualization" className="section visualization">
      <div className="section-head">
        <span>{sectionNumber}</span>
        <h2><LocalizedMarkdown text={titleText} inline /></h2>
      </div>
      <p>
        <LocalizedMarkdown text={descriptionText} inline />
      </p>

      <div className="twb-vis-top">
        <figure className="twb-vis-radar">
          <OverallRadar
            rows={visibleRows}
            allRows={rows}
            highlightName={highlightName}
            metricTexts={metricTexts}
            categoryTexts={categoryTexts}
          />
        </figure>
        <div className="twb-vis-models">
          <div className="twb-models-head">
            <h4><DualText en={`Models (${rows.length})`} zh={`模型（${rows.length}）`} /></h4>
            <button
              type="button"
              className="twb-present-all"
              onClick={() => {
                setPanelKey("overall");
                setHighlightName(null);
                setModelQuery("");
              }}
            >
              <DualText en="All" zh="全部" />
            </button>
          </div>
          <label className="twb-model-search">
            <span><DualText en="Filter models" zh="筛选模型" /></span>
            <input
              value={modelQuery}
              onChange={(event) => setModelQuery(event.target.value)}
              placeholder="Model name"
              autoComplete="off"
            />
          </label>
          <div className="twb-model-chips">
            {visibleRows.map((row) => {
              const globalIndex = Math.max(0, rows.findIndex((item) => item.modelName === row.modelName));
              const color = TRIWORLD_COLORS[globalIndex % TRIWORLD_COLORS.length];
              const isActive = highlightName === row.modelName;
              return (
                <button
                  type="button"
                  className={`twb-model-chip${isActive ? " is-active" : ""}`}
                  key={row.modelName}
                  data-model={row.modelName}
                  style={{ "--c": color } as React.CSSProperties}
                  onClick={() => {
                    if (isActive) {
                      setHighlightName(null);
                      return;
                    }
                    setHighlightName(row.modelName);
                  }}
                >
                  <i />
                  <span title={row.modelName}>{row.modelName}</span>
                </button>
              );
            })}
          </div>
          {!visibleRows.length ? <p className="twb-no-models"><DualText en="No models match this search." zh="没有匹配的模型。" /></p> : null}
        </div>
      </div>

      <div className="twb-filter-control">
        <span className="twb-filter-label"><DualText en="Metric:" zh="指标：" /></span>
        <div className="twb-metric-selector">
          {visiblePanels.map((panel) => (
            <button
              type="button"
              className={`ms-btn${panelKey === panel.key ? " is-active" : ""}`}
              data-panel={panel.key}
              data-panel-kind={panel.kind}
              key={panel.key}
              onClick={() => setPanelKey(panel.key)}
            >
              <DualText
                en={panelLabelFor(metricTexts, panel.code, panel.key).en}
                zh={panelLabelFor(metricTexts, panel.code, panel.key).zh}
              />
            </button>
          ))}
        </div>
      </div>

      <div className="twb-vis-ranked">
        {hasLocalizedText(activePanelTitle) ? (
          <h4>
            <DualText en={activePanelTitle.en} zh={activePanelTitle.zh} />
          </h4>
        ) : null}
        <div className="twb-bar-list" ref={rankingListRef}>
          {rankedRows.map((row) => {
            const globalIndex = Math.max(0, rows.findIndex((item) => item.modelName === row.modelName));
            const color = TRIWORLD_COLORS[globalIndex % TRIWORLD_COLORS.length];
            const isHighlighted = highlightName === row.modelName;
            const isDimmed = Boolean(highlightName && !isHighlighted);
            const width = row.value === null ? 0 : (Number(row.value) / maxValue) * 100;
            const medalColor = row.visualRank === 1
              ? "#c58b13"
              : row.visualRank === 2
                ? "#6b7280"
                : "#b56736";
            return (
              <button
                type="button"
                className={`twb-bar-row${isHighlighted ? " is-hl" : ""}${isDimmed ? " is-dim" : ""}`}
                key={`${activePanel.key}-${row.modelName}`}
                data-model={row.modelName}
                aria-label={`Locate ${row.modelName} in the leaderboard`}
                title={`Locate ${row.modelName} in the leaderboard`}
                onClick={() => setHighlightName(row.modelName)}
                style={
                  {
                    "--v": `${width.toFixed(1)}%`,
                    "--c": color,
                  } as React.CSSProperties
                }
              >
                {row.visualRank <= 3 ? (
                  <FaMedal
                    className={`twb-ranking-medal rank-${row.visualRank}`}
                    style={{ "--medal-color": medalColor } as React.CSSProperties}
                    aria-label={`Rank ${row.visualRank}`}
                    title={`Rank ${row.visualRank}`}
                  />
                ) : (
                  <em className="twb-ranking-number">{row.visualRank}</em>
                )}
                <b>{row.modelName}</b>
                <i>{fmt(row.value)}</i>
              </button>
            );
          })}
          {!rankedRows.length ? <p className="twb-no-models"><DualText en="No model scores to show." zh="没有可展示的模型分数。" /></p> : null}
        </div>
      </div>

    </section>
  );
}
