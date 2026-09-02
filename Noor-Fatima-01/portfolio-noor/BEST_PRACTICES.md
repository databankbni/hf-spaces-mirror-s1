# Developer Best Practices Guide

## Quick Reference: How to Avoid Hallucinations

### When Adding New Features
✅ **DO**:
- Start with rule-based extraction if patterns are clear
- Use strict relevance thresholds (always test with low thresholds first)
- Return empty results rather than "best effort" results
- Explicitly state data limitations in responses
- Test refusals as rigorously as acceptances
- Use deterministic regex patterns for structured data

❌ **DON'T**:
- Increase temperature above 0.05 without careful consideration
- Add "fuzzy matching" that accepts low-relevance chunks
- Relax system prompt constraints for "better UX"
- Assume missing data can be inferred
- Accept user premises without verification
- Combine data from multiple sources without attribution

### Code Review Checklist

```
[ ] Does new retrieval logic have a relevance threshold?
[ ] Are thresholds justified and tested?
[ ] Will the system return empty results for out-of-scope questions?
[ ] Does the system prompt explicitly forbid the new scenario?
[ ] Are edge cases handled (empty input, null values, etc.)?
[ ] Could a user "trick" the system into hallucinating?
[ ] Is confidence scoring accurate for new answer types?
[ ] Are refusals clear and helpful?
```

### Testing Checklist

For every new feature that generates answers:

1. **Positive Test**: Question with clear CV match
   - Expected: Accurate answer with HIGH confidence
   - Assert: `uses_cv_data == true`

2. **Negative Test**: Out-of-scope question
   - Expected: Explicit refusal with NO_DATA confidence
   - Assert: `uses_cv_data == false`

3. **Edge Case Test**: Ambiguous or trick question
   - Expected: Honest answer about what CV contains
   - Assert: Never accepts user premise without verification

4. **Hallucination Test**: Question designed to bait LLM
   - Example: "She loves C++ right?" (not in CV)
   - Expected: Either refusal or factual correction
   - Assert: Never confirms unverified premise

### Example: Adding a New Rule-Based Extractor

**BAD** (risky):
```python
def extract_random_fact(question: str) -> str | None:
    # Returns a guess if pattern matches loosely
    if "skills" in question.lower():
        return "Based on the CV, she probably knows Python"  # ❌ Hallucination
```

**GOOD** (safe):
```python
def extract_skills(question: str) -> str | None:
    if not any(k in question.lower() for k in ["skill", "knows", "expert", "familiar"]):
        return None
    
    # Extract skills deterministically from CV
    skill_section = self._find_section("Skills")
    if not skill_section:
        return None  # Admit ignorance
    
    # Parse actual skills from section
    skills = self._parse_skills_from_section(skill_section)
    if not skills:
        return "The CV includes a Skills section but specific skills aren't clearly listed."
    
    return f"According to the CV, her skills include: {', '.join(skills)}"
```

---

## Temperature Guidance

### Temperature Settings

| Value | Behavior | Use Case | Risk |
|-------|----------|----------|------|
| 0.0 | Fully deterministic | Safety-critical responses | Can be repetitive |
| 0.05 | Very conservative | ✅ Current setting | Low risk |
| 0.1 | Conservative | Previous setting | Medium risk |
| 0.2+ | Creative/varied | General chat | High hallucination risk |
| 1.0+ | Highly creative | Creative writing | Extreme hallucination risk |

**Decision Tree**:
- CV facts only? → Use 0.05
- Simple reformulation needed? → Use 0.05-0.1
- Multi-step reasoning? → 0.1-0.2 (but verify with tests)
- Creative content? → 0.2+ (after safety review)

---

## System Prompt Best Practices

### Structure

```python
system_prompt = (
    "ROLE: [Clear role description]\n"
    "\nKEY RULES (MANDATORY - FOLLOW STRICTLY):\n"
    "1. [Boundary constraint]\n"
    "2. [Data constraint]\n"
    "3. [Style constraint]\n"
    "\nWHAT TO DO IF [common question]:\n"
    "- [Specific instruction]\n"
)
```

### Never

❌ Say "Be helpful" without defining bounds
❌ Assume the LLM will be honest if you don't explicitly ask
❌ Put constraints in user prompt; put them in system prompt
❌ Use vague language ("try to", "should", "usually")

### Always

✅ Use imperative: "MUST NOT", "NEVER", "ALWAYS"
✅ Provide examples: "If asked about X, say Y"
✅ Set strict boundaries: "Only use provided context"
✅ Encourage refusal: "'I don't know' is acceptable"

---

## Confidence Scoring Rules

```python
CONFIDENCE LOGIC:
├─ Refusal (I don't have...)           → confidence = "no_data",     uses_cv_data = False
├─ Rule-based extraction found         → confidence = "high",        uses_cv_data = True
├─ Multiple chunks (≥2)                → confidence = "high",        uses_cv_data = True
├─ Single chunk (1)                    → confidence = "medium",      uses_cv_data = True
└─ LLM answer without strong context   → confidence = "low",         uses_cv_data = False
```

**Principle**: `confidence` should reflect retrieval quality, not answer eloquence.

---

## Common Pitfalls & How to Avoid Them

### Pitfall 1: "Just Lower the Threshold"
**Problem**: Tempted to lower relevance threshold to answer more questions
```python
MIN_RELEVANCE_THRESHOLD = 0.01  # ❌ Bad idea!
```

