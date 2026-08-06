// Canonical book names (KJV order, as the corpus uses them) + helpers shared
// across autocomplete, scope filtering, and verse permalinks.

export const BOOKS = [
  "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua",
  "Judges", "Ruth", "I Samuel", "II Samuel", "I Kings", "II Kings",
  "I Chronicles", "II Chronicles", "Ezra", "Nehemiah", "Esther", "Job",
  "Psalms", "Proverbs", "Ecclesiastes", "Song of Solomon", "Isaiah",
  "Jeremiah", "Lamentations", "Ezekiel", "Daniel", "Hosea", "Joel", "Amos",
  "Obadiah", "Jonah", "Micah", "Nahum", "Habakkuk", "Zephaniah", "Haggai",
  "Zechariah", "Malachi", "Matthew", "Mark", "Luke", "John", "Acts", "Romans",
  "I Corinthians", "II Corinthians", "Galatians", "Ephesians", "Philippians",
  "Colossians", "I Thessalonians", "II Thessalonians", "I Timothy",
  "II Timothy", "Titus", "Philemon", "Hebrews", "James", "I Peter", "II Peter",
  "I John", "II John", "III John", "Jude", "Revelation",
];

export interface Scope {
  id: string;
  label: string;
}

export const SCOPES: Scope[] = [
  { id: "all", label: "Whole Bible" },
  { id: "ot", label: "Old Testament" },
  { id: "nt", label: "New Testament" },
  { id: "torah", label: "Torah" },
  { id: "history", label: "History" },
  { id: "wisdom", label: "Wisdom" },
  { id: "prophets", label: "Prophets" },
  { id: "gospels", label: "Gospels" },
  { id: "epistles", label: "Epistles" },
];

export const EXAMPLES = [
  "John 3:16",
  "the lord is my shepherd",
  "verses about hope",
  "first Corinthians 13",
  "be still and know",
];

// "John 3:16" <-> "john-3-16" for shareable permalink URLs.
export function refToSlug(ref: string): string {
  return ref
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/:/g, "-")
    .replace(/[^a-z0-9-]/g, "");
}

// Split a verse into parts, marking which words overlap the query (for
// match highlighting). Returns [{text, hit}].
export function highlightParts(
  text: string,
  query: string,
): { text: string; hit: boolean }[] {
  const stop = new Set([
    "the", "and", "of", "to", "a", "in", "that", "is", "for", "i", "he",
    "his", "him", "with", "be", "as", "thy", "thou", "shall", "unto", "not",
  ]);
  const terms = new Set(
    (query || "")
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, " ")
      .split(/\s+/)
      .filter((w) => w.length > 2 && !stop.has(w)),
  );
  if (terms.size === 0) return [{ text, hit: false }];
  return text.split(/(\s+)/).map((tok) => {
    const clean = tok.toLowerCase().replace(/[^a-z0-9]/g, "");
    return { text: tok, hit: clean.length > 0 && terms.has(clean) };
  });
}
