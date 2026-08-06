
import os
import sys
import subprocess
import tempfile
import shutil
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gradio as gr
from env.models import parse_agent_output
from server.reward_calculator import DebugRewardCalculator



EXAMPLES = {
    "🔢 Off-by-One: binary_search": {
        "bug_type": "off_by_one",
        "function_name": "binary_search",
        "buggy_code": """\
def binary_search(arr, target):
    left, right = 0, len(arr)
    while left < right:
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1""",
        "original_code": """\
def binary_search(arr, target):
    left, right = 0, len(arr) - 1
    while left <= right:
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1""",
        "test_cases": [
            {"input": [[1, 3, 5, 7, 9], 5], "expected_output": 2},
            {"input": [[1, 3, 5, 7, 9], 1], "expected_output": 0},
            {"input": [[1, 3, 5, 7, 9], 9], "expected_output": 4},
            {"input": [[1, 3, 5, 7, 9], 4], "expected_output": -1},
        ],
        "bug_location": {"function": "binary_search", "line_start": 2},
        "initial_error": "IndexError: list index out of range when target is the last element",
        "agent_turns": [
            """\
OBSERVATION: `right` is initialized to `len(arr)` on line 2, which is one index past the last valid position. The while condition `left < right` (strict less-than) also prevents checking the final candidate when left equals right.
HYPOTHESIS: Python lists are 0-indexed so valid indices run 0 to len(arr)-1. Setting `right = len(arr)` allows `arr[mid]` to access an out-of-bounds index when mid is computed near the boundary, causing IndexError. Additionally, `left < right` skips the element at the final convergence point, causing missed targets. Both bugs need simultaneous correction.
CONFIDENCE: high
ACTION: inspect_lines
DETAIL: 2, 3""",
            """\
OBSERVATION: Two mutations confirmed: (1) `right = len(arr)` should be `right = len(arr) - 1` to stay within bounds; (2) `left < right` should be `left <= right` to check the last remaining element.
HYPOTHESIS: Changing `right = len(arr)` to `right = len(arr) - 1` constrains all mid-point calculations to valid indices. Changing `<` to `<=` ensures the algorithm checks the element when the search window narrows to a single index. Together these two character-level fixes restore correct binary search semantics across all inputs.
CONFIDENCE: high
ACTION: propose_fix
DETAIL: def binary_search(arr, target):
    left, right = 0, len(arr) - 1
    while left <= right:
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1""",
        ],
    },

    "⚙️ Wrong Operator: is_even": {
        "bug_type": "wrong_operator",
        "function_name": "is_even",
        "buggy_code": """\
def is_even(n):
    return n % 2 != 0""",
        "original_code": """\
def is_even(n):
    return n % 2 == 0""",
        "test_cases": [
            {"input": 4, "expected_output": True},
            {"input": 3, "expected_output": False},
            {"input": 0, "expected_output": True},
            {"input": 7, "expected_output": False},
        ],
        "bug_location": {"function": "is_even", "line_start": 2},
        "initial_error": "AssertionError: is_even(4) returned False, expected True",
        "agent_turns": [
            """\
OBSERVATION: The single-expression body `return n % 2 != 0` returns False for n=4 (4%2=0, 0!=0 is False) but True was expected. The modulo operation itself is correct — the comparison operator is wrong.
HYPOTHESIS: A number is even when `n % 2 == 0`. The `!=` operator is the exact negation of `==`, inverting the result for every input: even numbers return False, odd numbers return True. This is a single-character bug — changing `!=` to `==` fixes all four test cases simultaneously.
CONFIDENCE: high
ACTION: inspect_lines
DETAIL: 2""",
            """\
OBSERVATION: `n % 2 != 0` evaluates to True for odd numbers and False for even numbers — the opposite of the function contract. Replacing `!=` with `==` inverts the boolean, restoring correct semantics.
HYPOTHESIS: `n % 2 == 0` correctly returns True for even numbers (remainder zero) and False for odd numbers (remainder one). No other changes are needed. All four test cases will pass after this single operator change.
CONFIDENCE: high
ACTION: propose_fix
DETAIL: def is_even(n):
    return n % 2 == 0""",
        ],
    },

    "🔀 Wrong Condition: is_sorted": {
        "bug_type": "wrong_condition",
        "function_name": "is_sorted",
        "buggy_code": """\
def is_sorted(lst):
    for i in range(len(lst) - 1):
        if lst[i] > lst[i + 1]:
            return True
    return False""",
        "original_code": """\
def is_sorted(lst):
    for i in range(len(lst) - 1):
        if lst[i] > lst[i + 1]:
            return False
    return True""",
        "test_cases": [
            {"input": [[1, 2, 3]], "expected_output": True},
            {"input": [[3, 1, 2]], "expected_output": False},
            {"input": [[1]], "expected_output": True},
            {"input": [[5, 3, 1]], "expected_output": False},
        ],
        "bug_location": {"function": "is_sorted", "line_start": 4},
        "initial_error": "AssertionError: is_sorted([1,2,3]) returned False, expected True",
        "agent_turns": [
            """\
OBSERVATION: `is_sorted([1,2,3])` returns False. The loop finds no element where `lst[i] > lst[i+1]`, falls through to line 5, and returns False. But a fully sorted list should return True. The early-return and fallthrough values are swapped.
HYPOTHESIS: The function's logic is inverted on both return paths. When a violation is found (`lst[i] > lst[i+1]`), the list is NOT sorted — so it should return False, not True. When no violation is found after the full loop, the list IS sorted — so it should return True, not False. Both return values on lines 4 and 5 need to be swapped.
CONFIDENCE: high
ACTION: inspect_lines
DETAIL: 4, 5""",
            """\
OBSERVATION: Lines 4 and 5 return the wrong boolean values. Line 4 (violation found) returns True; line 5 (no violations) returns False. Both are exactly backwards.
HYPOTHESIS: Swapping `return True` → `return False` on line 4 and `return False` → `return True` on line 5 corrects all four test cases. The comparison operator `>` and loop range are both correct — only the return values need fixing.
CONFIDENCE: high
ACTION: propose_fix
DETAIL: def is_sorted(lst):
    for i in range(len(lst) - 1):
        if lst[i] > lst[i + 1]:
            return False
    return True""",
        ],
    },

    "📦 Wrong Accumulation: flatten": {
        "bug_type": "wrong_accumulation",
        "function_name": "flatten",
        "buggy_code": """\
def flatten(lst):
    result = []
    for item in lst:
        if isinstance(item, list):
            result.append(flatten(item))
        else:
            result.append(item)
    return result""",
        "original_code": """\
def flatten(lst):
    result = []
    for item in lst:
        if isinstance(item, list):
            result.extend(flatten(item))
        else:
            result.append(item)
    return result""",
        "test_cases": [
            {"input": [[[1, [2, 3], 4]]], "expected_output": [1, 2, 3, 4]},
            {"input": [[[1, 2]]], "expected_output": [1, 2]},
            {"input": [[[1]]], "expected_output": [1]},
            {"input": [[[]]], "expected_output": []},
        ],
        "bug_location": {"function": "flatten", "line_start": 5},
        "initial_error": "AssertionError: flatten([1,[2,3],4]) returned [1,[2,3],4] not [1,2,3,4]",
        "agent_turns": [
            """\
OBSERVATION: `flatten([1,[2,3],4])` returns `[1, [2, 3], 4]` — the sublist `[2,3]` is present as a nested list instead of being unpacked. The recursive call on line 5 correctly returns `[2, 3]` but then `append` inserts that list as a single element.
HYPOTHESIS: `list.append(x)` adds `x` as one element regardless of type. So `result.append(flatten([2,3]))` inserts `[2,3]` as a nested list. The correct method is `list.extend(x)` which iterates over `x` and adds each element individually. This is a classic Python accumulation pattern error — `append` vs `extend` determines whether the recursion output is nested or merged.
CONFIDENCE: high
ACTION: inspect_lines
DETAIL: 5""",
            """\
OBSERVATION: Line 5 uses `result.append(flatten(item))`. `flatten(item)` returns a flat list (e.g., `[2, 3]`). `append` wraps it as one element. `extend` would unpack it element-by-element into result.
HYPOTHESIS: Replacing `result.append(flatten(item))` with `result.extend(flatten(item))` on line 5 merges the recursively flattened sublist into result without adding nesting. All other lines are correct. This single method name change fixes all four test cases.
CONFIDENCE: high
ACTION: propose_fix
DETAIL: def flatten(lst):
    result = []
    for item in lst:
        if isinstance(item, list):
            result.extend(flatten(item))
        else:
            result.append(item)
    return result""",
        ],
    },

    "↩️ Missing Return: fibonacci": {
        "bug_type": "missing_return",
        "function_name": "fibonacci",
        "buggy_code": """\
def fibonacci(n):
    if n == 0:
        return 0
    return fibonacci(n - 1) + fibonacci(n - 2)""",
        "original_code": """\
def fibonacci(n):
    if n == 0:
        return 0
    if n == 1:
        return 1
    return fibonacci(n - 1) + fibonacci(n - 2)""",
        "test_cases": [
            {"input": 0, "expected_output": 0},
            {"input": 1, "expected_output": 1},
            {"input": 5, "expected_output": 5},
            {"input": 10, "expected_output": 55},
        ],
        "bug_location": {"function": "fibonacci", "line_start": 4},
        "initial_error": "RecursionError: maximum recursion depth exceeded — n=1 has no base case",
        "agent_turns": [
            """\
OBSERVATION: `fibonacci(1)` causes a RecursionError. The function has a base case for `n == 0` (returns 0) but no base case for `n == 1`. When called with n=1, it computes `fibonacci(0) + fibonacci(-1)`. `fibonacci(-1)` then computes `fibonacci(-2) + fibonacci(-3)`, recursing infinitely into negative integers.
HYPOTHESIS: Standard Fibonacci requires two base cases: fib(0)=0 and fib(1)=1. Without the `n==1` base case, any call with n>=1 eventually reaches n=1 which recurses into n=-1, n=-2, ... with no termination condition. The recursion invariant `n >= 0` is broken as soon as n becomes negative, causing infinite descent.
CONFIDENCE: high
ACTION: inspect_lines
DETAIL: 3, 4""",
            """\
OBSERVATION: Missing `if n == 1: return 1` between line 3 and the recursive return. This is the second required base case for the Fibonacci recurrence.
HYPOTHESIS: Adding `if n == 1: return 1` after the `n == 0` check provides the second anchor point. With both base cases, `fibonacci(2) = fibonacci(1) + fibonacci(0) = 1 + 0 = 1`, and the recursion terminates correctly for all n >= 0. This fixes fibonacci(1)=1, fibonacci(5)=5, and fibonacci(10)=55.
CONFIDENCE: high
ACTION: propose_fix
DETAIL: def fibonacci(n):
    if n == 0:
        return 0
    if n == 1:
        return 1
    return fibonacci(n - 1) + fibonacci(n - 2)""",
        ],
    },
}



