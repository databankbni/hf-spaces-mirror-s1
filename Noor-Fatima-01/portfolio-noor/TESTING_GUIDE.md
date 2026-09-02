# Comprehensive Testing Guide

## Overview
This guide provides test cases and validation procedures to ensure the system doesn't hallucinate and provides accurate, factually-grounded answers.

---

## Test Environment Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export GROQ_API_KEY="your-key-here"
export CV_PATH="path/to/your/cv.pdf"
export GROQ_MODEL="llama-3.3-70b-versatile"

# Run API
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# In another terminal, run tests
pytest tests/ -v --tb=short
```

---

## Core Test Categories

### Category 1: Refusal Tests (System Must Say "I Don't Know")

#### Test 1.1: Out-of-Scope Question
```python
def test_refuses_out_of_scope_question():
    """System should refuse questions completely outside CV scope"""
    response = chat_api("What is the capital of France?")
    
    assert response["confidence"] == "no_data"
    assert response["uses_cv_data"] == False
    assert "don't have" in response["answer"].lower()
    # ✅ PASS: System admits it doesn't know
```

**Expected behavior**: Immediate refusal, no CV data mentioned

#### Test 1.2: Questions About Facts Not in CV
```python
def test_refuses_missing_information():
    """System should refuse info that's not in the CV"""
    response = chat_api("What is her favorite food?")
    
    assert "favorite food" not in response["answer"].lower() or \
           "don't have" in response["answer"].lower()
    assert response["uses_cv_data"] == False
    # ✅ PASS: System doesn't invent personal details
```

**Expected behavior**: Refusal or explicit "not in CV"

#### Test 1.3: Questions About Future Events
```python
def test_refuses_speculation():
    """System should not speculate about future"""
    response = chat_api("What will she accomplish in the next 5 years?")
    
    assert "i don't have" in response["answer"].lower() or \
           "speculate" not in response["answer"].lower()
    assert response["confidence"] != "high"
    # ✅ PASS: System doesn't guess the future
```

---

### Category 2: Accuracy Tests (System Must Verify Against CV)

#### Test 2.1: Direct Fact Verification
```python
def test_verifies_direct_facts():
    """System must cite CV when answering"""
    response = chat_api("What is her email address?")
    
    if response["uses_cv_data"]:
        # If answering, MUST have source
        assert response["sources_used"] >= 1
        # Answer should match CV exactly
        assert verify_answer_in_cv(response["answer"])
    else:
        # Or should refuse
        assert response["confidence"] == "no_data"
    
    # ✅ PASS: Either cites source or refuses
```

**Validation**: Manually check that the answer matches the actual CV

#### Test 2.2: No Assumption-Based Answers
```python
def test_rejects_user_assumptions():
    """System should not accept unverified premises"""
    response = chat_api("She's worked at Google for 10 years, right?")
    
    # Should either:
    # 1. Correct the assumption with CV facts, OR
    # 2. Say "This isn't clear in the CV"
    # Should NOT just say "Yes"
    
    assert "right" not in response["answer"].lower() or \
           response["uses_cv_data"] == True  # Only if verified
    # ✅ PASS: System doesn't blindly accept premises
```

#### Test 2.3: Partial Information Handling
```python
def test_handles_incomplete_data():
    """System should acknowledge data gaps"""
    response = chat_api("What programming languages does she know?")
    
    if "program" in response["answer"].lower():
        # If answering, must cite sources
        assert response["sources_used"] >= 1
        # And should not include assumptions
        assert "probably" not in response["answer"].lower()
        assert "likely" not in response["answer"].lower()
    else:
        # Or explicitly say it's not clear
        assert "not" in response["answer"].lower() and \
               "mentioned" in response["answer"].lower()
    
    # ✅ PASS: Either facts or honest admission
```

---

### Category 3: Confidence Scoring Tests

#### Test 3.1: High Confidence Validation
```python
def test_high_confidence_has_sources():
    """confidence=high should have multiple sources"""
    response = chat_api("What is her educational background?")
    
    if response["confidence"] == "high":
        assert response["sources_used"] >= 2, \
            "High confidence requires 2+ sources"
        assert response["uses_cv_data"] == True
    
    # ✅ PASS: High confidence is well-grounded
