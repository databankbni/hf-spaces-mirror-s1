export type Confidence = "high" | "medium" | "low";

export interface Translation {
  version: string;
  language: string;
  languageName: string;
  ref: string;
  text: string;
}

export interface VerseResult {
  rank: number;
  ref: string;
  book_no: number;
  chapter: number;
  verse: number;
  version: string;
  language: string;
  languageName: string;
  text: string;
  score: number;
  relevance: number;
  confidence: Confidence;
  exact: boolean;
  translations: Translation[];
}

export interface PredictResponse {
  transcript: string;
  results: VerseResult[];
  confident: boolean;
  topScore: number;
  error?: string;
}

export interface BibleVersion {
  code: string;
  name: string;
  language: string;
}

export interface BibleLanguage {
  code: string;
  name: string;
}

export interface ChapterVerse {
  verse: number;
  ref: string;
  text: string;
}

export interface ChapterResponse {
  version: string;
  book: string;
  book_no: number;
  chapter: number;
  verses: ChapterVerse[];
  error?: string;
}

export interface AskVerse {
  ref: string;
  text: string;
  book_no: number;
  chapter: number;
  verse: number;
}

export interface AskResponse {
  answer: string | null;
  verses: AskVerse[];
  error: string | null;
}

export interface Topic {
  label: string;
  emoji: string;
  query: string;
}

// A lightweight verse reference (cross-references, similar verses).
export interface VerseRef {
  ref: string;
  version: string;
  text: string;
  book_no: number;
  chapter: number;
  verse: number;
  relevance?: number;
}

export interface TestAccess {
  valid: boolean;
  label: string;
  features: { speak: boolean; type: boolean; ask: boolean; listen: boolean };
}

// Sermon Studio (Speaker plan) — storytelling-arc outline builder with
// linked Bible passages.
export interface SermonVerseLink {
  ref: string;
  version: string;
  text: string;
}

export interface SermonPoint {
  id?: number;
  beat: string;
  title: string;
  notes: string;
  verse_refs: SermonVerseLink[];
}

export interface Sermon {
  id: number;
  user_id: string;
  title: string;
  description: string;
  status: "draft" | "archived";
  created_at: number;
  updated_at: number;
  points: SermonPoint[];
}

// localStorage records
export interface HistoryItem {
  query: string;
  mode: "speak" | "type" | "ask";
  ref?: string;
  at: number;
}

export interface FavoriteItem {
  ref: string;
  version: string;
  text: string;
  at: number;
}
