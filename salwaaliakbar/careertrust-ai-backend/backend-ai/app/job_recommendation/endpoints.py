from typing import Dict

from fastapi import APIRouter, Depends

from app.config import require_api_key
from .aggregator import ScoreAggregator
from .matchers import ExperienceMatcher, SkillsMatcher, SummaryMatcher, TitleMatcher
from .model import get_model
from .utils import parse_experience

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.post("/recommend")
def recommend(payload: Dict):
    model = get_model()

    skills_matcher = SkillsMatcher(model)
    title_matcher = TitleMatcher(model)
    experience_matcher = ExperienceMatcher()
    summary_matcher = SummaryMatcher(model)

    user = payload.get("user", {})
    jobs = payload.get("jobs", [])

    user_skills = user.get("skills", [])
    user_title = user.get("headline", "")
    user_summary = user.get("summary", "")
    user_experience = user.get("totalExperience", 0)

    if isinstance(user_experience, str):
        user_experience = parse_experience(user_experience) or 0

    recommendations = []

    for job in jobs:
        job_id = job.get("id", "unknown")
        job_title = job.get("title", "")
        job_description = job.get("description", "")

        job_all_skills = job.get("skills", [])
        job_required_skills = job.get("requiredSkills", job_all_skills)
        job_optional_skills = job.get("optionalSkills", [])

        job_min_exp = job.get("minExperience")
        job_max_exp = job.get("maxExperience")

        if isinstance(job_min_exp, str):
            job_min_exp = parse_experience(job_min_exp)
        if isinstance(job_max_exp, str):
            job_max_exp = parse_experience(job_max_exp)

        skills_result = skills_matcher.match(
            user_skills,
            job_required_skills,
            job_optional_skills,
        )

        title_result = title_matcher.match(user_title, job_title)

        experience_result = experience_matcher.match(
            user_experience,
            job_min_exp,
            job_max_exp,
        )

        summary_result = summary_matcher.match(user_summary, job_description)

        aggregated = ScoreAggregator.aggregate(
            skills_result,
            title_result,
            experience_result,
            summary_result,
        )

        recommendations.append(
            {
                "job_id": job_id,
                "score": aggregated["final_score"],
                "confidence": aggregated["confidence"],
                "breakdown": aggregated["breakdown"],
                "flags": aggregated["flags"],
            }
        )

    recommendations.sort(key=lambda x: x["score"], reverse=True)

    return {
        "recommendations": recommendations,
        "metadata": {
            "total_jobs": len(jobs),
            "user_experience_years": user_experience,
            "matching_strategy": "hybrid_semantic_rules_v1",
        },
    }


@router.post("/recommend-for-job")
def recommend_for_job(payload: Dict):
    model = get_model()

    skills_matcher = SkillsMatcher(model)
    title_matcher = TitleMatcher(model)
    experience_matcher = ExperienceMatcher()
    summary_matcher = SummaryMatcher(model)

    job = payload.get("job", {})
    jobseekers = payload.get("jobseekers", [])

    job_id = job.get("id")
    job_title = job.get("title", "")
    job_description = job.get("description", "")
    job_all_skills = job.get("skills", [])
    job_required_skills = job.get("requiredSkills", job_all_skills)
    job_optional_skills = job.get("optionalSkills", [])
    job_min_exp = job.get("minExperience")
    job_max_exp = job.get("maxExperience")

    if isinstance(job_min_exp, str):
        job_min_exp = parse_experience(job_min_exp)
    if isinstance(job_max_exp, str):
        job_max_exp = parse_experience(job_max_exp)

    recommendations = []

    for jobseeker in jobseekers:
        clerk_id = jobseeker.get("clerkId")

        seeker_skills = jobseeker.get("skills", [])
        seeker_title = jobseeker.get("headline", "")
        seeker_summary = jobseeker.get("summary", "")
        seeker_experience = jobseeker.get("totalExperience", 0)

        if isinstance(seeker_experience, str):
            seeker_experience = parse_experience(seeker_experience) or 0

        skills_result = skills_matcher.match(
            seeker_skills,
            job_required_skills,
            job_optional_skills,
        )

        title_result = title_matcher.match(seeker_title, job_title)

        experience_result = experience_matcher.match(
            seeker_experience,
            job_min_exp,
            job_max_exp,
        )

        summary_result = summary_matcher.match(seeker_summary, job_description)

        aggregated = ScoreAggregator.aggregate(
            skills_result,
            title_result,
            experience_result,
            summary_result,
        )

        recommendations.append(
            {
                "clerkId": clerk_id,
                "jobId": job_id,
                "score": aggregated["final_score"],
                "confidence": aggregated["confidence"],
                "breakdown": aggregated["breakdown"],
                "flags": aggregated["flags"],
            }
        )

    recommendations.sort(key=lambda x: x["score"], reverse=True)

    return {
        "recommendations": recommendations,
        "metadata": {
            "total_jobseekers": len(jobseekers),
            "job_id": job_id,
            "job_title": job_title,
            "matching_strategy": "hybrid_semantic_rules_v1",
        },
    }