def _run_tests(code: str, function_name: str, test_cases: list) -> dict:
    passed = 0
    python = shutil.which("python3") or shutil.which("python") or sys.executable
    for tc in test_cases:
        inp = tc["input"]
        expected = tc["expected_output"]
        args_str = ", ".join(repr(x) for x in inp)
        script = (
            f"{code}\n"
            f"try:\n"
            f"    r = {function_name}({args_str})\n"
            f"    print('PASS' if r == {repr(expected)} else f'FAIL: got { r} ')\n"
            f"except Exception as e:\n"
            f"    print(f'ERROR: { e} ')\n"
        )
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
                f.write(script)
                fname = f.name
            r = subprocess.run([python, fname], capture_output=True, text=True, timeout=5)
            os.unlink(fname)
            if "PASS" in r.stdout:
                passed += 1
        except Exception:
            pass
    total = len(test_cases)
    return {"passed": passed, "failed": total - passed, "total": total, "newly_broken": 0}




def run_debug_session(example_name: str, custom_code: str) -> str:
    calculator = DebugRewardCalculator()

    
    if example_name and example_name in EXAMPLES:
        bug = EXAMPLES[example_name]
        code = bug["buggy_code"]
        agent_turns = bug["agent_turns"]
        ground_truth = {
            "bug_function": bug["bug_location"]["function"],
            "bug_line": bug["bug_location"]["line_start"],
            "bug_type": bug["bug_type"],
            "canonical_fix_code": bug["original_code"],
        }
        test_cases = bug["test_cases"]
        function_name = bug["function_name"]
        initial_error = bug["initial_error"]
    else:
        
        code = custom_code.strip() if custom_code.strip() else "# No code provided"
        agent_turns = [
            """\
OBSERVATION: Analyzing the provided code for structural issues, off-by-one errors, wrong operators, and logic inversions.
HYPOTHESIS: Based on visual inspection, the function may contain a comparison operator error or a missing base case. Without test output I cannot pinpoint the exact line — requesting test execution to observe failure mode.
CONFIDENCE: low
ACTION: run_tests
DETAIL: Run the full test suite to observe which inputs fail and what values are returned.""",
            """\
OBSERVATION: Without test case outputs available in this demo mode, proposing a conservative fix based on common patterns observed in the code structure.
HYPOTHESIS: The most likely bug class for this code structure is an operator or boundary condition error. A careful review of comparison operators, return values, and accumulation methods is recommended.
CONFIDENCE: low
ACTION: propose_fix
DETAIL: """ + code,
        ]
        ground_truth = {
            "bug_function": "", "bug_line": -1,
            "bug_type": "unknown", "canonical_fix_code": "",
        }
        test_cases = []
        function_name = ""
        initial_error = "Unknown — paste your own code and observe the agent reasoning"

    
    lines = []
    lines.append("━" * 60)
    lines.append(f"🐛  BUGGY CODE")
    lines.append("━" * 60)
    lines.append(code)
    lines.append("")
    lines.append(f"❌  Initial failure: {initial_error}")
    lines.append("")

    total_episode_reward = 0.0
    solved = False

    for turn_idx, raw_turn in enumerate(agent_turns):
        lines.append("━" * 60)
        lines.append(f"  TURN {turn_idx + 1}")
        lines.append("━" * 60)

        agent_output = parse_agent_output(raw_turn)

        
        test_results = {"passed": 0, "failed": 0, "total": len(test_cases), "newly_broken": 0}
        if agent_output.action == "propose_fix" and test_cases and function_name:
            test_results = _run_tests(agent_output.detail, function_name, test_cases)

        
        reward = calculator.compute_turn_reward(
            agent_output=agent_output,
            ground_truth=ground_truth,
            test_results=test_results,
            turn_number=turn_idx,
        )
        total_episode_reward += reward.total

        
        lines.append(f"OBSERVATION:  {agent_output.observation}")
        lines.append("")
        lines.append(f"HYPOTHESIS:   {agent_output.hypothesis}")
        lines.append("")
        lines.append(f"CONFIDENCE:   {agent_output.confidence.upper()}")
        lines.append(f"ACTION:       {agent_output.action}")
        lines.append(f"DETAIL:       {agent_output.detail[:120]}{'...' if len(agent_output.detail) > 120 else ''}")
        lines.append("")

        
        lines.append("┌─────────────────────────────────────────────┐")
        lines.append("│  Reward Breakdown                           │")
        lines.append("├──────────────────────────┬──────────────────┤")
        lines.append(f"│  Format compliance       │  {reward.format_compliance:+.4f}          │")
        lines.append(f"│  Hypothesis quality      │  {reward.hypothesis_quality:+.4f}          │")
        lines.append(f"│  Localization            │  {reward.localization:+.4f}          │")
        lines.append(f"│  Fix quality             │  {reward.fix_quality:+.4f}          │")
        lines.append(f"│  Semantic similarity     │  {reward.semantic_similarity:+.4f}          │")
        lines.append(f"│  Efficiency potential    │  {reward.efficiency_potential:+.4f}          │")
        lines.append(f"│  Penalties               │  {reward.penalties:+.4f}          │")
        lines.append("├──────────────────────────┼──────────────────┤")
        lines.append(f"│  TURN REWARD             │  {reward.total:+.4f}          │")
        lines.append("└──────────────────────────┴──────────────────┘")

        
        if agent_output.action == "propose_fix" and test_results["total"] > 0:
            p = test_results["passed"]
            t = test_results["total"]
            bar = "█" * p + "░" * (t - p)
            lines.append(f"\n  Tests: [{bar}] {p}/{t} passing")
            if p == t:
                lines.append("  ✅ ALL TESTS PASS")
                solved = True
            else:
                lines.append(f"  ⚠️  {t - p} test(s) still failing")

        lines.append("")

    
    lines.append("━" * 60)
    if solved:
        lines.append(f"  ✅  SOLVED in {len(agent_turns)} turns  |  Episode reward: {total_episode_reward:+.3f}")
    else:
        lines.append(f"  ❌  NOT SOLVED in {len(agent_turns)} turns  |  Episode reward: {total_episode_reward:+.3f}")
    lines.append("━" * 60)
    lines.append("")
    lines.append("Reward design grounded in:")
    lines.append("  • Masud et al. (2026) — process-based + execution-based rewards")
    lines.append("  • Ibrahim et al. (2024) — potential-based efficiency shaping")

    return "\n".join(lines)




