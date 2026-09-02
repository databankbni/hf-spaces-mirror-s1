"""
F1InsightAI — Performance Benchmark Script
Runs a set of test queries through the API and measures accuracy metrics.
Usage: python tests/benchmark.py
Requires: App running on localhost:5000
"""

import requests
import json
import time
import sys

API_URL = "http://localhost:5000/api/chat"

# ── Test Cases ────────────────────────────────────────────
# Each test has: question, expected_type, validation keywords/checks
TEST_QUERIES = [
    # --- Driver Stats ---
    {
        "question": "Who has the most race wins in F1 history?",
        "category": "Driver Stats",
        "expect_sql": True,
        "validation": ["hamilton", "105"],
    },
    {
        "question": "How many world championships has Michael Schumacher won?",
        "category": "Driver Stats",
        "expect_sql": True,
        "validation": ["schumacher", "7"],
    },
    {
        "question": "Which driver has the most pole positions?",
        "category": "Driver Stats",
        "expect_sql": True,
        "validation": ["hamilton"],
    },
    {
        "question": "List the top 5 drivers by career points",
        "category": "Driver Stats",
        "expect_sql": True,
        "validation": ["hamilton", "verstappen"],
    },

    # --- Race & Circuit Queries ---
    {
        "question": "How many races were held in 2023?",
        "category": "Race Queries",
        "expect_sql": True,
        "validation": ["22"],
    },
    {
        "question": "Show the race winners at Spa",
        "category": "Race Queries",
        "expect_sql": True,
        "validation": ["schumacher"],
    },
    {
        "question": "Which circuits are located in Italy?",
        "category": "Circuit Queries",
        "expect_sql": True,
        "validation": ["monza"],
    },
    {
        "question": "How many times has the Monaco Grand Prix been held?",
        "category": "Race Queries",
        "expect_sql": True,
        "validation": [],
    },

    # --- Team/Constructor Queries ---
    {
        "question": "Which team has won the most constructors championships?",
        "category": "Team Queries",
        "expect_sql": True,
        "validation": ["ferrari"],
    },
    {
        "question": "How many race wins does Red Bull have?",
        "category": "Team Queries",
        "expect_sql": True,
        "validation": ["red bull"],
    },

    # --- Lap Times & Pit Stops ---
    {
        "question": "What is the average pit stop duration in 2023?",
        "category": "Pit Stops",
        "expect_sql": True,
        "validation": [],
    },
    {
        "question": "What was the fastest lap time at Monza in 2023?",
        "category": "Lap Times",
        "expect_sql": True,
        "validation": [],
    },

    # --- Comparison Queries ---
    {
        "question": "Compare the number of wins between Hamilton and Verstappen",
        "category": "Comparison",
        "expect_sql": True,
        "validation": ["hamilton", "verstappen"],
    },

    # --- Historical Queries ---
    {
        "question": "Who won the first ever F1 race?",
        "category": "Historical",
        "expect_sql": True,
        "validation": ["farina"],
    },
    {
        "question": "How many different drivers have won a race?",
        "category": "Historical",
        "expect_sql": True,
        "validation": [],
    },

    # --- Qualifying ---
    {
        "question": "Who got pole position at the 2023 British Grand Prix?",
        "category": "Qualifying",
        "expect_sql": True,
        "validation": [],
    },

    # --- Sprint Results ---
    {
        "question": "How many sprint races were held in 2023?",
        "category": "Sprint",
        "expect_sql": True,
        "validation": [],
    },

    # --- Conversational (should NOT generate SQL) ---
    {
        "question": "What is DRS in Formula 1?",
        "category": "Conversational",
        "expect_sql": False,
        "validation": ["drag"],
    },
    {
        "question": "Hello, what can you do?",
        "category": "Conversational",
        "expect_sql": False,
        "validation": [],
    },

    # --- Edge Case: Name variations ---
    {
        "question": "Show results of the 2023 Sao Paulo Grand Prix",
        "category": "Edge Case",
        "expect_sql": True,
        "validation": [],
    },
]


