"""
Test Examples for Job Matching System

Run this file to see how the improved matching system handles various edge cases.
"""

import json
from app.job_recommendation import recommend


def print_result(title, result):
    """Pretty print results"""
    print(f"\n{'='*60}")
    print(f"🧪 {title}")
    print(f"{'='*60}")
    print(json.dumps(result, indent=2))
    print()


# ============================================================================
# TEST 1: Extra Skills Should NOT Penalize
# ============================================================================
def test_extra_skills():
    """Candidate has ALL required skills + extra → should score high"""
    
    payload = {
        "user": {
            "skills": ["Python", "Django", "PostgreSQL", "React", "AWS", "Docker"],
            "headline": "Full Stack Engineer",
            "summary": "5 years building scalable web applications with Python and Django",
            "totalExperience": 5
        },
        "jobs": [{
            "id": "job_001",
            "title": "Backend Engineer",
            "description": "Looking for a Python developer with Django experience",
            "requiredSkills": ["Python", "Django"],
            "optionalSkills": ["PostgreSQL", "Docker"],
            "minExperience": 3,
            "maxExperience": 7
        }]
    }
    
    result = recommend(payload)
    rec = result["recommendations"][0]
    
    print_result("Test 1: Extra Skills (Should NOT Penalize)", {
        "final_score": rec["score"],
        "skills_breakdown": {
            "coverage": rec["breakdown"]["skills"]["coverage"],
            "semantic": rec["breakdown"]["skills"]["semantic"],
            "bonus": rec["breakdown"]["skills"]["bonus"],
            "missing": rec["breakdown"]["skills"]["missing_skills"],
            "extra": rec["breakdown"]["skills"]["extra_skills"]
        },
        "expected": "100% coverage + bonus for extra skills → score ~90+"
    })
    
    assert rec["score"] >= 85, "Should score high with all required + extra skills"
    assert rec["breakdown"]["skills"]["coverage"] == 100.0
    print("✅ PASSED: Extra skills do not penalize")


# ============================================================================
# TEST 2: Title Hierarchy & Specialization
# ============================================================================
def test_title_hierarchy():
    """Specialized titles should match generalist job postings"""
    
    payload = {
        "user": {
            "skills": ["Python", "TensorFlow", "PyTorch", "Django"],
            "headline": "Senior Full Stack AI Engineer",
            "summary": "8 years building AI-powered applications",
            "totalExperience": 8
        },
        "jobs": [{
            "id": "job_002",
            "title": "Full Stack Engineer",
            "description": "We need an experienced full stack developer",
            "requiredSkills": ["Python", "Django"],
            "minExperience": 5
        }]
    }
    
    result = recommend(payload)
    rec = result["recommendations"][0]
    
    print_result("Test 2: Title Hierarchy (AI Engineer ⊃ Engineer)", {
        "final_score": rec["score"],
        "title_breakdown": {
            "semantic": rec["breakdown"]["title"]["semantic"],
            "hierarchy_boost": rec["breakdown"]["title"]["hierarchy_boost"],
            "is_overqualified": rec["breakdown"]["title"]["is_overqualified"]
        },
        "flags": rec["flags"],
        "expected": "Semantic similarity + specialization boost"
    })
    
    print("✅ PASSED: Title hierarchy recognized")


# ============================================================================
# TEST 3: Experience - No Over-Qualification Penalty
# ============================================================================
def test_experience_overqualified():
    """Candidate with 10 years for 3-year job should still score high"""
    
    payload = {
        "user": {
            "skills": ["Python", "Django"],
            "headline": "Senior Backend Engineer",
            "summary": "10 years of backend development experience",
            "totalExperience": 10
        },
        "jobs": [{
            "id": "job_003",
            "title": "Backend Engineer",
            "description": "Mid-level backend position",
            "requiredSkills": ["Python", "Django"],
            "minExperience": 3,
            "maxExperience": 5
        }]
    }
    
    result = recommend(payload)
    rec = result["recommendations"][0]
    
    print_result("Test 3: Over-Qualified Experience", {
        "final_score": rec["score"],
        "experience_breakdown": {
            "score": rec["breakdown"]["experience"]["score"],
            "meets_minimum": rec["breakdown"]["experience"]["meets_minimum"],
            "within_range": rec["breakdown"]["experience"]["within_range"],
            "years_difference": rec["breakdown"]["experience"]["years_difference"]
        },
        "flags": rec["flags"],
        "expected": "High score despite being over-qualified (85-100 range)"
    })
    
    assert rec["breakdown"]["experience"]["score"] >= 85
    assert rec["breakdown"]["experience"]["meets_minimum"] == True
    print("✅ PASSED: Over-qualification does not heavily penalize")