def load_example(example_name: str) -> str:
    if example_name and example_name in EXAMPLES:
        return EXAMPLES[example_name]["buggy_code"]
    return ""


def create_demo() -> gr.Blocks:
    example_names = list(EXAMPLES.keys())

    with gr.Blocks(
        title="AgentDebuggerEnv — Live Demo",
        theme=gr.themes.Soft(),
        css="""
        .output-text { font-family: 'JetBrains Mono', 'Fira Code', monospace !important; font-size: 13px; }
        .header-md h1 { color: #1a1a2e; }
        """,
    ) as demo:

        gr.Markdown(
            """
# 🐛 AgentDebuggerEnv — Live Debugging Demo

**Watch an AI agent reason through buggy code using structured hypothesis testing.**

Each turn the agent outputs a rigid format: `OBSERVATION → HYPOTHESIS → CONFIDENCE → ACTION → DETAIL`  
The environment scores every turn across 6 reward components grounded in two research papers.

---
            """,
            elem_classes=["header-md"],
        )

        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### Step 1 — Choose a bug")
                example_dropdown = gr.Dropdown(
                    choices=example_names,
                    value=example_names[0],
                    label="Pre-loaded examples (one per bug type)",
                    interactive=True,
                )
                gr.Markdown("### Step 2 — Or paste your own buggy Python")
                custom_code = gr.Code(
                    language="python",
                    label="Custom buggy code (optional — overrides dropdown)",
                    lines=14,
                    interactive=True,
                )
                example_dropdown.change(
                    fn=load_example,
                    inputs=example_dropdown,
                    outputs=custom_code,
                )
                
                demo.load(
                    fn=lambda: load_example(example_names[0]),
                    outputs=custom_code,
                )

                run_btn = gr.Button(
                    "▶  Run Debug Agent",
                    variant="primary",
                    size="lg",
                )

                gr.Markdown(
                    """
**Reward components:**
| Component | Weight | Paper |
|-----------|--------|-------|
| Format compliance | 10% | Dense signal |
| Hypothesis quality | 20% | Masud et al. 2026 |
| Localization | 15% | Execution proxy |
| Fix quality | 35% | Primary signal |
| Semantic similarity | 10% | Masud et al. 2026 |
| Efficiency potential | 10% | Ibrahim et al. 2024 |
                    """
                )

            with gr.Column(scale=2):
                gr.Markdown("### Agent output — turn by turn")
                output_box = gr.Textbox(
                    label="Debug session",
                    lines=50,
                    max_lines=80,
                    interactive=False,
                    elem_classes=["output-text"],
                    placeholder="Click 'Run Debug Agent' to start...",
                )

        run_btn.click(
            fn=run_debug_session,
            inputs=[example_dropdown, custom_code],
            outputs=output_box,
        )

        gr.Markdown(
            """
---
**API endpoints** (for programmatic access):
`POST /reset` · `POST /step` · `GET /tasks` · `GET /health`  
[View full API docs](/docs) · [GitHub](https://github.com/shasshaank/meta_hackthon)
            """
        )

    return demo
