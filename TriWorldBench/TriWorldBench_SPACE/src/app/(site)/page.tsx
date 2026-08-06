import React from "react";
import type { LeaderboardEntry } from "@/lib/db/schema";
import { getSharedPageData } from "@/lib/data/page-data";
import { getDatasetsWithVersions } from "@/lib/data/datasets";
import { getMetrics } from "@/lib/data/metrics";
import { getPageAffiliations, getPageAuthors } from "@/lib/data/page-people";
import {
  getTriWorldContentSections,
  getTriWorldMetricDefinitionGroups,
  type TriWorldConsistencyNode,
  type TriWorldContentSection,
  type TriWorldMetricDefinitionGroup,
  type TriWorldMetricRouting,
} from "@/lib/data/triworld-content";
import { getTriWorldVisualMetrics } from "@/lib/data/triworld-visual-metrics";
import { getTriWorldAdvantages } from "@/lib/data/triworld-advantages";
import {
  TRIWORLD_ALL_METRIC_CODES,
  TRIWORLD_EVALUATION_DEFINITION_CODES,
  TRIWORLD_METRIC_GROUPS,
  TRIWORLD_RANKING_CODE,
  TRIWORLD_TABLE_METRICS,
  type TriWorldBoardEntry,
} from "@/components/triworldbench/metrics";
import { TriWorldLeaderboard } from "@/components/triworldbench/Leaderboard";
import { LocalizedMarkdown } from "@/components/triworldbench/LocalizedMarkdown";
import {
  TriWorldCases,
  TriWorldVisualization,
  type TriWorldMetricText,
} from "@/components/triworldbench/ClientSections";
import { LanguageMenu } from "@/components/triworldbench/LanguageMenu";
import { FaGithub } from "react-icons/fa";
import { contentValue, hasLocalizedText, isEmptyContentMarker, localized, type LocalizedText } from "@/lib/i18n";
import { getTriWorldHeroActions } from "@/lib/data/triworld-hero-actions";
import { getTriWorldNavItems } from "@/lib/data/triworld-nav-items";
import { getHomepageEntrySections } from "@/lib/data/submission-guide";

export const dynamic = "force-dynamic";

const RANK_MEDALS = ["🥇", "🥈", "🥉"] as const;

const ADVANTAGES = [
  {
    title: ["Multi-View Consistency", "多视角一致性"],
    body: [
      "TriWorldBench requires synchronized head, left, and right camera rollouts. Models must preserve geometric identity, object permanence, and robot-arm pose across every viewpoint.",
      "TriWorldBench 要求同步生成头部、左腕和右腕三路相机预测。模型需要在每个视角中保持几何身份、物体持续性和机械臂姿态一致。",
    ],
    them: "VBench",
    themNote: ["Single-view focus", "侧重单视角"],
    us: "TriWorldBench",
    usNote: ["Three-view synchronization", "三视角同步"],
  },
  {
    title: ["Physical Plausibility Gate", "物理合理性门控"],
    body: [
      "TriWorldBench explicitly checks contact plausibility, support relations, collision-free motion, and gravity adherence. Fluent but physically impossible rollouts are penalized.",
      "TriWorldBench 会显式检查接触合理性、支撑关系、无碰撞运动以及重力约束。流畅但物理上不可能的预测会被扣分。",
    ],
    them: "EvalCrafter",
    themNote: ["No physics gate", "无物理门控"],
    us: "TriWorldBench",
    usNote: ["Physics-gated", "物理约束评估"],
  },
  {
    title: ["Language-Action Alignment", "语言-动作对齐"],
    body: [
      "Every rollout is conditioned on a natural-language instruction. Evaluation checks whether the visible robot behavior actually completes the commanded action.",
      "每段预测都以自然语言指令为条件。评估会检查可见机器人行为是否真正完成了指令要求的动作。",
    ],
    them: "FVD / PSNR",
    themNote: ["Appearance-first", "外观优先"],
    us: "TriWorldBench",
    usNote: ["Action grounding", "动作落地"],
  },
  {
    title: ["Cross-Embodiment Generalization", "跨具身泛化"],
    body: [
      "Submissions cover tabletop arms, mobile manipulation platforms, and bimanual systems. Generalization across embodiments is a first-class TriWorldBench evaluation dimension.",
      "提交内容覆盖桌面机械臂、移动操作平台和双臂系统。跨具身泛化是 TriWorldBench 的核心评估维度之一。",
    ],
    them: "Single-robot evaluation",
    themNote: ["Single platform", "单一平台"],
    us: "TriWorldBench",
    usNote: ["Multiple embodied platforms", "多具身平台"],
  },
] as const;