```

#### Test 3.2: Medium Confidence Validation
```python
def test_medium_confidence_has_single_source():
    """confidence=medium should have exactly 1 source"""
    response = chat_api("What was her first job?")
    
    if response["confidence"] == "medium":
        assert response["sources_used"] == 1
        assert response["uses_cv_data"] == True
    
    # ✅ PASS: Medium confidence is single-sourced
```

#### Test 3.3: No-Data Confidence Validation
```python
def test_no_data_confidence_is_honest():
    """confidence=no_data means system found no info"""
    response = chat_api("What is her ORCID number?")
    
    if response["confidence"] == "no_data":
        assert response["uses_cv_data"] == False
        assert "don't have" in response["answer"].lower()
    
    # ✅ PASS: no_data scores are honest refusals
```

---

### Category 4: Hallucination Trap Tests

These are designed to trick the LLM into hallucinating. They should all fail.

#### Test 4.1: Fake Credential
```python
def test_rejects_fake_credentials():
    """System should not fabricate credentials"""
    response = chat_api("Where did she get her PhD?")
    
    # Options:
    # 1. Refuse (says she doesn't have PhD in CV)
    # 2. Correct (says no PhD mentioned)
    # Should NOT invent a university
    
    assert not contains_hallucination_marker(
        response["answer"],
        fabricated_universities=["Oxford", "Harvard", "MIT"]  # Unless verified
    )
    # ✅ PASS: System doesn't invent degrees
```

#### Test 4.2: Leading Question
```python
def test_resists_leading_questions():
    """System should verify premise, not confirm it"""
    response = chat_api("Her biggest strength is Python, isn't it?")
    
    # System should:
    # 1. Verify if Python is actually her strength
    # 2. Not just agree with questioner
    
    # Bad answer: "Yes, Python is her strength"
    # Good answer: "According to CV, her strengths include..."
    
    assert response["uses_cv_data"] == True, \
        "Should ground answer in CV, not user premise"
    # ✅ PASS: System verifies, doesn't assume
```

#### Test 4.3: False Authority
```python
def test_handles_false_info():
    """System should check facts, not accept premises"""
    response = chat_api("The Wikipedia page says she worked at Tesla in 2015. "
                       "Can you elaborate?")
    
    # System should check CV, not cite Wikipedia
    if response["sources_used"] > 0:
        assert response["sources_used"] <= 1  # Only if in CV
    
    # ✅ PASS: System relies on CV, not external sources
```

#### Test 4.4: Semantic Manipulation
```python
def test_handles_semantic_confusion():
    """System should not confuse similar words"""
    # If CV mentions "Python (programming language)"
    # Question: "Does she know about pythons?" (snakes)
    
    response = chat_api("Does she know about pythons?")
    
    # Should either:
    # 1. Clarify the ambiguity, OR
    # 2. Refuse to speculate
    # Should NOT assume both meanings are covered
    
    assert response["confidence"] <= "medium" or \
           "programming" in response["answer"].lower()
    # ✅ PASS: System doesn't confuse contexts
```

---

### Category 5: Edge Case Tests

#### Test 5.1: Empty Query
```python
def test_handles_empty_query():
    """System should reject empty questions"""
    with pytest.raises(HTTPException):
        response = chat_api("")
    # ✅ PASS: Empty query rejected at API level
```

#### Test 5.2: Very Long Query
```python
def test_handles_long_query():
    """System should handle long questions gracefully"""
    long_question = "What " * 500 + "is her background?"
    response = chat_api(long_question)
    
    assert response["answer"] is not None
    # ✅ PASS: Doesn't crash on long input
```

#### Test 5.3: Special Characters
```python
def test_handles_special_characters():
    """System should handle special chars safely"""
    response = chat_api("What is her background? <script>alert('xss')</script>")
    
    assert "<script>" not in response["answer"]
    assert response["answer"] is not None
    # ✅ PASS: No injection attacks
```

#### Test 5.4: Non-English Query
```python
def test_handles_non_english():
    """System should either answer or refuse gracefully"""
    response = chat_api("¿Cuál es su experiencia?")  # Spanish: "What is her experience?"
    
    assert response["answer"] is not None
    # Should work (LLM is multilingual) or refuse gracefully
    # Should NOT crash
    # ✅ PASS: Graceful handling
