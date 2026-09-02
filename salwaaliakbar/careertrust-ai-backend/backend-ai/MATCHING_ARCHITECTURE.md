# Job Matching System - Production Architecture

##  Executive Summary

This document describes a **production-grade, hybrid job matching system** that combines semantic similarity with rule-based constraints to accurately match candidates with job postings.

### Key Improvements Over Naive Embedding Approach

| Problem | Old Approach | New Solution | Impact |
|---------|-------------|--------------|---------|
| **Extra Skills Penalty** | Pure cosine similarity penalizes candidates with more skills than required | Hybrid: Set coverage (60%) + Semantic (30%) + Bonus (10%) | ✅ Qualified candidates no longer penalized |
| **Title Hierarchy** | "AI Engineer" vs "Engineer" treated as dissimilar | Hierarchy detection + specialization boost |  Specializations correctly recognized |
| **Experience Matching** | Embedding "5 years" vs "2 years" semantically | Numeric rule-based matching |  Correct numerical comparison |
| **Over-qualification** | Not distinguished from under-qualification | Separate flags + maintained high scores |  HR can review flight risk |

---

##  System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     MATCHING PIPELINE                        │
│                                                              │
│  Input: User Profile + Job Posting                          │
│         │                                                    │
│         ▼                                                    │
│  ┌──────────────────────────────────────────────┐          │
│  │  1. Skills Matcher (Hybrid)                  │          │
│  │     • Set-based coverage (required skills)   │          │
│  │     • Semantic similarity (handle synonyms)  │          │
│  │     • Bonus for extra relevant skills        │          │
│  │                                              │          │
│  │  Score = 0.6×Coverage + 0.3×Semantic + 0.1×Bonus       │
│  └──────────────────────────────────────────────┘          │
│         │                                                    │
│         ▼                                                    │
│  ┌──────────────────────────────────────────────┐          │
│  │  2. Title Matcher (Semantic + Hierarchy)     │          │
│  │     • Embedding similarity baseline          │          │
│  │     • Hierarchy detection (seniority levels) │          │
│  │     • Specialization awareness               │          │
│  │                                              │          │
│  │  Score = 0.7×Semantic + 0.3×Hierarchy        │          │
│  └──────────────────────────────────────────────┘          │
│         │                                                    │
│         ▼                                                    │
│  ┌──────────────────────────────────────────────┐          │
│  │  3. Experience Matcher (Rule-Based)          │          │
│  │     • Numeric parsing                        │          │
│  │     • Min/max constraint satisfaction        │          │
│  │     • No over-qualification penalty          │          │
│  │                                              │          │
│  │  Score = Rule-based (0-100)                  │          │
│  └──────────────────────────────────────────────┘          │
│         │                                                    │
│         ▼                                                    │
│  ┌──────────────────────────────────────────────┐          │
│  │  4. Summary Matcher (Pure Semantic)          │          │
│  │     • Cosine similarity                      │          │
│  │     • Profile summary <-> Job description    │          │
│  │                                              │          │
│  │  Score = Cosine Similarity × 100             │          │
│  └──────────────────────────────────────────────┘          │
│         │                                                    │
│         ▼                                                    │
│  ┌──────────────────────────────────────────────┐          │
│  │  5. Score Aggregator                         │          │
│  │     Final = 0.45×Skills + 0.25×Summary +     │          │
│  │             0.20×Title + 0.10×Experience     │          │
│  │                                              │          │
│  │     + Confidence Score                       │          │
│  │     + Flags for HR Review                    │          │
│  └──────────────────────────────────────────────┘          │
│         │                                                    │
│         ▼                                                    │
│  Output: Ranked Recommendations + Explainability            │
└─────────────────────────────────────────────────────────────┘
```

---

##  Scoring Methodology

### Component Weights (Final Score)

```
Final Score (0-100) = 
    0.45 × Skills Score +
    0.25 × Summary Score +
    0.20 × Title Score +
    0.10 × Experience Score
