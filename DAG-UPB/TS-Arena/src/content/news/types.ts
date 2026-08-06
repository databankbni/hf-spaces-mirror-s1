/**
 * Frontmatter of a news post, as authored in the external content repo.
 *
 * ```markdown
 * ---
 * title: Ranking switches from Elo to Arena Score
 * date: 2026-07-23
 * summary: One-line teaser shown in the listing.
 * author: TS-Arena Team
 * draft: true
 * ---
 *
 * Body in Markdown…
 * ```
 *
 * `title` and `date` are required; a post missing either is skipped with a
 * build-time warning rather than breaking the build. `draft: true` keeps a
 * post out of the build entirely, so unpublished work can live in the content
 * repo alongside what is live.
 */
export interface NewsPostMetadata {
  /** URL slug — derived from the file name (sans `.md`). */
  slug: string;
  /** Headline shown in the listing and as the page `<h1>`. */
  title: string;
  /** ISO publishing date (YYYY-MM-DD). Drives the listing order. */
  date: string;
  /** Optional one-line teaser for the listing card. */
  summary?: string;
  /** Optional byline. */
  author?: string;
}

export interface NewsPost extends NewsPostMetadata {
  /** Post body rendered from Markdown to HTML. */
  html: string;
}
