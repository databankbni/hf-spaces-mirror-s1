import { getDb } from "@/lib/db";
import { all } from "@/lib/db/helpers";
import { contentValue, hasLocalizedText, localized, type LocalizedText } from "@/lib/i18n";

export interface TriWorldContentSection {
  id: number;
  sectionKey: string;
  titleText: LocalizedText;
  bodyText: LocalizedText;
  secondaryBodyText: LocalizedText;
  imagePath: string | null;
  imageAltText: LocalizedText;
  captionText: LocalizedText;
}

export interface TriWorldConsistencyNode {
  id: number;
  nodeKey: string;
  nodeType: "input" | "check" | "protocol" | "output";
  titleText: LocalizedText;
  bodyText: LocalizedText;
}

export interface TriWorldMetricRouting {
  id: number;
  blockText: LocalizedText;
  metricsText: LocalizedText;
  inputsText: LocalizedText;
  outputText: LocalizedText;
}

export interface TriWorldMetricDefinitionItem {
  id: number;
  itemKey: string;
  titleText: LocalizedText;
  bodyText: LocalizedText;
}

export interface TriWorldMetricDefinitionGroup {
  id: number;
  groupKey: string;
  titleText: LocalizedText;
  summaryText: LocalizedText;
  items: TriWorldMetricDefinitionItem[];
}

interface ContentSectionRow {
  id: number;
  section_key: string;
  title_en: string;
  title_zh: string;
  body_en: string;
  body_zh: string;
  secondary_body_en: string | null;
  secondary_body_zh: string | null;
  image_path: string | null;
  image_alt_en: string | null;
  image_alt_zh: string | null;
  caption_en: string | null;
  caption_zh: string | null;
}

interface ConsistencyNodeRow {
  id: number;
  node_key: string;
  node_type: TriWorldConsistencyNode["nodeType"];
  title_en: string;
  title_zh: string;
  body_en: string;
  body_zh: string;
}

interface MetricRoutingRow {
  id: number;
  block_en: string;
  block_zh: string;
  metrics_en: string;
  metrics_zh: string;
  inputs_en: string;
  inputs_zh: string;
  output_en: string;
  output_zh: string;
}

interface MetricDefinitionGroupRow {
  id: number;
  group_key: string;
  title_en: string;
  title_zh: string;
  summary_en: string;
  summary_zh: string;
}

interface MetricDefinitionItemRow {
  id: number;
  group_id: number;
  item_key: string;
  title_en: string;
  title_zh: string;
  body_en: string;
  body_zh: string;
}

export function getTriWorldContentSections(): TriWorldContentSection[] {
  const rows = all<ContentSectionRow>(
    getDb().prepare("SELECT * FROM triworld_content_sections ORDER BY sort_order, id")
  );
  return rows
    .map((row) => ({
      id: row.id,
      sectionKey: row.section_key,
      titleText: localized(row.title_en, row.title_zh),
      bodyText: localized(row.body_en, row.body_zh),
      secondaryBodyText: localized(row.secondary_body_en || "", row.secondary_body_zh || ""),
      imagePath: contentValue(row.image_path) || null,
      imageAltText: localized(row.image_alt_en || row.title_en, row.image_alt_zh || row.title_zh),
      captionText: localized(row.caption_en || "", row.caption_zh || ""),
    }))
    .filter((section) =>
      hasLocalizedText(section.titleText) ||
      hasLocalizedText(section.bodyText) ||
      hasLocalizedText(section.secondaryBodyText) ||
      Boolean(section.imagePath)
    );
}

export function getTriWorldConsistencyNodes(): TriWorldConsistencyNode[] {
  const rows = all<ConsistencyNodeRow>(
    getDb().prepare("SELECT * FROM triworld_consistency_nodes ORDER BY sort_order, id")
  );
  return rows
    .map((row) => ({
      id: row.id,
      nodeKey: row.node_key,
      nodeType: row.node_type,
      titleText: localized(row.title_en, row.title_zh),
      bodyText: localized(row.body_en, row.body_zh),
    }))
    .filter((node) => hasLocalizedText(node.titleText) || hasLocalizedText(node.bodyText));
}

export function getTriWorldMetricRouting(): TriWorldMetricRouting[] {
  const rows = all<MetricRoutingRow>(
    getDb().prepare("SELECT * FROM triworld_metric_routing ORDER BY sort_order, id")
  );
  return rows
    .map((row) => ({
      id: row.id,
      blockText: localized(row.block_en, row.block_zh),
      metricsText: localized(row.metrics_en, row.metrics_zh),
      inputsText: localized(row.inputs_en, row.inputs_zh),
      outputText: localized(row.output_en, row.output_zh),
    }))
    .filter((row) =>
      hasLocalizedText(row.blockText) ||
      hasLocalizedText(row.metricsText) ||
      hasLocalizedText(row.inputsText) ||
      hasLocalizedText(row.outputText)
    );
}

export function getTriWorldMetricDefinitionGroups(): TriWorldMetricDefinitionGroup[] {
  try {
    const database = getDb();
    const groups = all<MetricDefinitionGroupRow>(
      database.prepare("SELECT * FROM triworld_metric_definition_groups ORDER BY sort_order, id")
    );
    const items = all<MetricDefinitionItemRow>(
      database.prepare("SELECT * FROM triworld_metric_definition_items ORDER BY sort_order, id")
    );
    const itemsByGroup = new Map<number, TriWorldMetricDefinitionItem[]>();
    for (const item of items) {
      const groupItems = itemsByGroup.get(item.group_id) || [];
      const mappedItem = {
        id: item.id,
        itemKey: item.item_key,
        titleText: localized(item.title_en, item.title_zh),
        bodyText: localized(item.body_en, item.body_zh),
      };
      if (hasLocalizedText(mappedItem.titleText) || hasLocalizedText(mappedItem.bodyText)) {
        groupItems.push(mappedItem);
      }
      itemsByGroup.set(item.group_id, groupItems);
    }
    return groups
      .map((group) => ({
        id: group.id,
        groupKey: group.group_key,
        titleText: localized(group.title_en, group.title_zh),
        summaryText: localized(group.summary_en, group.summary_zh),
        items: itemsByGroup.get(group.id) || [],
      }))
      .filter((group) =>
        hasLocalizedText(group.titleText) ||
        hasLocalizedText(group.summaryText) ||
        group.items.length > 0
      );
  } catch {
    return [];
  }
}
