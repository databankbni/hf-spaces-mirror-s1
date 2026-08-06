"use client";

import React, { useCallback, useMemo, useRef, useState } from "react";
import { FaMedal } from "react-icons/fa";
import { contentValue, type LocalizedText } from "@/lib/i18n";
import {
  TRIWORLD_COLORS,
  TRIWORLD_TABLE_METRICS,
  type TriWorldBoardEntry,
} from "./metrics";
import { LocalizedMarkdown } from "./LocalizedMarkdown";

type MetricText = {
  code: string;
  label: LocalizedText;
  shortLabel: LocalizedText;
  title: LocalizedText;
  description?: LocalizedText;
};

type Props = {
  rows: TriWorldBoardEntry[];
  metricTexts: Record<string, MetricText>;
  descriptionText: LocalizedText;
};

const RANGE_SIZE = 20;

function DualText({ en, zh }: { en: React.ReactNode; zh: React.ReactNode }) {
  return (
    <>
      <span className="i18n-en">{en}</span>
      <span className="i18n-zh">{zh}</span>
    </>
  );
}

function displayScore(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "TBA";
  return Number(value).toFixed(2);
}

function textFor(
  metricTexts: Record<string, MetricText>,
  code: string,
  fallback: string
): LocalizedText {
  return metricTexts[code]?.label || metricTexts[code]?.shortLabel || { en: fallback, zh: fallback };
}

function headerLines(value: string): string[] {
  const words = value.trim().split(/\s+/).filter(Boolean);
  if (words.length <= 2) return [value.trim()];
  const lines: string[] = [];
  for (let index = 0; index < words.length; index += 2) {
    lines.push(words.slice(index, index + 2).join(" "));
  }
  return lines;
}

function MetricHeaderText({ text }: { text: LocalizedText }) {
  const en = contentValue(text.en);
  const zh = contentValue(text.zh);
  return (
    <>
      {en ? (
        <span className="i18n-en twb-metric-header-text">
          {headerLines(en).map((line, index) => (
            <span className="twb-metric-header-line" key={`${line}-${index}`}>{line}</span>
          ))}
        </span>
      ) : null}
      {zh ? (
        <span className="i18n-zh twb-metric-header-text">
          {headerLines(zh).map((line, index) => (
            <span className="twb-metric-header-line" key={`${line}-${index}`}>{line}</span>
          ))}
        </span>
      ) : null}
    </>
  );
}

function valueFor(row: TriWorldBoardEntry, code: string): number | null {
  return code === "TWBScore" ? row.score : row.metrics[code] ?? null;
}

function isScore(value: number | null): value is number {
  return value !== null && Number.isFinite(value);
}