```

**Rationale:**
- **Skills (45%)**: Most critical - determines if candidate can do the job
- **Summary (25%)**: Contextual fit and experience relevance  
- **Title (20%)**: Role alignment and career trajectory
- **Experience (10%)**: Threshold gate, less discriminative once minimum met

### 1. Skills Matching (Hybrid Approach)

**Sub-components:**
```
Skills Score = 0.6 × Coverage + 0.3 × Semantic + 0.1 × Bonus
```

#### Coverage Score (60% weight)
- **Direct string matching** (normalized: lowercase, trimmed)
- **Semantic synonym matching** for remaining gaps (similarity > 0.85)
  - Example: "JavaScript" ≈ "JS", "React.js" ≈ "React"
- **Formula**: `(matched_skills / required_skills) × 100`

#### Semantic Score (30% weight)
- Encode full skill lists as text: `", ".join(skills)`
- Compute cosine similarity between embeddings
- Captures overall skill domain alignment

#### Bonus Score (10% weight)
- Extra skills matching optional requirements: up to 50 points
- Generic extra skills: up to 20 points
- **Key**: Extra skills NEVER reduce score

**Example:**

```python
Job Required: ["Python", "Django", "PostgreSQL"]
Job Optional: ["Redis", "Docker"]
Candidate: ["Python", "Django", "PostgreSQL", "Redis", "Docker", "AWS"]

Coverage: 100% (all required present)
Semantic: 95% (high domain alignment)
Bonus: 50% (2/2 optional + extra AWS)

Skills Score = 0.6×100 + 0.3×95 + 0.1×50 = 93.5
```

---

### 2. Title Matching (Semantic + Hierarchy)

**Sub-components:**
```
Title Score = 0.7 × Semantic + 0.3 × Hierarchy Boost
```

#### Semantic Similarity (70% weight)
- Standard embedding-based cosine similarity
- Handles role variations: "Developer" vs "Engineer"

#### Hierarchy Boost (30% weight)
- **Seniority levels**: `['intern', 'junior', 'mid', 'senior', 'lead', 'principal']`
- **Specializations**: `['ai', 'ml', 'cloud', 'devops', 'security', etc.]`

**Logic:**
1. **Specialization detection**: 
   - If candidate title contains job title + domain keywords → +15 boost
   - Example: "Full Stack Engineer" ⊂ "Full Stack AI Engineer" → +15
   
2. **Seniority comparison**:
   - Over-qualified (higher seniority): +10 boost + flag for HR
   - Under-qualified (lower seniority): -20 penalty + flag
   
3. **Word overlap**:
   - High overlap (>70%) with extra specialization → positive signal

**Example:**

```python
Job: "Full Stack Engineer"
Candidate: "Senior Full Stack AI Engineer"

Semantic: 85% (very similar roles)
Hierarchy: +15 (AI specialization) + 10 (senior level) = +25

Title Score = 0.7×85 + 0.3×25 = 67
```

---

### 3. Experience Matching (Rule-Based)

**NOT embedding-based** - this is a numerical constraint problem.

#### Scoring Logic

```python
if candidate_years < min_required:
    score = max(0, 100 - (gap × 20))  # -20 per year short
    
elif max_required and candidate_years > max_required:
    excess = candidate_years - max_required
    score = max(85, 100 - (excess × 2))  # Minimal penalty
    
else:  # Within range
    score = 100
```

**Key Principles:**
-  Meeting minimum → 100 points
-  Under-qualified → proportional penalty
-  Over-qualified → maintain 85-100 (NO hard penalty)
-  Flag extreme over-qualification for HR review (flight risk)

**Example:**

```python
Job: 2-5 years required
Candidate: 7 years

