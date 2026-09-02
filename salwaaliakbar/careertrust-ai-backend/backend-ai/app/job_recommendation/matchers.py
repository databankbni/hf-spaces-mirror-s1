from typing import Dict, List

from .utils import cosine_sim, normalize_skill


class SkillsMatcher:
    """Hybrid skills matching strategy."""

    def __init__(self, model):
        self.model = model

    def match(
        self,
        candidate_skills: List[str],
        job_required_skills: List[str],
        job_optional_skills: List[str] = None,
    ) -> Dict:
        if not job_required_skills:
            return {
                "score": 100.0,
                "coverage": 100.0,
                "semantic": 100.0,
                "bonus": 0.0,
                "missing_skills": [],
                "extra_skills": candidate_skills,
            }

        job_optional_skills = job_optional_skills or []

        candidate_norm = {normalize_skill(s): s for s in candidate_skills}
        required_norm = {normalize_skill(s): s for s in job_required_skills}
        optional_norm = {normalize_skill(s): s for s in job_optional_skills}

        direct_matches = set(candidate_norm.keys()) & set(required_norm.keys())
        missing_required = set(required_norm.keys()) - set(candidate_norm.keys())

        semantically_matched = set()
        if missing_required and candidate_skills:
            for missing in list(missing_required):
                missing_vec = self.model.encode(required_norm[missing])

                for cand_norm, cand_orig in candidate_norm.items():
                    if cand_norm in direct_matches or cand_norm in semantically_matched:
                        continue

                    cand_vec = self.model.encode(cand_orig)
                    sim = cosine_sim(missing_vec, cand_vec)

                    if sim > 0.85:
                        semantically_matched.add(missing)
                        break

        total_matched = len(direct_matches) + len(semantically_matched)
        coverage_score = (total_matched / len(required_norm)) * 100 if required_norm else 100.0

        candidate_text = ", ".join(candidate_skills) if candidate_skills else "none"
        required_text = ", ".join(job_required_skills)

        candidate_vec = self.model.encode(candidate_text)
        required_vec = self.model.encode(required_text)

        semantic_score = cosine_sim(candidate_vec, required_vec) * 100

        extra_skills = set(candidate_norm.keys()) - set(required_norm.keys())

        bonus_score = 0.0
        if extra_skills:
            optional_matches = extra_skills & set(optional_norm.keys())
            bonus_score = min((len(optional_matches) / max(len(optional_norm), 1)) * 100, 50.0)

            if not job_optional_skills:
                bonus_score = min(len(extra_skills) * 2, 20.0)

        final_score = 0.60 * coverage_score + 0.30 * semantic_score + 0.10 * bonus_score

        return {
            "score": round(final_score, 2),
            "coverage": round(coverage_score, 2),
            "semantic": round(semantic_score, 2),
            "bonus": round(bonus_score, 2),
            "missing_skills": [required_norm[s] for s in (missing_required - semantically_matched)],
            "extra_skills": [candidate_norm[s] for s in extra_skills],
        }


class TitleMatcher:
    """Job title matching with hierarchy awareness."""

    def __init__(self, model):
        self.model = model

        self.seniority_levels = [
            "intern",
            "junior",
            "mid",
            "senior",
            "lead",
            "principal",
            "staff",
            "architect",
        ]
        self.specializations = [
            "ai",
            "ml",
            "data",
            "cloud",
            "devops",
            "security",
            "mobile",
            "frontend",
            "backend",
            "fullstack",
            "full stack",
        ]

    def match(self, candidate_title: str, job_title: str) -> Dict:
        if not job_title or not candidate_title:
            return {
                "score": 0.0,
                "semantic": 0.0,
                "hierarchy_boost": 0.0,
                "is_overqualified": False,
                "is_underqualified": False,
            }

        cand_vec = self.model.encode(candidate_title)
        job_vec = self.model.encode(job_title)
        semantic_score = cosine_sim(cand_vec, job_vec) * 100

        cand_lower = candidate_title.lower()
        job_lower = job_title.lower()

        hierarchy_boost = 0.0
        is_overqualified = False
        is_underqualified = False

        cand_seniority = [s for s in self.seniority_levels if s in cand_lower]
        job_seniority = [s for s in self.seniority_levels if s in job_lower]

        job_core_words = set(job_lower.split())
        cand_core_words = set(cand_lower.split())

        overlap = job_core_words & cand_core_words
        overlap_ratio = len(overlap) / len(job_core_words) if job_core_words else 0

        if overlap_ratio > 0.7:
            extra_words = cand_core_words - job_core_words
            if any(spec in " ".join(extra_words) for spec in self.specializations):
                hierarchy_boost = 15.0

        if cand_seniority and job_seniority:
            cand_level = self.seniority_levels.index(cand_seniority[0])
            job_level = self.seniority_levels.index(job_seniority[0])

            if cand_level > job_level:
                is_overqualified = True
                hierarchy_boost = max(hierarchy_boost, 10.0)
            elif cand_level < job_level:
                is_underqualified = True
                hierarchy_boost = -20.0

        final_score = min(max(0.70 * semantic_score + 0.30 * hierarchy_boost, 0), 100)

        return {
            "score": round(final_score, 2),
            "semantic": round(semantic_score, 2),
            "hierarchy_boost": round(hierarchy_boost, 2),
            "is_overqualified": is_overqualified,
            "is_underqualified": is_underqualified,
        }


class ExperienceMatcher:
    """Numeric experience matching (NOT embedding-based)."""

    def match(
        self,
        candidate_years: float,
        job_min_years: float = None,
        job_max_years: float = None,
    ) -> Dict:
        if job_min_years is None:
            return {
                "score": 100.0,
                "meets_minimum": True,
                "within_range": True,
                "years_difference": 0.0,
            }

        meets_minimum = candidate_years >= job_min_years
        years_diff = candidate_years - job_min_years

        if candidate_years < job_min_years:
            gap = job_min_years - candidate_years
            score = max(0, 100 - (gap * 20))
        elif job_max_years and candidate_years > job_max_years:
            excess = candidate_years - job_max_years
            score = max(85, 100 - (excess * 2))
        else:
            score = 100.0

        within_range = candidate_years >= job_min_years and (
            job_max_years is None or candidate_years <= job_max_years + 3
        )

        return {
            "score": round(score, 2),
            "meets_minimum": meets_minimum,
            "within_range": within_range,
            "years_difference": round(years_diff, 2),
        }


class SummaryMatcher:
    """Professional summary vs job description semantic matching."""

    def __init__(self, model):
        self.model = model

    def match(self, candidate_summary: str, job_description: str) -> Dict:
        if not job_description or not candidate_summary:
            return {
                "score": 50.0,
                "semantic": 50.0,
            }

        cand_vec = self.model.encode(candidate_summary)
        job_vec = self.model.encode(job_description)

        semantic_score = cosine_sim(cand_vec, job_vec) * 100

        return {
            "score": round(semantic_score, 2),
            "semantic": round(semantic_score, 2),
        }
