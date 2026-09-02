// ============================================================
// TypeScript interfaces for all 26 database tables
// Mirrors database/schema.sql
// ============================================================

// --- Singleton / meta tables ---

export interface DataVersion {
  id: number;
  version: number;
  updated_at: string;
}

export interface SiteInfo {
  id: number;
  title: string;
  short_name: string;
  tagline: string;
  description: string;
  contact_email: string | null;
  github_url: string | null;
  updated_at: string;
}

// --- Content tables ---

export interface HeroContent {
  id: number;
  eyebrow: string | null;
  title: string;
  subtitle: string;
  primary_cta_label: string | null;
  primary_cta_url: string | null;
  secondary_cta_label: string | null;
  secondary_cta_url: string | null;
  updated_at: string;
}

export interface OverviewContent {
  id: number;
  title: string;
  body: string;
  stat_json: string | null;
  stats?: string[]; // parsed from stat_json
  updated_at: string;
}

export interface EvaluationSection {
  id: number;
  title: string;
  body: string;
  category: string | null;
  sort_order: number;
  updated_at: string;
}

export interface ResearchSection {
  id: number;
  title: string;
  body: string;
  tags_json: string | null;
  tags?: string[]; // parsed from tags_json
  sort_order: number;
  updated_at: string;
}

export interface ParticipationInfo {
  id: number;
  title: string;
  body: string;
  sort_order: number;
  updated_at: string;
}

export interface VenueHostInfo {
  id: number;
  host_name: string;
  venue_name: string | null;
  location: string | null;
  body: string;
  updated_at: string;
}

export interface PolicyItem {
  id: number;
  title: string;
  title_en?: string | null;
  title_zh?: string | null;
  body: string;
  body_en?: string | null;
  body_zh?: string | null;
  sort_order: number;
  updated_at: string;
  titleText?: { en: string; zh: string };
  bodyText?: { en: string; zh: string };
}

export interface ContactInfo {
  id: number;
  label: string;
  label_en?: string | null;
  label_zh?: string | null;
  value: string;
  value_en?: string | null;
  value_zh?: string | null;
  href: string | null;
  image_path?: string | null;
  description_en?: string | null;
  description_zh?: string | null;
  sort_order: number;
  updated_at: string;
  labelText?: { en: string; zh: string };
  valueText?: { en: string; zh: string };
  descriptionText?: { en: string; zh: string };
}

export interface OtherInformation {
  id: number;
  title: string;
  body: string;
  status: string;
  updated_at: string;
}

export interface ImportantDate {
  id: number;
  phase: string;
  title: string;
  title_en?: string | null;
  title_zh?: string | null;
  body: string;
  body_en?: string | null;
    body_zh?: string | null;
    starts_at: string;
    date_label_en?: string | null;
    date_label_zh?: string | null;
    ends_at: string | null;
  cta_label: string | null;
  cta_label_en?: string | null;
  cta_label_zh?: string | null;
  cta_url: string | null;
  sort_order: number;
  updated_at: string;
  // Computed
  status?: "upcoming" | "live" | "closed";
    titleText?: { en: string; zh: string };
    dateLabelText?: { en: string; zh: string };
    bodyText?: { en: string; zh: string };
  ctaLabelText?: { en: string; zh: string };
}

export interface Dataset {
  id: number;
  slug: string;
  name: string;
  description: string;
  task_count: number | null;
  modality: string | null;
  status: string;
  updated_at: string;
  // Joined from dataset_versions (latest)
  version_label?: string;
  release_date?: string;
  download_url?: string;
  checksum?: string;
  version_notes?: string;
}

export interface DatasetVersion {
  id: number;
  dataset_id: number;
  version_label: string;
  release_date: string | null;
  download_url: string | null;
  checksum: string | null;
  notes: string | null;
  is_latest: number;
  created_at: string;
}

export interface UploadRequirement {
  id: number;
  title: string;
  title_en?: string | null;
  title_zh?: string | null;
  body: string;
  body_en?: string | null;
  body_zh?: string | null;
  required: number;
  sort_order: number;
  updated_at: string;
  titleText?: { en: string; zh: string };
  bodyText?: { en: string; zh: string };
}

export interface SubmissionFileType {
  id: number;
  code: string;
  label: string;
  label_en?: string | null;
  label_zh?: string | null;
  description: string | null;
  description_en?: string | null;
  description_zh?: string | null;
  accepted_extensions: string | null;
  required: number;
  updated_at: string;
  labelText?: { en: string; zh: string };
  descriptionText?: { en: string; zh: string };
}

export interface Announcement {
  id: number;
  title: string;
  body: string;
  severity: string;
  published_at: string;
  updated_at: string;
}