Meets minimum:  Yes
Within range:  No (2 years over max)
Score: max(85, 100 - 2×2) = 96
Flag: "Potentially over-qualified (review for flight risk)"
```

---

### 4. Summary Matching (Pure Semantic)

**This is the ONE place where pure embeddings are correct.**

- Free-form text: professional summary vs job description
- Semantic alignment captures intent, domain, and experience relevance
- No rule-based logic needed

```python
summary_vec = model.encode(candidate_summary)
description_vec = model.encode(job_description)
score = cosine_similarity(summary_vec, description_vec) × 100
```

---

## 🔍 When to Use Embeddings vs Rules

| Dimension | Strategy | Rationale |
|-----------|----------|-----------|
| **Skills** | Hybrid (Set + Semantic) | Required skills = hard constraints; synonyms = semantic |
| **Title** | Hybrid (Semantic + Hierarchy) | Base similarity + seniority/specialization rules |
| **Experience** | **Rule-Based ONLY** | Numeric comparison, not semantic |
| **Summary** | **Semantic ONLY** | Free-form text, intent matching |

###  When NOT to Use Embeddings

1. **Numeric constraints**: Experience, salary ranges, dates
2. **Exact matches**: Required certifications, legal requirements
3. **Hierarchies**: Seniority levels (use rule-based ordering)
4. **Set operations**: Required vs optional (use set logic)

###  When TO Use Embeddings

1. **Synonyms**: "JS" ≈ "JavaScript", "ML" ≈ "Machine Learning"
2. **Free text**: Summaries, descriptions, cover letters
3. **Domain alignment**: Overall skill relevance, background fit
4. **Semantic intent**: Job goals vs career aspirations

---

##  API Usage

### Request Format

```json
{
  "user": {
    "skills": ["Python", "Django", "React", "AWS"],
    "headline": "Senior Full Stack Engineer",
    "summary": "10 years building scalable web applications...",
    "totalExperience": 10.0
  },
  "jobs": [
    {
      "id": "job_123",
      "title": "Full Stack Engineer",
      "description": "We're looking for an experienced engineer...",
      "requiredSkills": ["Python", "Django"],
      "optionalSkills": ["React", "Docker"],
      "minExperience": 3.0,
      "maxExperience": 8.0
    }
  ]
}
```

### Response Format

```json
{
  "recommendations": [
    {
      "job_id": "job_123",
      "score": 87.5,
      "confidence": 85.0,
      "breakdown": {
        "skills": {
          "score": 93.5,
          "coverage": 100.0,
          "semantic": 95.0,
          "bonus": 50.0,
          "missing_skills": [],
          "extra_skills": ["AWS"]
        },
        "title": {
          "score": 67.0,
          "semantic": 85.0,
          "hierarchy_boost": 25.0,
          "is_overqualified": true
        },
        "experience": {
          "score": 96.0,
          "meets_minimum": true,
          "within_range": false,
          "years_difference": 7.0
        },
        "summary": {
          "score": 78.0,
          "semantic": 78.0
        }
      },
      "flags": [
        "Potentially over-qualified (review for flight risk)"
      ]
    }
  ],
  "metadata": {
    "total_jobs": 1,
    "user_experience_years": 10.0,
    "matching_strategy": "hybrid_semantic_rules_v1"
  }
}
```

---

## 🎓 Advanced Improvements (Future Roadmap)

### 1. Skill Graphs / Ontologies

**Problem**: "React" and "Vue.js" are both frontend frameworks but treated independently.

**Solution**: 
- Build skill taxonomy/graph
- Group related skills: `Frontend → [React, Vue, Angular]`
- Allow partial matching: "Looking for React" + "Candidate has Vue" = 70% match

**Implementation**:
```python
skill_graph = {
    "Frontend Framework": ["React", "Vue", "Angular", "Svelte"],
    "Backend Framework": ["Django", "Flask", "FastAPI", "Express"],
    "Cloud Platform": ["AWS", "Azure", "GCP"]
}

def get_skill_category(skill):
    for category, skills in skill_graph.items():
        if skill in skills:
            return category
    return None

# Compute cross-category matching
if get_skill_category("React") == get_skill_category("Vue"):
    similarity_boost = 0.7  # Same category
