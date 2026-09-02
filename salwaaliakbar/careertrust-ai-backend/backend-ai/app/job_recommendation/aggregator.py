from typing import Dict


class ScoreAggregator:
    """Combines individual match scores with domain-appropriate weights."""

    WEIGHTS = {
        "skills": 0.45,
        "summary": 0.25,
        "title": 0.20,
        "experience": 0.10,
    }

    @classmethod
    def aggregate(
        cls,
        skills_result: Dict,
        title_result: Dict,
        experience_result: Dict,
        summary_result: Dict,
    ) -> Dict:
        final_score = (
            cls.WEIGHTS["skills"] * skills_result["score"]
            + cls.WEIGHTS["summary"] * summary_result["score"]
            + cls.WEIGHTS["title"] * title_result["score"]
            + cls.WEIGHTS["experience"] * experience_result["score"]
        )

        confidence_factors = []

        if skills_result["coverage"] > 80:
            confidence_factors.append(20)
        elif skills_result["coverage"] > 60:
            confidence_factors.append(10)

        if experience_result["meets_minimum"]:
            confidence_factors.append(15)

        if summary_result["semantic"] > 70:
            confidence_factors.append(15)

        confidence = min(50 + sum(confidence_factors), 100)

        flags = []
        if skills_result["missing_skills"]:
            flags.append(f"Missing {len(skills_result['missing_skills'])} required skills")
        if not experience_result["meets_minimum"]:
            flags.append("Below minimum experience requirement")
        if title_result.get("is_underqualified"):
            flags.append("Title suggests under-qualification")
        if title_result.get("is_overqualified"):
            flags.append("Potentially over-qualified (review for flight risk)")

        return {
            "final_score": round(final_score, 2),
            "confidence": round(confidence, 2),
            "breakdown": {
                "skills": skills_result,
                "title": title_result,
                "experience": experience_result,
                "summary": summary_result,
            },
            "flags": flags,
        }