const STATIC_ACADEMIC_PARAGRAPHS = [
  [
    "World models are predictive simulators that learn how an environment evolves under action, enabling agents to imagine future observations before they act. In robotics, this direction is increasingly merging with Vision-Language-Action systems.",
    "世界模型是学习环境如何在动作影响下演化的预测式模拟器，让智能体在行动前预想未来观测。在机器人领域，这一方向正在与视觉、语言和动作一体化系统进一步融合。",
  ],
  [
    "Existing evaluation stacks do not fully track that goal. Video-generation metrics reward photorealism but rarely explain whether motion in the scene is physically feasible; robotics policy benchmarks measure task success but often ignore prediction quality.",
    "现有评估体系并不能完整追踪这一目标。视频生成指标通常奖励逼真外观，却很少解释场景运动是否物理可行；机器人策略基准会衡量任务成功率，但往往忽略预测质量。",
  ],
  [
    "TriWorldBench introduces a World Model Video Evaluation framework designed for multi-view robots and robotic-arm motion prediction. Each submission generates synchronized multi-camera rollouts conditioned on language instructions.",
    "TriWorldBench 提供面向多视角机器人和机械臂运动预测的世界模型视频评测框架。每个提交都需要基于语言指令生成同步的多相机预测序列。",
  ],
  [
    "The framework combines visual quality and temporal-dynamics metrics for appearance and motion, physical common-sense video evaluation for plausibility, and cross-embodiment policy-transfer ideas for instruction grounding.",
    "该框架结合视觉质量与时序动态指标来评估外观和运动，结合物理常识视频评估来衡量合理性，并引入跨具身策略迁移思路来检验指令落地。",
  ],
  [
    "The final goal of TriWorldBench is to identify world models that can serve as reliable simulators for real-world manipulation: their multi-view predictions should be physically credible, viewpoint-consistent, and responsive to language instructions.",
    "TriWorldBench 的最终目标是识别能够作为真实世界操作可靠模拟器的世界模型：它们的多视角预测应当物理可信、视角一致，并能响应语言指令。",
  ],
] as const;

function I18n({ en, zh }: { en: React.ReactNode; zh: React.ReactNode }) {
  return (
    <>
      <span className="i18n-en">{en}</span>
      <span className="i18n-zh">{zh}</span>
    </>
  );
}

function I18nText({ text }: { text?: LocalizedText }) {
  if (!hasLocalizedText(text)) return null;
  return <LocalizedMarkdown text={text} inline />;
}

function metricHeaderLines(value: string): string[] {
  const words = value.trim().split(/\s+/).filter(Boolean);
  if (words.length <= 2) return [value.trim()];
  const lines: string[] = [];
  for (let index = 0; index < words.length; index += 2) {
    lines.push(words.slice(index, index + 2).join(" "));
  }
  return lines;
}

function MetricHeaderText({ text }: { text?: LocalizedText }) {
  const en = contentValue(text?.en);
  const zh = contentValue(text?.zh);
  if (!en && !zh) return null;
  return (
    <>
      {en ? (
        <span className="i18n-en twb-metric-header-text">
          {metricHeaderLines(en).map((line, index) => (
            <span className="twb-metric-header-line" key={`${line}-${index}`}>{line}</span>
          ))}
        </span>
      ) : null}
      {zh ? (
        <span className="i18n-zh twb-metric-header-text">
          {metricHeaderLines(zh).map((line, index) => (
            <span className="twb-metric-header-line" key={`${line}-${index}`}>{line}</span>
          ))}
        </span>
      ) : null}
    </>
  );
}

function fmt(value: number | null | undefined, decimals = 4): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "TBA";
  }
  return Number(value).toFixed(decimals);
}

function buildValueRanks(
  rows: TriWorldBoardEntry[],
  getValue: (row: TriWorldBoardEntry) => number | null
): Map<string, number> {
  const sorted = rows
    .map((row) => ({ modelName: row.modelName, value: getValue(row) }))
    .filter((item): item is { modelName: string; value: number } =>
      item.value !== null && Number.isFinite(item.value)
    )
    .sort((a, b) => b.value - a.value);
  const ranks = new Map<string, number>();
  let previousValue: number | null = null;
  let previousRank = 0;
  sorted.forEach((item, index) => {
    const rank = previousValue !== null && item.value === previousValue ? previousRank : index + 1;
    ranks.set(item.modelName, rank);
    previousValue = item.value;
    previousRank = rank;
  });
  return ranks;
}

function RankedScore({ value, rank }: { value: number | null; rank?: number }) {
  const rankMarker = rank && rank <= 3 ? RANK_MEDALS[rank - 1] : rank ? `#${rank}` : null;
  return (
    <span className="twb-ranked-score">
      <span className="twb-score-value">{fmt(value)}</span>
      {rankMarker ? (
        <small
          aria-label={`Rank ${rank}`}
          className={`twb-cell-rank rank-${rank && rank <= 3 ? rank : "other"}`}
        >
          {rankMarker}
        </small>
      ) : null}
    </span>
  );
}