```

**Data Sources**:
- ESCO (European Skills/Competences/Occupations)
- O*NET (US Occupational Network)
- Custom industry ontologies

---

### 2. LLM-Based Normalization

**Problem**: "10 years experience in full-stack development" vs "Full Stack Developer with 10 YOE"

**Solution**: Use LLM to normalize unstructured data into structured format.

**Example**:
```python
import openai

def normalize_profile(raw_text):
    prompt = f"""
    Extract structured data from this job seeker profile:
    
    {raw_text}
    
    Return JSON:
    {{
        "skills": [...],
        "years_experience": float,
        "title": str,
        "seniority": str
    }}
    """
    
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    
    return json.loads(response.choices[0].message.content)
```

**Benefits**:
- Handle resume parsing errors
- Standardize free-form text
- Extract implicit information

---

### 3. Hybrid Semantic + Rule-Based Ranking

**Current**: Single final score

**Enhanced**: Multi-stage filtering + ranking

```
Stage 1: Hard Filters (Rule-Based)
  - Must meet minimum experience
  - Must have 60%+ required skills
  - Location constraints
  ↓
Stage 2: Semantic Ranking
  - Embedding-based similarity
  - Domain alignment
  ↓
Stage 3: Re-ranking
  - Business rules (diversity, tenure, etc.)
  - Personalization (user preferences)
  ↓
Stage 4: Explainability
  - Generate natural language explanation
  - Highlight matching points
```

**Implementation**:
```python
def multi_stage_ranking(candidates, job):
    # Stage 1: Hard filters
    filtered = [c for c in candidates if meets_hard_constraints(c, job)]
    
    # Stage 2: Semantic scoring
    scored = [(c, semantic_match(c, job)) for c in filtered]
    
    # Stage 3: Re-ranking
    reranked = apply_business_rules(scored)
    
    # Stage 4: Explain
    explanations = [generate_explanation(c, job) for c, score in reranked]
    
    return reranked, explanations
```

---

### 4. Learning-to-Rank (LTR) with User Feedback

**Problem**: Fixed weights may not reflect real hiring outcomes.

**Solution**: Learn optimal weights from historical data.

**Data Collection**:
```python
feedback_data = [
    {
        "candidate": {...},
        "job": {...},
        "features": {
            "skills_score": 85,
            "title_score": 70,
            "exp_score": 90,
            "summary_score": 75
        },
        "outcome": 1  # 1 = hired, 0 = not hired
    }
]
```

**Training**:
```python
from sklearn.ensemble import GradientBoostingClassifier

X = [f["features"] for f in feedback_data]
y = [f["outcome"] for f in feedback_data]

model = GradientBoostingClassifier()
model.fit(X, y)

# Use model to predict hire probability
hire_prob = model.predict_proba(new_features)
```

**Benefits**:
- Optimize for actual hiring outcomes
- Adapt to company-specific preferences
- Identify which features matter most

---

### 5. Contextualized Embeddings (Domain-Specific)

**Problem**: Generic embeddings may not capture domain nuances.

**Solution**: Fine-tune embeddings on job-specific data.

**Example**:
```python
from sentence_transformers import SentenceTransformer, InputExample, losses
from torch.utils.data import DataLoader

# Create training pairs
train_examples = [
    InputExample(texts=["Python", "Python programming"], label=1.0),
    InputExample(texts=["Python", "Snake"], label=0.0),
    InputExample(texts=["React", "React.js"], label=1.0),
    # ... thousands more from job postings
]

# Fine-tune model
model = SentenceTransformer("all-MiniLM-L6-v2")
train_dataloader = DataLoader(train_examples, shuffle=True, batch_size=16)
train_loss = losses.CosineSimilarityLoss(model)

