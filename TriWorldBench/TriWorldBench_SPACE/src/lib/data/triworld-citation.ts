import { getDb } from "@/lib/db";
import { get } from "@/lib/db/helpers";
import type { TriWorldCitation } from "@/lib/db/schema";
import { contentValue } from "@/lib/i18n";

const FALLBACK_CITATION: TriWorldCitation = {
  id: 1,
  lead_en: "If you use TriWorldBench in your research, please cite the benchmark:",
  lead_zh: "如果 TriWorldBench 对您的研究有所帮助，请引用本基准：",
  bibtex: `@misc{triworldbench2026,
  title  = {TriWorldBench: Multi-View World Model Video Evaluation},
  author = {TriWorldBench Contributors},
  year   = {2026},
  note   = {Benchmark website}
}`,
  updated_at: "",
};

export function getTriWorldCitation(): TriWorldCitation {
  try {
    const citation = (
      get<TriWorldCitation>(getDb().prepare("SELECT * FROM triworld_citation WHERE id = 1")) ||
      FALLBACK_CITATION
    );
    return {
      ...citation,
      lead_en: contentValue(citation.lead_en),
      lead_zh: contentValue(citation.lead_zh),
      bibtex: contentValue(citation.bibtex),
    };
  } catch {
    return FALLBACK_CITATION;
  }
}