export interface AcademicReference {
  id: number;
  title: string;
  title_en?: string | null;
  title_zh?: string | null;
  body: string;
  body_en?: string | null;
  body_zh?: string | null;
  url: string | null;
  tags_json: string | null;
  tags?: string[];
  sort_order: number;
  updated_at: string;
  titleText?: { en: string; zh: string };
  bodyText?: { en: string; zh: string };
}

export interface MetricExplanation {
  id: number;
  metric_code: string;
  short_label: string;
  explanation: string;
  updated_at: string;
}

// --- Competition tables ---

export interface Team {
  id: number;
  slug: string;
  name: string;
  participant_email: string;
  affiliation: string | null;
  country_region: string | null;
  strengths: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface Model {
  id: number;
  team_id: number;
  slug: string;
  name: string;
  model_card_url: string | null;
  brief_introduction?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Submission {
  id: number;
  model_id: number;
  version_label: string;
  submitted_at: string;
  status: string;
  dataset_split: string | null;
  artifact_uri: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface Metric {
  id: number;
  code: string;
  display_name: string;
  display_name_en?: string | null;
  display_name_zh?: string | null;
  short_label_en?: string | null;
  short_label_zh?: string | null;
  category: string;
  direction: string;
  unit: string | null;
  description: string | null;
  description_en?: string | null;
  description_zh?: string | null;
  sort_order: number;
  updated_at: string;
  displayNameText?: { en: string; zh: string };
  shortLabelText?: { en: string; zh: string };
  descriptionText?: { en: string; zh: string };
}

export interface ScoreRecord {
  id: number;
  submission_id: number;
  metric_id: number;
  raw_value: number | null;
  normalized_value: number | null;
  percentile: number | null;
  evaluation_version: string;
  source_note: string | null;
  recorded_at: string;
}

export interface LeaderboardSnapshot {
  id: number;
  label: string;
  snapshot_time: string;
  status: string;
  ranking_policy: string;
  notes: string | null;
  is_latest: number;
  created_at: string;
}

export interface LeaderboardSnapshotEntry {
  id: number;
  snapshot_id: number;
  rank: number;
  submission_id: number;
  score_record_id: number;
  status_label: string | null;
  updated_label: string | null;
}

// --- Composite / API response types ---

export interface MetricScore {
  code: string;
  displayName: string;
  displayNameText?: { en: string; zh: string };
  shortLabelText?: { en: string; zh: string };
  category: string;
  rawValue: number | null;
  normalizedValue: number | null;
  percentile: number | null;
  recordedAt: string;
}

export interface LeaderboardEntry {
  rank: number;
  statusLabel: string | null;
  updatedLabel: string | null;
  model: {
    id: number;
    slug: string;
    name: string;
  };
  submission: {
    id: number;
    versionLabel: string;
    status: string;
    datasetSplit: string | null;
    submittedAt: string;
  };
  score: {
    rawValue: number | null;
    normalizedValue: number | null;
    percentile: number | null;
  };
  metrics: Record<string, MetricScore>;
}

export interface RadarEntry {
  rank: number;
  model: { name: string; slug: string };
  score: { percentile: number | null };
  axes: Array<{ code: string; label: string; value: number | null }>;
}

export interface PageAuthor {
  id: number;
  name: string;
  name_en: string | null;
  name_zh: string | null;
  url: string | null;
  affiliation_refs: string | null;
  sort_order: number;
  updated_at: string;
  nameText?: { en: string; zh: string };
}

export interface PageAffiliation {
  id: number;
  ref: string;
  name: string;
  name_en: string | null;
  name_zh: string | null;
  logo_path?: string | null;
  website_url?: string | null;
  sort_order: number;
  updated_at: string;
  nameText?: { en: string; zh: string };
}

export interface TriWorldCitation {
  id: number;
  lead_en: string;
  lead_zh: string;
  bibtex: string;
  updated_at: string;
}

export interface TriWorldVisualMetric {
  id: number;
  metric_code: string;
  label_en: string;
  label_zh: string;
  title_en: string;
  title_zh: string;
  sort_order: number;
  updated_at: string;
}

// Site section text (database-driven unique section content)
export interface SiteSectionText {
  id: number;
  site_id: string;
  section_key: string;
  title: string;
  description: string;
  items_json: string;
  updated_at: string;
}

// Legacy — keep for backward compatibility with existing API routes
export interface SiteSection {
  id: number;
  site_id: string;
  section_key: string;
  section_data_json: string;
  updated_at: string;
}

// Parsed site section (items_json already parsed)
export interface ParsedSiteSection {
  id: number;
  siteId: string;
  sectionKey: string;
  title: string;
  description: string;
  items: Record<string, unknown>[];
}