model.fit(
    train_objectives=[(train_dataloader, train_loss)],
    epochs=10
)
```

**Data Sources**:
- Historical job postings + applications
- Accepted/rejected candidates
- Industry-specific skill taxonomies

---

## 🔬 Testing & Validation

### Unit Tests

```python
def test_skills_matcher_extra_skills():
    """Extra skills should NOT reduce score"""
    matcher = SkillsMatcher(model)
    
    result = matcher.match(
        candidate_skills=["Python", "Django", "React", "AWS", "Docker"],
        job_required_skills=["Python", "Django"],
        job_optional_skills=["React"]
    )
    
    assert result["coverage"] == 100.0
    assert result["bonus"] > 0
    assert result["score"] >= 90  # Should be high match

def test_experience_no_overqualification_penalty():
    """Over-qualified candidates should not be heavily penalized"""
    matcher = ExperienceMatcher()
    
    result = matcher.match(
        candidate_years=10,
        job_min_years=3,
        job_max_years=5
    )
    
    assert result["meets_minimum"] == True
    assert result["score"] >= 85  # Maintain high score
```

### Integration Tests

```python
def test_end_to_end_matching():
    """Full pipeline produces reasonable results"""
    payload = {
        "user": {
            "skills": ["Python", "Django", "React"],
            "headline": "Senior Full Stack Engineer",
            "summary": "10 years experience...",
            "totalExperience": 10
        },
        "jobs": [{
            "id": "job_1",
            "title": "Full Stack Engineer",
            "requiredSkills": ["Python", "Django"],
            "minExperience": 3
        }]
    }
    
    response = recommend(payload)
    
    assert len(response["recommendations"]) == 1
    assert response["recommendations"][0]["score"] >= 80
    assert "breakdown" in response["recommendations"][0]
```

---

## 📈 Performance Considerations

### Computational Complexity

| Component | Time Complexity | Notes |
|-----------|----------------|-------|
| Skills Coverage | O(n×m) | n = candidate skills, m = job skills |
| Semantic Matching | O(1) | Pre-computed embeddings |
| Experience | O(1) | Simple numeric comparison |
| Summary | O(1) | Pre-computed embeddings |
| **Total per job** | **O(n×m)** | Dominated by skills matching |

### Optimization Strategies

1. **Batch Embedding**:
   ```python
   # Instead of encoding one-by-one
   all_skills = user_skills + job_skills
   embeddings = model.encode(all_skills, batch_size=32)
   ```

2. **Caching**:
   ```python
   from functools import lru_cache
   
   @lru_cache(maxsize=10000)
   def get_skill_embedding(skill: str):
       return model.encode(skill)
   ```

3. **Approximate Nearest Neighbor (ANN)**:
   ```python
   import faiss
   
   # Build index for millions of candidates
   index = faiss.IndexFlatL2(embedding_dim)
   index.add(candidate_embeddings)
   
   # Fast search for top-k matches
   distances, indices = index.search(job_embedding, k=100)
   ```

---

## 🎯 Key Takeaways

### ✅ DO's
- ✅ Use **hybrid approaches**: semantic + rule-based
- ✅ Treat **numeric constraints** with rule-based logic
- ✅ **Never penalize** extra qualifications in skills/experience
- ✅ Provide **full explainability** for every score
- ✅ Use **embeddings for synonyms** and free text
- ✅ Implement **hierarchical understanding** for titles

### ❌ DON'Ts
- ❌ Don't use embeddings for numeric comparisons
- ❌ Don't penalize over-qualified candidates
- ❌ Don't treat extra skills as negative signals
- ❌ Don't use simple weighted averages without domain logic
- ❌ Don't ignore skill hierarchy and specializations

---

## 📚 References

- [Sentence Transformers Documentation](https://www.sbert.net/)
- [ESCO - European Skills Taxonomy](https://esco.ec.europa.eu/)
- [O*NET - Occupational Network](https://www.onetonline.org/)
- [Learning to Rank for IR](https://www.microsoft.com/en-us/research/project/mslr/)

---

**Document Version**: 1.0  
**Last Updated**: February 10, 2026  
**Maintained By**: AI/ML Architecture Team