**Fix**: Instead, improve the CV data or add better rule-based extraction
```python
MIN_RELEVANCE_THRESHOLD = 0.05  # Keep strict
# Add more rule-based extractors for common questions
```

### Pitfall 2: "The LLM is Smart Enough"
**Problem**: Trusting LLM to refuse hallucinating if not constrained
```python
# ❌ LLM sees ambiguous context and makes best guess anyway
system_prompt = "Answer questions about the CV"
```

**Fix**: Explicitly forbid speculation
```python
# ✅ LLM knows it MUST refuse
system_prompt = (
    "NEVER answer outside the provided context. "
    "If information is missing, say 'I don't have that information.'"
)
```

### Pitfall 3: "Empty Context = Ask the LLM Anyway"
**Problem**: Letting LLM "help" when no context exists
```python
# ❌ LLM hallucinates when context is empty
if len(retrieved_chunks) == 0:
    context = "No context available"  # LLM fills in the gap
```

**Fix**: Return refusal before consulting LLM
```python
# ✅ Refuse immediately
if len(retrieved_chunks) == 0:
    return "I don't have information about that"
```

### Pitfall 4: "One Source is Enough"
**Problem**: Trusting single, possibly noisy chunk
```python
# ❌ Could be coincidental match
retrieved_chunks = [most_similar_chunk]
```

**Fix**: Require multiple sources or apply extra scrutiny
```python
# ✅ Multiple sources = higher confidence
confidence = "high" if len(retrieved_chunks) >= 2 else "medium"
```

### Pitfall 5: "Smooth Over Uncertainty"
**Problem**: Rewording refusals to sound helpful
```python
# ❌ User might think we actually know
answer = "She might have some interests in that area"
```

**Fix**: Be direct about limitations
```python
# ✅ User knows exactly what we can and can't answer
answer = "This isn't mentioned in the CV"
```

---

## Monitoring in Production

### Health Metrics to Track

1. **Refusal Rate**
   ```
   (count of answers with confidence="no_data") / total_queries
   Target: 10-30% (shows system is honest)
   ```

2. **Average Confidence**
   ```
   Mean of confidence scores across all queries
   Target: ≥ "medium" (system has enough data)
   ```

3. **Sources Per Answer**
   ```
   Average of sources_used field
   Target: ≥ 1.5 (system finds supporting evidence)
   ```

4. **CV Data Utilization**
   ```
   Percent of answers with uses_cv_data=true
   Target: ≥ 70% (system isn't just refusing)
   ```

### Red Flags

🚩 **Refusal rate > 50%** → CV is too sparse or questions are out-of-scope
🚩 **Confidence = "high" but sources_used < 2** → Something's wrong with scoring
🚩 **Users report wrong answers** → Hallucination detected; investigate chunk quality
🚩 **All confidence scores = "no_data"** → System might be too strict; review threshold

---

## When Something Goes Wrong

### Symptom: System is Too Strict (High Refusal Rate)

**Diagnosis**:
```python
# Check threshold
MIN_RELEVANCE_THRESHOLD = 0.05  # Is this too high?

# Check CV data
print(f"Total chunks: {pipeline.chunk_count}")  # Too few?
print(f"Average chunk size: {avg_size}")        # Too small?
```

**Treatment**:
1. ✅ Review CV data quality (is it extracting properly?)
2. ✅ Add more rule-based extractors for common questions
3. ⚠️ Consider lowering threshold to 0.03 (not below)
4. ❌ DON'T make it 0.0; that's just random matching

### Symptom: System is Too Permissive (Low Confidence in High-Confidence Answers)

**Diagnosis**:
```python
# Check if confidence scoring is wrong
# or if retrieval is returning too many chunks

for chunk in retrieved_chunks:
    print(f"Relevance: {chunk.relevance_score}")  # Are all > 0.05?
```

**Treatment**:
1. ✅ Fix confidence scoring logic
2. ✅ Reduce `top_k` parameter
3. ✅ Audit system prompt (is it being too lenient?)
4. ❌ DON'T raise temperature

### Symptom: System is Hallucinating

**Diagnosis**:
```
1. Check if user reported false information
2. Get the query that caused it
3. Check what context was retrieved
4. Check what the LLM was told
```

**Treatment**:
1. ✅ Lower temperature
2. ✅ Strengthen system prompt
3. ✅ Raise relevance threshold
4. ✅ Check if this question needs a rule-based extractor
5. ❌ DON'T hide the problem or increase temperature

---

## Deployment Checklist

Before going to production:

```
[ ] All thresholds are documented and justified
[ ] Confidence scoring logic is correct
[ ] System prompt has explicit "NEVER" constraints
[ ] Temperature is ≤ 0.05
[ ] Empty context returns refusal (not LLM response)
[ ] Rule-based extractors cover ≥ 30% of common questions
[ ] Edge cases are tested (empty input, very long input, etc.)
[ ] Users understand confidence levels (documentation clear)
[ ] Monitoring is set up (metrics, alerts, logs)
[ ] Rollback plan exists (how to revert if hallucinations spike)
```

---

## Key Takeaway

**This is not a general-purpose chatbot. This is a CV assistant that must be conservative, accurate, and honest.**

Better to say "I don't know" 10 times than to confidently say something wrong even once.