export function TriWorldLeaderboard({ rows, metricTexts, descriptionText }: Props) {
  const [query, setQuery] = useState("");
  const [highlightedName, setHighlightedName] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const rangeMenuRef = useRef<HTMLDetailsElement>(null);
  const rowRefs = useRef(new Map<string, HTMLTableRowElement>());

  const ranges = useMemo(() => {
    const total = Math.ceil(rows.length / RANGE_SIZE);
    return Array.from({ length: total }, (_, index) => {
      const start = index * RANGE_SIZE;
      const end = Math.min(start + RANGE_SIZE, rows.length);
      return { index, start, end, label: start === 0 ? `Top ${end}` : `Ranks ${start + 1}-${end}` };
    });
  }, [rows.length]);

  const metricRanks = useMemo(() => {
    const ranksByMetric = new Map<string, Map<TriWorldBoardEntry, number>>();

    for (const metric of TRIWORLD_TABLE_METRICS) {
      const rankedRows = rows
        .map((row) => ({ row, value: valueFor(row, metric.code) }))
        .filter((entry): entry is { row: TriWorldBoardEntry; value: number } => isScore(entry.value))
        .sort((left, right) => right.value - left.value);
      const ranks = new Map<TriWorldBoardEntry, number>();
      let previousValue: number | null = null;
      let previousRank = 0;

      rankedRows.forEach((entry, index) => {
        const rank = previousValue !== null && entry.value === previousValue ? previousRank : index + 1;
        ranks.set(entry.row, rank);
        previousValue = entry.value;
        previousRank = rank;
      });
      ranksByMetric.set(metric.code, ranks);
    }

    return ranksByMetric;
  }, [rows]);

  const locate = useCallback((name = query) => {
    const normalized = name.trim().toLocaleLowerCase();
    if (!normalized) {
      setHighlightedName(null);
      setMessage("");
      return;
    }
    const matched =
      rows.find((row) => row.modelName.toLocaleLowerCase() === normalized) ||
      rows.find((row) => row.modelName.toLocaleLowerCase().includes(normalized));
    if (!matched) {
      setHighlightedName(null);
      setMessage(`No published model matches "${name.trim()}".`);
      return;
    }
    setHighlightedName(matched.modelName);
    setMessage(`Located ${matched.modelName} at rank ${matched.rank}.`);
    window.requestAnimationFrame(() => {
      rowRefs.current.get(matched.modelName)?.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
    });
  }, [query, rows]);

  const jumpToRange = (start: number) => {
    const row = rows[start];
    if (!row) return;
    setHighlightedName(null);
    setMessage("");
    rangeMenuRef.current?.removeAttribute("open");
    window.requestAnimationFrame(() => {
      rowRefs.current.get(row.modelName)?.scrollIntoView({ behavior: "smooth", block: "start", inline: "nearest" });
    });
  };

  return (
    <article className="twb-rich-card twb-overall twb-leaderboard-card">
      <p className="twb-board-note">
        <LocalizedMarkdown text={descriptionText} inline />
      </p>

      <div className="twb-leaderboard-controls">
        <details className="twb-rank-range-menu" ref={rangeMenuRef}>
          <summary>
            <DualText en={ranges[0]?.label || "Published ranks"} zh={ranges[0] ? `前 ${ranges[0].end} 名` : "已发布排名"} />
          </summary>
          <div className="twb-rank-range-options">
            {ranges.map((range) => (
              <button type="button" key={range.index} onClick={() => jumpToRange(range.start)}>
                <DualText
                  en={range.label}
                  zh={range.start === 0 ? `前 ${range.end} 名` : `第 ${range.start + 1}-${range.end} 名`}
                />
              </button>
            ))}
          </div>
        </details>
        <form
          className="twb-model-locator"
          onSubmit={(event) => {
            event.preventDefault();
            locate();
          }}
        >
          <label htmlFor="leaderboard-model-locator"><DualText en="Locate model" zh="定位模型" /></label>
          <input
            id="leaderboard-model-locator"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Model name"
            autoComplete="off"
          />
          <button type="submit"><DualText en="Locate" zh="定位" /></button>
        </form>
      </div>
      {message ? <p className="twb-locator-message" role="status">{message}</p> : null}

      <div className="twb-table-wrap" tabIndex={0} aria-label="TriWorldBench leaderboard">
        <table
          className="twb-dense-table"
          style={{ "--twb-score-column-count": TRIWORLD_TABLE_METRICS.length } as React.CSSProperties}
        >
          <thead>
            <tr>
              <th className="twb-model-col twb-sticky-col"><DualText en="Model" zh="模型" /></th>
              <th className="twb-col-rank twb-sticky-rank"><DualText en="#" zh="名次" /></th>
              {TRIWORLD_TABLE_METRICS.map((metric) => {
                const label = textFor(metricTexts, metric.code, metric.code);
                return (
                  <th
                    className={`${metric.className}${metric.isCategory ? " is-category" : ""}${metric.isOverall ? " is-overall" : ""} twb-metric-header`}
                    data-metric-code={metric.code}
                    key={metric.code}
                    style={{ "--metric-accent": metric.color } as React.CSSProperties}
                    title={metricTexts[metric.code]?.description?.en || label.en}
                  >
                    <MetricHeaderText text={label} />
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.flatMap((row, index) => {
              const color = TRIWORLD_COLORS[index % TRIWORLD_COLORS.length];
              const range = ranges.find((item) => item.start === index);
              const isHighlighted = highlightedName === row.modelName;
              const entry = (
                <tr
                  key={row.modelName}
                  ref={(node) => {
                    if (node) rowRefs.current.set(row.modelName, node);
                    else rowRefs.current.delete(row.modelName);
                  }}
                  data-highlighted={isHighlighted ? "true" : undefined}
                  style={{ "--model-highlight": color } as React.CSSProperties}
                >
                  <td className="twb-model-col twb-sticky-col">
                    <b>{row.modelName}</b>
                    {row.teamName ? <small>{row.teamName}</small> : null}
                  </td>
                  <td className="twb-col-rank twb-sticky-rank"><span className="twb-rank-badge">{row.rank}</span></td>
                  {TRIWORLD_TABLE_METRICS.map((metric) => {
                    const value = valueFor(row, metric.code);
                    const metricRank = metricRanks.get(metric.code)?.get(row) ?? null;
                    return (
                      <td
                        className={`${metric.className} twb-metric-cell${metric.isCategory ? " twb-category-score" : ""}${metric.isOverall ? " twb-overall-score" : ""}`}
                        data-metric-code={metric.code}
                        data-metric-rank={metricRank ?? undefined}
                        key={metric.code}
                      >
                        <div className="twb-score-cell">
                          {metricRank !== null ? (
                            <span
                              className={`twb-cell-rank rank-${metricRank <= 3 ? metricRank : "other"}`}
                              aria-label={`Rank ${metricRank}`}
                            >
                              {metricRank <= 3 ? (
                                <FaMedal
                                  aria-hidden="true"
                                  className={`twb-cell-medal medal-${metricRank}`}
                                />
                              ) : null}
                              #{metricRank}
                            </span>
                          ) : null}
                          <span className="twb-score-value">{displayScore(value)}</span>
                        </div>
                      </td>
                    );
                  })}
                </tr>
              );
              return range
                ? [
                    <tr className="twb-subchart-row" key={`range-${range.index}`} id={`leaderboard-range-${range.index}`}>
                      <td className="twb-model-col twb-sticky-col twb-range-label-cell">
                        <DualText
                          en={range.label}
                          zh={range.start === 0 ? `前 ${range.end} 名` : `第 ${range.start + 1}-${range.end} 名`}
                        />
                      </td>
                      <td className="twb-col-rank twb-sticky-rank twb-range-rank-cell" aria-hidden="true" />
                      <td className="twb-range-metric-cell" colSpan={TRIWORLD_TABLE_METRICS.length} aria-hidden="true" />
                    </tr>,
                    entry,
                  ]
                : [entry];
            })}
          </tbody>
        </table>
      </div>
    </article>
  );
}