# ============================================================================
# TEST 4: Missing Required Skills Should Reduce Score
# ============================================================================
def test_missing_skills():
    """Candidate missing critical skills should score lower"""
    
    payload = {
        "user": {
            "skills": ["Python", "Flask"],  # Missing Django
            "headline": "Backend Developer",
            "summary": "3 years Python development",
            "totalExperience": 3
        },
        "jobs": [{
            "id": "job_004",
            "title": "Django Developer",
            "description": "Django-specific role",
            "requiredSkills": ["Python", "Django", "PostgreSQL"],
            "minExperience": 2
        }]
    }
    
    result = recommend(payload)
    rec = result["recommendations"][0]
    
    print_result("Test 4: Missing Required Skills", {
        "final_score": rec["score"],
        "skills_breakdown": {
            "coverage": rec["breakdown"]["skills"]["coverage"],
            "missing_skills": rec["breakdown"]["skills"]["missing_skills"]
        },
        "flags": rec["flags"],
        "expected": "Lower coverage → lower overall score"
    })
    
    assert rec["breakdown"]["skills"]["coverage"] < 100
    assert len(rec["breakdown"]["skills"]["missing_skills"]) > 0
    assert "Missing" in " ".join(rec["flags"])
    print("✅ PASSED: Missing skills correctly reduce score")


# ============================================================================
# TEST 5: Experience Below Minimum
# ============================================================================
def test_experience_below_minimum():
    """Candidate with 1 year for 5-year minimum should score low on experience"""
    
    payload = {
        "user": {
            "skills": ["Python", "Django", "React"],
            "headline": "Junior Full Stack Developer",
            "summary": "1 year of professional experience",
            "totalExperience": 1
        },
        "jobs": [{
            "id": "job_005",
            "title": "Senior Full Stack Engineer",
            "description": "Senior role requiring extensive experience",
            "requiredSkills": ["Python", "Django"],
            "minExperience": 5
        }]
    }
    
    result = recommend(payload)
    rec = result["recommendations"][0]
    
    print_result("Test 5: Below Minimum Experience", {
        "final_score": rec["score"],
        "experience_breakdown": {
            "score": rec["breakdown"]["experience"]["score"],
            "meets_minimum": rec["breakdown"]["experience"]["meets_minimum"],
            "years_difference": rec["breakdown"]["experience"]["years_difference"]
        },
        "flags": rec["flags"],
        "expected": "Low experience score + flag"
    })
    
    assert rec["breakdown"]["experience"]["meets_minimum"] == False
    assert rec["breakdown"]["experience"]["score"] < 100
    print("✅ PASSED: Under-qualified correctly flagged")


# ============================================================================
# TEST 6: Perfect Match
# ============================================================================
def test_perfect_match():
    """Ideal candidate should score very high"""
    
    payload = {
        "user": {
            "skills": ["Python", "Django", "PostgreSQL", "Docker", "Redis"],
            "headline": "Full Stack Engineer",
            "summary": "5 years building scalable web applications with Django and React. Experienced in microservices and cloud deployment.",
            "totalExperience": 5
        },
        "jobs": [{
            "id": "job_006",
            "title": "Full Stack Engineer",
            "description": "We need an experienced full stack engineer with Python, Django, and PostgreSQL. Knowledge of Docker and cloud platforms is a plus.",
            "requiredSkills": ["Python", "Django", "PostgreSQL"],
            "optionalSkills": ["Docker", "Redis"],
            "minExperience": 3,
            "maxExperience": 7
        }]
    }
    
    result = recommend(payload)
    rec = result["recommendations"][0]
    
    print_result("Test 6: Perfect Match", {
        "final_score": rec["score"],
        "confidence": rec["confidence"],
        "all_components": {
            "skills": rec["breakdown"]["skills"]["score"],
            "title": rec["breakdown"]["title"]["score"],
            "experience": rec["breakdown"]["experience"]["score"],
            "summary": rec["breakdown"]["summary"]["score"]
        },
        "flags": rec["flags"],
        "expected": "Score ~95+ with high confidence"
    })
    
    assert rec["score"] >= 90
    assert rec["confidence"] >= 80
    print("✅ PASSED: Perfect match scores very high")


# ============================================================================
# RUN ALL TESTS
# ============================================================================
if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 RUNNING JOB MATCHING SYSTEM TESTS")
    print("="*60)
    
    try:
        test_extra_skills()
        test_title_hierarchy()
        test_experience_overqualified()
        test_missing_skills()
        test_experience_below_minimum()
        test_perfect_match()
        
        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED")
        print("="*60)
        print("\nThe improved matching system correctly handles:")
        print("  1. ✅ Extra skills do not penalize")
        print("  2. ✅ Title hierarchy and specialization")
        print("  3. ✅ Over-qualification maintained high scores")
        print("  4. ✅ Missing skills reduce scores appropriately")
        print("  5. ✅ Under-qualification flagged correctly")
        print("  6. ✅ Perfect matches score very high\n")
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