def run_benchmark():
    """Run all test queries and collect metrics."""
    print("=" * 70)
    print("  F1InsightAI — Performance Benchmark")
    print(f"  Testing {len(TEST_QUERIES)} queries against {API_URL}")
    print("=" * 70)
    print()

    results = []
    total_time = 0

    for i, test in enumerate(TEST_QUERIES, 1):
        question = test["question"]
        print(f"[{i:2d}/{len(TEST_QUERIES)}] {question}")

        start = time.time()
        try:
            resp = requests.post(API_URL, json={"message": question}, timeout=60)
            elapsed = time.time() - start
            total_time += elapsed

            if resp.status_code != 200:
                print(f"       ❌ HTTP {resp.status_code}")
                results.append({**test, "status": "HTTP_ERROR", "time": elapsed, "retries": 0, "has_results": False})
                continue

            data = resp.json()
            answer = (data.get("answer") or "").lower()
            sql = data.get("sql") or ""
            rows = data.get("results", {}).get("rows", [])
            steps = data.get("steps", [])
            error = data.get("error")

            # Count retries from agent steps
            retries = sum(1 for s in steps if s.get("node") == "retry_sql")

            # Check if SQL was generated when expected
            sql_generated = bool(sql.strip())
            correct_type = (sql_generated == test["expect_sql"])

            # Check if we got results (for SQL queries)
            has_results = len(rows) > 0 if test["expect_sql"] else True

            # Validate expected keywords in the answer
            validation_pass = True
            failed_keywords = []
            for keyword in test["validation"]:
                if keyword.lower() not in answer:
                    validation_pass = False
                    failed_keywords.append(keyword)

            # Determine overall status
            if error and not has_results:
                status = "ERROR"
            elif not correct_type:
                status = "WRONG_TYPE"
            elif not has_results and test["expect_sql"]:
                status = "NO_RESULTS"
            elif not validation_pass:
                status = "VALIDATION_FAIL"
            else:
                status = "PASS"

            status_icon = "✅" if status == "PASS" else "⚠️" if status in ("NO_RESULTS", "VALIDATION_FAIL") else "❌"
            retry_str = f" (retries: {retries})" if retries > 0 else ""
            print(f"       {status_icon} {status} — {elapsed:.2f}s{retry_str}")
            if failed_keywords:
                print(f"          Missing keywords: {failed_keywords}")

            results.append({
                **test,
                "status": status,
                "time": elapsed,
                "retries": retries,
                "has_results": has_results,
                "sql_generated": sql_generated,
            })

        except requests.exceptions.Timeout:
            elapsed = time.time() - start
            print(f"       ❌ TIMEOUT after {elapsed:.1f}s")
            results.append({**test, "status": "TIMEOUT", "time": elapsed, "retries": 0, "has_results": False})

        except Exception as e:
            elapsed = time.time() - start
            print(f"       ❌ ERROR: {e}")
            results.append({**test, "status": "ERROR", "time": elapsed, "retries": 0, "has_results": False})

    # ── Print Summary ─────────────────────────────────────
    print()
    print("=" * 70)
    print("  BENCHMARK RESULTS")
    print("=" * 70)

    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    no_results = sum(1 for r in results if r["status"] == "NO_RESULTS")
    validation_fail = sum(1 for r in results if r["status"] == "VALIDATION_FAIL")
    errors = sum(1 for r in results if r["status"] in ("ERROR", "HTTP_ERROR", "TIMEOUT"))
    wrong_type = sum(1 for r in results if r["status"] == "WRONG_TYPE")

    sql_queries = [r for r in results if r["expect_sql"]]
    sql_passed = sum(1 for r in sql_queries if r["status"] == "PASS")
    sql_with_retries = sum(1 for r in sql_queries if r.get("retries", 0) > 0)
    sql_retry_success = sum(1 for r in sql_queries if r.get("retries", 0) > 0 and r["status"] == "PASS")

    conv_queries = [r for r in results if not r["expect_sql"]]
    conv_passed = sum(1 for r in conv_queries if r["status"] == "PASS")

    avg_time = total_time / total if total > 0 else 0
    times = [r["time"] for r in results]

    print(f"\n  Total Queries:              {total}")
    print(f"  ✅ Passed:                   {passed}/{total} ({100*passed/total:.1f}%)")
    print(f"  ⚠️  No Results:              {no_results}")
    print(f"  ⚠️  Validation Failed:       {validation_fail}")
    print(f"  ❌ Errors/Timeouts:          {errors}")
    print(f"  ❌ Wrong Classification:     {wrong_type}")

    print(f"\n  --- SQL Query Accuracy ---")
    print(f"  SQL Queries Tested:         {len(sql_queries)}")
    print(f"  First-Attempt Accuracy:     {sql_passed}/{len(sql_queries)} ({100*sql_passed/len(sql_queries):.1f}%)")
    print(f"  Queries Needing Retry:      {sql_with_retries}")
    if sql_with_retries > 0:
        print(f"  Retry Success Rate:         {sql_retry_success}/{sql_with_retries} ({100*sql_retry_success/sql_with_retries:.1f}%)")

    print(f"\n  --- Conversational ---")
    print(f"  Conversational Queries:     {len(conv_queries)}")
    print(f"  Correctly Classified:       {conv_passed}/{len(conv_queries)}")

    print(f"\n  --- Response Time ---")
    print(f"  Average:                    {avg_time:.2f}s")
    print(f"  Min:                        {min(times):.2f}s")
    print(f"  Max:                        {max(times):.2f}s")

    print(f"\n  --- By Category ---")
    categories = {}
    for r in results:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = {"total": 0, "passed": 0}
        categories[cat]["total"] += 1
        if r["status"] == "PASS":
            categories[cat]["passed"] += 1

    for cat, stats in sorted(categories.items()):
        pct = 100 * stats["passed"] / stats["total"]
        print(f"  {cat:25s}  {stats['passed']}/{stats['total']} ({pct:.0f}%)")

    print("\n" + "=" * 70)

    # ── Save results to JSON ──────────────────────────────
    output = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_queries": total,
        "overall_accuracy": round(100 * passed / total, 1),
        "sql_accuracy": round(100 * sql_passed / len(sql_queries), 1) if sql_queries else 0,
        "avg_response_time": round(avg_time, 2),
        "min_response_time": round(min(times), 2),
        "max_response_time": round(max(times), 2),
        "retries_needed": sql_with_retries,
        "retry_success_rate": round(100 * sql_retry_success / sql_with_retries, 1) if sql_with_retries > 0 else 100.0,
        "results": [
            {
                "question": r["question"],
                "category": r["category"],
                "status": r["status"],
                "time": round(r["time"], 2),
                "retries": r.get("retries", 0),
            }
            for r in results
        ],
    }

    output_path = "tests/benchmark_results.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Results saved to: {output_path}")
    print()


if __name__ == "__main__":
    run_benchmark()