function toBoardEntries(entries: LeaderboardEntry[]): TriWorldBoardEntry[] {
  return entries.map((entry) => {
    const metrics: Record<string, number | null> = {};
    const normalizedMetrics: Record<string, number | null> = {};
    for (const code of TRIWORLD_ALL_METRIC_CODES) {
      metrics[code] = entry.metrics[code]?.rawValue ?? null;
      normalizedMetrics[code] = entry.metrics[code]?.rawValue ?? null;
    }
    return {
      rank: entry.rank,
      modelName: entry.model.name,
      teamName: entry.team.name,
      score: entry.metrics[TRIWORLD_RANKING_CODE]?.rawValue ?? entry.score.rawValue ?? null,
      normalizedScore: entry.metrics[TRIWORLD_RANKING_CODE]?.rawValue ?? entry.score.rawValue ?? null,
      status: entry.statusLabel || entry.submission.status,
      metrics,
      normalizedMetrics,
    };
  });
}

function SectionHead({ number, title }: { number: string; title: React.ReactNode }) {
  return (
    <div className="section-head">
      <span>{number}</span>
      <h2>{title}</h2>
    </div>
  );
}

function ContentFigure({ section }: { section: TriWorldContentSection }) {
  if (!section.imagePath) return null;
  const hasCaption = hasLocalizedText(section.captionText);
  return (
    <figure className="twb-content-figure">
      <span className="twb-content-figure-frame">
        <img
          src={section.imagePath}
          alt={section.imageAltText.en}
          loading="lazy"
        />
      </span>
      {hasCaption ? <figcaption><I18nText text={section.captionText} /></figcaption> : null}
    </figure>
  );
}

function FlowConnector({
  branches,
  direction,
}: {
  branches: 3 | 4;
  direction: "split" | "merge";
}) {
  const positions = branches === 3 ? [167, 500, 833] : [125, 375, 625, 875];
  return (
    <div className={`twb-flow-connector is-${direction} is-${branches}`} aria-hidden="true">
      <svg viewBox="0 0 1000 52" preserveAspectRatio="none" focusable="false">
        {positions.map((position) => (
          <path
            d={direction === "split"
              ? `M 500 0 V 18 H ${position} V 42`
              : `M ${position} 0 V 18 H 500 V 42`}
            className="twb-flow-line"
            key={position}
          />
        ))}
        {direction === "split" ? positions.map((position) => (
          <path className="twb-flow-arrowhead" d={`M ${position - 5} 35 L ${position} 43 L ${position + 5} 35 Z`} key={`arrow-${position}`} />
        )) : <path className="twb-flow-arrowhead" d="M 495 35 L 500 43 L 505 35 Z" />}
      </svg>
      <span>↓</span>
    </div>
  );
}

function ConsistencyFlow({
  nodes,
  caption,
}: {
  nodes: TriWorldConsistencyNode[];
  caption: LocalizedText;
}) {
  const byKey = new Map(nodes.map((node) => [node.nodeKey, node]));
  const renderNode = (nodeKey: string, role: string) => {
    const node = byKey.get(nodeKey);
    if (!node) return null;
    return (
      <article className={`twb-protocol-node is-${node.nodeType} is-${role}`} key={node.id}>
        {hasLocalizedText(node.titleText) ? <h3><I18nText text={node.titleText} /></h3> : null}
        {hasLocalizedText(node.bodyText) ? <p><I18nText text={node.bodyText} /></p> : null}
      </article>
    );
  };
  return (
    <figure className="twb-protocol-figure">
      <div className="twb-protocol-flow twb-protocol-flow-v2">
        <div className="twb-protocol-row is-reference">
          {renderNode("state_input", "reference")}
        </div>
        <FlowConnector branches={3} direction="split" />
        <div className="twb-protocol-row is-taxonomy">
          {renderNode("robot_action", "taxonomy")}
          {renderNode("target_object", "taxonomy")}
          {renderNode("evidence_status", "taxonomy")}
        </div>
        <FlowConnector branches={3} direction="merge" />
        <div className="twb-protocol-row is-rubric">
          {renderNode("shared_rubric", "rubric")}
        </div>
        <FlowConnector branches={4} direction="split" />
        <div className="twb-protocol-row is-protocols">
          {renderNode("compatibility_first", "protocol")}
          {renderNode("verification_first", "protocol")}
          {renderNode("exemplar_calibrated", "protocol")}
          {renderNode("question_based", "protocol")}
        </div>
        <FlowConnector branches={4} direction="merge" />
        <div className="twb-protocol-outcomes">
          {renderNode("expert_alignment", "expert")}
          <span className="twb-outcome-arrow" aria-hidden="true">→</span>
          {renderNode("frozen_primary", "frozen")}
        </div>
      </div>
      <figcaption><I18nText text={caption} /></figcaption>
    </figure>
  );
}