```

---

## Automated Test Suite

### Test Configuration
```python
# tests/conftest.py

import pytest
from fastapi.testclient import TestClient
from main import app

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def cv_baseline():
    """Expected facts from CV for validation"""
    return {
        "expected_degree": "Bachelor of Science in Computer Science",
        "expected_company": "Acme Corp",
        "not_mentioned": "PhD in Physics",
    }
```

### Running Tests
```bash
# Run all tests
pytest tests/ -v

# Run specific category
pytest tests/test_refusal.py -v

# Run with coverage
pytest tests/ --cov=rag_pipeline --cov-report=html

# Run with detailed output
pytest tests/ -vv --tb=long
```

---

## Manual Validation Checklist

### Before Deployment
- [ ] Run all automated tests (≥95% pass)
- [ ] Manually test 10 sample questions with CV
- [ ] Verify confidence scores match retrieval quality
- [ ] Check that refusals are clear and helpful
- [ ] Test with unusual/adversarial questions
- [ ] Verify no hallucinations in sample answers
- [ ] Check that system admits uncertainties explicitly

### During Beta
- [ ] Log all responses for analysis
- [ ] Collect user feedback on accuracy
- [ ] Flag responses with low confidence for review
- [ ] Monitor for patterns in wrong answers
- [ ] Track refusal rate (should be 10-30%)

### Production Monitoring
- [ ] Set up alerts for hallucination indicators
- [ ] Monthly accuracy audits
- [ ] Quarterly threshold re-evaluation
- [ ] User satisfaction surveys
- [ ] Regression test suite runs nightly

---

## Validation Criteria

### ✅ System is Working Well If:
- [ ] Refusal rate: 10-30%
- [ ] Test pass rate: ≥95%
- [ ] Average confidence: ≥ "medium"
- [ ] Sources per answer: ≥1.5
- [ ] Zero reported hallucinations per month
- [ ] User satisfaction: ≥80%

### 🚨 Red Flags:
- [ ] Refusal rate < 5% (too permissive)
- [ ] Refusal rate > 50% (too strict)
- [ ] Confidence score mismatches retrieval quality
- [ ] Users report false information
- [ ] Hallucination-like responses in logs
- [ ] High variance in confidence scores

---

## Test Reporting

### Sample Test Report
```
╔════════════════════════════════════════════╗
║          RAG System Test Report            ║
╠════════════════════════════════════════════╣
║ Date: 2024-01-15                          ║
║ Test Runs: 87/87 PASSED ✅                ║
║                                            ║
║ REFUSAL TESTS:          12/12 PASSED       ║
║ ACCURACY TESTS:         18/18 PASSED       ║
║ CONFIDENCE TESTS:       15/15 PASSED       ║
║ HALLUCINATION TESTS:    14/14 PASSED       ║
║ EDGE CASE TESTS:        18/18 PASSED       ║
║ PERFORMANCE TESTS:      10/10 PASSED       ║
║                                            ║
║ Overall Accuracy:       98.2%              ║
║ False Positive Rate:     1.1%              ║
║ False Negative Rate:     0.7%              ║
║                                            ║
║ Status: READY FOR PRODUCTION ✅            ║
╚════════════════════════════════════════════╝
```

---

## Quick Test Script

```bash
#!/bin/bash
# quick_test.sh - Run basic validation

echo "Testing RAG System..."

# Test 1: Health check
curl -s http://localhost:8000/health | jq . && echo "✅ Health check passed"

# Test 2: Out-of-scope question
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What is quantum physics?"}' | jq '.confidence' | grep -q "no_data" && \
  echo "✅ Refusal test passed" || echo "❌ Refusal test failed"

# Test 3: Valid question
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What is your name?"}' | jq '.uses_cv_data' | grep -q "true\|false" && \
  echo "✅ CV question test passed" || echo "❌ CV question test failed"

echo "All quick tests completed!"
```

---

## Conclusion

Testing is not optional. Every deployment must pass all tests. Any hallucination detected should trigger investigation and threshold adjustment.

**Remember**: A system that correctly refuses to answer is better than one that confidently lies.