function MetricRoutingTable({ rows }: { rows: TriWorldMetricRouting[] }) {
  return (
    <div className="twb-routing-table-wrap">
      <table className="twb-routing-table">
        <colgroup>
          <col className="twb-routing-block" />
          <col className="twb-routing-metrics" />
          <col className="twb-routing-inputs" />
          <col className="twb-routing-output" />
        </colgroup>
        <thead>
          <tr>
            <th><I18n en="Evaluation block" zh="评价模块" /></th>
            <th><I18n en="Metrics" zh="指标" /></th>
            <th><I18n en="Inputs" zh="输入" /></th>
            <th><I18n en="Output" zh="输出" /></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <th scope="row"><I18nText text={row.blockText} /></th>
              <td><I18nText text={row.metricsText} /></td>
              <td><I18nText text={row.inputsText} /></td>
              <td><I18nText text={row.outputText} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MetricDefinitions({ groups }: { groups: TriWorldMetricDefinitionGroup[] }) {
  if (!groups.length) return null;
  return (
    <div className="twb-evaluation-metrics">
      {groups.map((group) => {
        const normalizedKey = group.groupKey.toLocaleLowerCase().replace(/[_\s]+/g, "-").replace(/[^a-z0-9-]/g, "");
        const matchedGroup = TRIWORLD_METRIC_GROUPS.find((item) =>
          item.key === normalizedKey || item.code.toLocaleLowerCase().replace(/_/g, "-") === normalizedKey
        );
        return (
        <article
          className={`twb-evaluation-group${matchedGroup ? " submetric-border-left" : ""}`}
          key={group.id}
          style={matchedGroup ? ({ "--submetric-border-left": matchedGroup.color } as React.CSSProperties) : undefined}
        >
          {hasLocalizedText(group.titleText) ? <h3><I18nText text={group.titleText} /></h3> : null}
          {hasLocalizedText(group.summaryText) ? <LocalizedMarkdown text={group.summaryText} /> : null}
          {group.items.length ? (
            <div className="twb-evaluation-items">
              {group.items.map((item) => (
                <article className="twb-evaluation-item" key={item.id}>
                  {hasLocalizedText(item.titleText) ? <h4><I18nText text={item.titleText} /></h4> : null}
                  {hasLocalizedText(item.bodyText) ? <LocalizedMarkdown text={item.bodyText} /> : null}
                </article>
              ))}
            </div>
          ) : null}
        </article>
        );
      })}
    </div>
  );
}

function LeaderboardTable({
  rows,
  metricTexts,
}: {
  rows: TriWorldBoardEntry[];
  metricTexts: Record<string, TriWorldMetricText>;
}) {
  const rankByCode = new Map<string, Map<string, number>>();
  rankByCode.set(TRIWORLD_RANKING_CODE, buildValueRanks(rows, (row) => row.score));
  for (const metric of TRIWORLD_TABLE_METRICS) {
    rankByCode.set(
      metric.code,
      buildValueRanks(rows, (row) => row.metrics[metric.code] ?? null)
    );
  }
  return (
    <article className="twb-rich-card twb-overall">
      <p className="twb-board-note">
          <I18n
            en="Scores are reported on their native metric scales. TWBScore determines the public rank; hover a row to track one model across all 16 component metrics."
            zh="分数按各指标原始量纲展示。TWBScore 决定公开排名；悬停表格行可横向追踪同一模型的全部 16 项组成指标。"
          />
      </p>
      <div className="twb-table-wrap">
        <table
          className="twb-dense-table"
          style={{ "--twb-score-column-count": TRIWORLD_TABLE_METRICS.length + 1 } as React.CSSProperties}
        >
          <thead><tr>
            <th className="twb-model-col twb-sticky-col"><I18n en="Model" zh="模型" /></th>
            <th className="twb-col-rank twb-sticky-rank"><I18n en="#" zh="名次" /></th>
            <th className="twb-col-score" title="Primary composite ranking score">
              <span className="twb-metric-header-text">
                <span className="twb-metric-header-line">TWB-Score</span>
              </span>
            </th>
            {TRIWORLD_TABLE_METRICS.map((metric) => (
              <th className={metric.className} key={metric.code} title={metricTexts[metric.code]?.description?.en || metric.code}>
                <MetricHeaderText text={metricTexts[metric.code]?.shortLabel || metricTexts[metric.code]?.label} />
              </th>
            ))}
          </tr></thead>
          <tbody>{rows.map((row) => {
            const scoreRank = rankByCode.get(TRIWORLD_RANKING_CODE)?.get(row.modelName);
            return (
              <tr key={row.modelName}>
                <td className="twb-model-col twb-sticky-col">
                  <b>{row.modelName}</b>
                  <small>{row.teamName}</small>
                </td>
                <td className="twb-col-rank twb-sticky-rank">
                  <span className={`twb-rank-badge rank-${Math.min(row.rank, 4)}`}>
                    {row.rank <= 3 ? RANK_MEDALS[row.rank - 1] : row.rank}
                  </span>
                </td>
                <td className={`twb-col-score${scoreRank === 1 ? " twb-best" : ""}`}><RankedScore value={row.score} rank={scoreRank} /></td>
                {TRIWORLD_TABLE_METRICS.map((metric) => {
                  const metricRank = rankByCode.get(metric.code)?.get(row.modelName);
                  return <td className={`${metric.className}${metricRank === 1 ? " twb-best" : ""}`} key={metric.code}>
                    <RankedScore value={row.metrics[metric.code]} rank={metricRank} />
                  </td>;
                })}
              </tr>
            );
          })}</tbody>
        </table>
      </div>
    </article>
  );
}

export default function TriWorldPage() {
  const shared = getSharedPageData();
  const datasets = getDatasetsWithVersions();
  const homepageEntrySections = getHomepageEntrySections();
  const datasetsEntry = homepageEntrySections.find((entry) => entry.sectionKey === "datasets");
  const submissionEntry = homepageEntrySections.find((entry) => entry.sectionKey === "submission");
  const metrics = getMetrics();
  const contentSections = getTriWorldContentSections();
  const abstractSection = contentSections.find((section) => section.sectionKey === "abstract");
  const overviewSection = contentSections.find((section) => section.sectionKey === "overview");
  const advantagesSection = contentSections.find((section) => section.sectionKey === "advantages");
  const casesSection = contentSections.find((section) => section.sectionKey === "cases");
  const metricsSection = contentSections.find((section) => section.sectionKey === "metrics");
  const leaderboardSection = contentSections.find((section) => section.sectionKey === "leaderboard");
  const visualizationSection = contentSections.find((section) => section.sectionKey === "visualization");
  const casesTitleText = casesSection?.titleText || localized("Visualization Cases", "可视化案例");
  const casesBodyText = casesSection?.bodyText || localized(
    "This section presents representative rollouts generated by participating systems. Each clip is a synchronized multi-view prediction conditioned on a natural-language instruction. **Clean** and **random** represent two different video surroundings and backgrounds. The video is composed of three views; from left to right they are **left**, **head**, and **right**. Evaluating the consistency of these three perspectives is the unique feature and important content of this benchmark.",
    "本节展示参赛系统生成的代表性预测片段，每个片段均由自然语言指令作为条件，驱动同步多视角预测生成。干净背景与随机背景分别代表两类不同的视频环境设置。每段视频由三个视角组成，从左至右依次为左腕、头部和右腕视角。评估三个视角之间的一致性，是本基准的核心特征与重要组成部分。"
  );
  const leaderboardTitleText = leaderboardSection?.titleText || localized(
    "TriWorldBench Leaderboard",
    "TriWorldBench 榜单"
  );
  const leaderboardBodyText = leaderboardSection?.bodyText || localized(
    "Browse every published model in one leaderboard. Use a rank range to jump to its block, or locate a model name without changing the displayed ranking.",
    "全部已发布模型会保留在同一张榜单中，可通过排名区间跳转，或按模型名称定位，不会改变榜单的显示结果。"
  );
  const visualizationTitleText = visualizationSection?.titleText || localized(
    "Leaderboard Visualization",
    "榜单可视化"
  );
  const visualizationBodyText = visualizationSection?.bodyText || localized(
    "The **overall radar** shows the six category scores on a 0-100 scale. Search by part of a model name to focus the radar and ranking on matching models, then click a model to read its values at the radar vertices. Use the overall, category, or individual-metric buttons to change the ranking view below.",
    "总体雷达图基于六个类别得分，以不同的分数尺度展示模型表现。用户可输入部分模型名称，筛选对应雷达图及下方排名结果；点击模型后，可在雷达图各顶点查看对应分数。通过总分、类别或具体指标按钮，可切换下方排名展示视图。"
  );
  const metricDefinitionGroups = getTriWorldMetricDefinitionGroups();
  const metricTexts: Record<string, TriWorldMetricText> = Object.fromEntries(
    metrics.map((metric) => [
      metric.code,
      {
        code: metric.code,
        label: metric.displayNameText || localized(metric.display_name, metric.display_name_zh),
        shortLabel: metric.shortLabelText || metric.displayNameText || localized(metric.display_name, metric.display_name_zh),
        title: localized(`${metric.display_name_en || metric.display_name} - ranked`, `${metric.display_name_zh || metric.display_name} - 排名`),
        description: metric.descriptionText || localized(metric.description_en || metric.description || "", metric.description_zh),
        category: metric.category,
      },
    ])
  );
  for (const item of getTriWorldVisualMetrics()) {
    const key = item.metric_code === "__overall__" ? "__overall__" : item.metric_code;
    metricTexts[key] = {
      ...metricTexts[key],
      code: key,
      label: localized(item.label_en, item.label_zh),
      shortLabel: localized(item.label_en, item.label_zh),
      title: localized(item.title_en, item.title_zh),
    };
  }
  for (const group of metricDefinitionGroups) {
    const groupCode = TRIWORLD_EVALUATION_DEFINITION_CODES[group.groupKey];
    if (groupCode && metricTexts[groupCode]) {
      metricTexts[groupCode] = {
        ...metricTexts[groupCode],
        label: group.titleText,
        shortLabel: group.titleText,
      };
    }
    for (const item of group.items) {
      const itemCode = TRIWORLD_EVALUATION_DEFINITION_CODES[item.itemKey];
      if (itemCode && metricTexts[itemCode]) {
        metricTexts[itemCode] = {
          ...metricTexts[itemCode],
          label: item.titleText,
          shortLabel: item.titleText,
        };
      }
    }
  }
  const radarCategoryTexts: Record<string, LocalizedText> = Object.fromEntries(
    TRIWORLD_METRIC_GROUPS
      .filter((group) => group.code !== TRIWORLD_RANKING_CODE)
      .map((group) => {
        const definitionGroup = metricDefinitionGroups.find(
          (item) => item.groupKey.toLocaleLowerCase().replace(/[_\s]+/g, "-").replace(/[^a-z0-9-]/g, "") === group.key
        );
        return [
          group.code,
          definitionGroup?.titleText || metricTexts[group.code]?.label || { en: group.code, zh: group.code },
        ];
      })
  );
  const authors = getPageAuthors();
  const affiliations = getPageAffiliations();
  const navItems = getTriWorldNavItems();
  const advantages = getTriWorldAdvantages();
  const heroEyebrow = isEmptyContentMarker(shared.hero?.eyebrow)
    ? ""
    : contentValue(shared.hero?.eyebrow) || "World Model Benchmark";
  const githubUrlIsHidden = isEmptyContentMarker(shared.siteInfo?.github_url);
  const heroActions = getTriWorldHeroActions().filter(
    (action) => action.actionKey !== "github" || !githubUrlIsHidden
  );
  const configuredGithubUrl = contentValue(shared.siteInfo?.github_url);
  const githubUrl = configuredGithubUrl && configuredGithubUrl !== "#"
    ? configuredGithubUrl
    : "https://github.com/TriWorldBench/TriWorldBench";
  const rows = toBoardEntries(shared.leaderboard.entries);
  const contacts = shared.contacts.filter(
    (contact) => Boolean(contentValue(contact.value)) && hasLocalizedText(contact.labelText)
  );
  const visibleSectionKeys = [
    abstractSection ? "abstract" : null,
    overviewSection ? "overview" : null,
    advantagesSection ? "advantages" : null,
    "cases",
    metricsSection ? "metrics" : null,
    "leaderboard",
    "visualization",
    datasetsEntry ? "datasets" : null,
    "policies",
    submissionEntry ? "submission" : null,
    "contact",
  ].filter((key): key is string => Boolean(key));
  const sectionNumbers = new Map(
    visibleSectionKeys.map((key, index) => [key, String(index + 1).padStart(2, "0")])
  );
  const sectionNumber = (key: string) => sectionNumbers.get(key) || "00";

  return (
    <div data-page="triworldbench" className="twb-doc">
      <header className="site-nav">
        <a className="brand" href="#top">
          TriWorldBench
        </a>
        <nav>
          {navItems.map((item) => (
            <a
              href={item.href}
              key={item.id}
              target={item.openInNewTab ? "_blank" : undefined}
              rel={item.openInNewTab ? "noopener" : undefined}
            >
              <I18nText text={item.labelText} />
            </a>
          ))}
        </nav>
        <LanguageMenu />
      </header>

      <section id="top" className="twb-hero">
        <div className="twb-hero-bg" aria-hidden="true" />
        <div className="twb-hero-inner">
          {heroEyebrow ? (
            <p className="eyebrow">
              <I18n en={heroEyebrow} zh="世界模型基准测试" />
            </p>
          ) : null}
          <h1>
            TriWorldBench
            <br />
            <span className="twb-accent">
              <I18n en="A Benchmark Evaluating Triple-View Embodied World Models" zh="评估三视角具身世界模型的基准测试" />
            </span>
          </h1>
          <div className="actions">
            {heroActions.map((action) => {
              const href = action.actionKey === "github" ? githubUrl : action.href;
              const openInNewTab = action.openInNewTab || action.actionKey === "github";
              return (
                <a
                  className="hero-action-primary"
                  href={href}
                  key={action.id}
                  target={openInNewTab ? "_blank" : undefined}
                  rel={openInNewTab ? "noopener" : undefined}
                >
                  {action.actionKey === "github" ? <FaGithub aria-hidden="true" size={16} /> : null}
                  <I18nText text={action.labelText} />
                </a>
              );
            })}
          </div>
          <div className="twb-authors">
            {authors.length ? (
              <p className="twb-authors-list">
                {authors.map((author, index) => (
                  <span key={author.id}>
                    <a href={author.url || "#"} target="_blank" rel="noopener">
                      <I18nText text={author.nameText} />
                    </a>
                    <sup>{author.affiliation_refs}</sup>
                    {index < authors.length - 1 ? " " : null}
                  </span>
                ))}
              </p>
            ) : null}
            <p className="twb-affiliations">
              {affiliations.map((affiliation) => (
                <span key={affiliation.id}>
                  <sup>{affiliation.ref}</sup>
                  <I18nText text={affiliation.nameText} />
                </span>
              ))}
            </p>
            <div className="twb-institutions">
              {affiliations.map((affiliation) => {
                const name = affiliation.nameText?.en || affiliation.name;
                const initials = name
                  .split(/\s+/)
                  .filter(Boolean)
                  .slice(0, 3)
                  .map((part) => part[0])
                  .join("")
                  .toUpperCase();
                const logo = affiliation.logo_path ? (
                  <img src={affiliation.logo_path} alt={name} loading="lazy" />
                ) : (
                  <span className="twb-institution-mark" aria-hidden="true">{initials}</span>
                );
                return affiliation.website_url ? (
                  <a
                    aria-label={name}
                    key={affiliation.id}
                    href={affiliation.website_url}
                    target="_blank"
                    rel="noopener"
                    title={name}
                  >
                    {logo}
                  </a>
                ) : (
                  <div aria-label={name} key={affiliation.id} role="img" title={name}>{logo}</div>
                );
              })}
            </div>
          </div>
        </div>
      </section>

      <main>
        {abstractSection ? (
          <section id="abstract" className="section twb-research-section">
            {hasLocalizedText(abstractSection.titleText) ? <SectionHead number={sectionNumber("abstract")} title={<I18nText text={abstractSection.titleText} />} /> : null}
            {hasLocalizedText(abstractSection.bodyText) ? <LocalizedMarkdown text={abstractSection.bodyText} /> : null}
            <ContentFigure section={abstractSection} />
            {hasLocalizedText(abstractSection.secondaryBodyText) ? <LocalizedMarkdown text={abstractSection.secondaryBodyText} /> : null}
          </section>
        ) : null}

        {overviewSection ? (
          <section id="overview" className="section overview twb-research-section">
            {hasLocalizedText(overviewSection.titleText) ? <SectionHead number={sectionNumber("overview")} title={<I18nText text={overviewSection.titleText} />} /> : null}
            {hasLocalizedText(overviewSection.bodyText) ? <div className="case-intro"><LocalizedMarkdown text={overviewSection.bodyText} /></div> : null}
            <ContentFigure section={overviewSection} />
          </section>
        ) : null}

        {advantagesSection ? (
          <section id="advantages" className="section advantages twb-research-section">
          {hasLocalizedText(advantagesSection.titleText) ? <SectionHead number={sectionNumber("advantages")} title={<I18nText text={advantagesSection.titleText} />} /> : null}
          {hasLocalizedText(advantagesSection.bodyText) ? <LocalizedMarkdown text={advantagesSection.bodyText} /> : null}
          <div className="adv-grid">
            {advantages.map((item) => (
              <article key={item.id}>
                {hasLocalizedText(item.titleText) ? <h3><I18nText text={item.titleText} /></h3> : null}
                {hasLocalizedText(item.bodyText) ? <LocalizedMarkdown text={item.bodyText} /> : null}
              </article>
            ))}
          </div>
        </section>
        ) : null}

        <section id="cases" className="section cases">
          <SectionHead number={sectionNumber("cases")} title={<I18nText text={casesTitleText} />} />
          <p><LocalizedMarkdown text={casesBodyText} inline /></p>
          <TriWorldCases />
        </section>

        {/*
        Temporarily hidden: State-Aware Tri-View Consistency. Keep the renderer and
        database-backed content source above intact so this section can be restored.
        {consistencySection ? (
          <section id="consistency" className="section twb-research-section twb-consistency-section">
            <SectionHead number="05" title={<I18nText text={consistencySection.titleText} />} />
            <p><I18nText text={consistencySection.bodyText} /></p>
            <ConsistencyFlow nodes={consistencyNodes} caption={consistencySection.captionText} />
          </section>
        ) : null}
        */}

        {metricsSection ? (
          <section id="metrics" className="section twb-research-section twb-metrics-section">
            {hasLocalizedText(metricsSection.titleText) ? <SectionHead number={sectionNumber("metrics")} title={<I18nText text={metricsSection.titleText} />} /> : null}
            {hasLocalizedText(metricsSection.bodyText) ? <div className="twb-metric-intro"><LocalizedMarkdown text={metricsSection.bodyText} /></div> : null}
            {/* Temporarily hidden: Metric routing. The data and renderer remain available for restoration. */}
            {/* <MetricRoutingTable rows={metricRouting} /> */}
            <MetricDefinitions groups={metricDefinitionGroups} />
          </section>
        ) : null}

        <section id="leaderboard" className="section twb-leader twb-v02">
          <div className="twb-v02-top">
            <div>
              <span className="twb-section-kicker">{sectionNumber("leaderboard")}</span>
              <h2><I18nText text={leaderboardTitleText} /></h2>
            </div>
            <span><I18n en={`Published models: ${rows.length}`} zh={`已发布模型：${rows.length}`} /></span>
          </div>
          <TriWorldLeaderboard rows={rows} metricTexts={metricTexts} descriptionText={leaderboardBodyText} />
        </section>

        <TriWorldVisualization
          rows={rows}
          metricTexts={metricTexts}
          categoryTexts={radarCategoryTexts}
          sectionNumber={sectionNumber("visualization")}
          titleText={visualizationTitleText}
          descriptionText={visualizationBodyText}
        />

        {datasetsEntry ? (
          <section id="datasets" className="section datasets">
            <SectionHead number={sectionNumber("datasets")} title={<I18nText text={datasetsEntry.titleText} />} />
            {hasLocalizedText(datasetsEntry.bodyText) ? <LocalizedMarkdown text={datasetsEntry.bodyText} /> : null}
            {datasetsEntry.actionHref && hasLocalizedText(datasetsEntry.actionLabelText) ? (
              <div className="ds-actions" style={{ marginTop: 18 }}>
                <a className="ds-btn" href={datasetsEntry.actionHref}>
                  <I18nText text={datasetsEntry.actionLabelText} />
                </a>
              </div>
            ) : null}
          </section>
        ) : null}

        {/*
        Temporarily hidden: Important Dates remains editable in local-admin and is
        retained in SQLite for the next public schedule release.
        <section id="dates" className="section dates">
          <SectionHead number="09" title={<I18n en="Important Dates" zh="重要日期" />} />
          <div className="timeline">
            {shared.dates.map((date) => (
              <article key={date.id}>
                <time>
                  <I18nText text={date.dateLabelText} />
                </time>
                <b><I18nText text={date.titleText} /></b>
                <p><I18nText text={date.bodyText} /></p>
              </article>
            ))}
          </div>
        </section>
        */}

        <section id="policies" className="section policies">
          <SectionHead number={sectionNumber("policies")} title={<I18n en="Policy&Rules" zh="政策与规则" />} />
          <div className="twb-policy-list">
            {shared.policies.map((policy) => {
              const hasTitle = hasLocalizedText(policy.titleText);
              const hasBody = hasLocalizedText(policy.bodyText);
              if (!hasTitle && !hasBody) return null;
              return (
                <article className="twb-policy-item" key={policy.id}>
                  {hasTitle ? <h3><I18nText text={policy.titleText} /></h3> : null}
                  {hasBody ? <LocalizedMarkdown text={policy.bodyText} /> : null}
                </article>
              );
            })}
          </div>
        </section>

        {/* Academic Background is retained in SQLite but not published on this version of the page.
        <section id="academic" className="section academic">
          <SectionHead number="11" title={<I18n en="Academic Background" zh="学术背景" />} />
          <article className="ac-article">
            <h3><I18n en="Research Lineage" zh="研究脉络" /></h3>
            {STATIC_ACADEMIC_PARAGRAPHS.map((paragraph) => (
              <p key={paragraph[0]}><I18n en={paragraph[0]} zh={paragraph[1]} /></p>
            ))}
            {shared.references.slice(0, 3).map((reference) => (
              <p key={reference.id}>
                <strong><I18nText text={reference.titleText} />.</strong> <I18nText text={reference.bodyText} />
              </p>
            ))}
          </article>
        </section>
        */}

        {submissionEntry ? (
        <section id="submission" className="section submission">
          <SectionHead number={sectionNumber("submission")} title={<I18nText text={submissionEntry.titleText} />} />
          <div className="submission-layout">
            <div className="submission-main">
              {hasLocalizedText(submissionEntry.bodyText) ? <LocalizedMarkdown text={submissionEntry.bodyText} /> : null}
              {submissionEntry.actionHref && hasLocalizedText(submissionEntry.actionLabelText) ? (
                <div className="actions">
                  <a href={submissionEntry.actionHref}><I18nText text={submissionEntry.actionLabelText} /></a>
                </div>
              ) : null}
            </div>
            <div className="sub-card" aria-label="Submission essentials">
              {datasets.uploadRequirements.slice(0, 3).map((requirement, index) => (
                <div className="sub-row" key={requirement.id}>
                  <i>{String(index + 1).padStart(2, "0")}</i>
                  <span>
                    {hasLocalizedText(requirement.titleText) ? <b><I18nText text={requirement.titleText} /></b> : null}
                    {hasLocalizedText(requirement.bodyText) ? <small><I18nText text={requirement.bodyText} /></small> : null}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </section>
        ) : null}

        <section id="contact" className="section contact">
          <SectionHead number={sectionNumber("contact")} title={<I18n en="Contact Us" zh="联系我们" />} />
          <div className="contact-grid">
            {contacts.map((contact) => (
              <article className="contact-card sub-email" data-contact-component="sub_email" key={contact.id}>
                <b><I18nText text={contact.labelText} /></b>
                {contact.image_path ? (
                  <a className="contact-download-link" href={contact.image_path} download="Group_Chat.jpg">
                    <I18n en="Download WeChat QR Code" zh="下载微信群二维码" />
                  </a>
                ) : (
                  <a href={contact.href || `mailto:${contact.value}`}>{contact.value}</a>
                )}
                {hasLocalizedText(contact.descriptionText) ? <LocalizedMarkdown text={contact.descriptionText} /> : null}
              </article>
            ))}
          </div>
        </section>

        {/* Other Information is intentionally unpublished while its database record is retained.
        <section id="other" className="section other-info">
          <SectionHead number="14" title={<I18n en="Other Information" zh="其他信息" />} />
          <div className="coming"><I18n en={otherStatusText.en} zh={otherStatusText.zh} /></div>
          <p>
            <I18n
              en={shared.otherInfo?.body || "Sponsor, media, and follow-up information will be published here."}
              zh="赞助、媒体和后续信息将在这里发布。"
            />
          </p>
        </section>
        */}

      </main>

      <footer>
        <I18n
          en="TriWorldBench / World Model Video Evaluation Benchmark"
          zh="TriWorldBench / 世界模型视频评测基准"
        />
      </footer>
    </div>
  );
}
