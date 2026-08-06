import os
import sys


sys.path.append(os.path.abspath('.'))

from data.generate_bugs import TIER1_BUGS, TIER2_BUGS, TIER3_BUGS

for b in TIER1_BUGS:
    if b["id"] == "t1_003":
        for t in b["test_cases"]:
            while len(t["input"]) == 1 and isinstance(t["input"][0], list):
                t["input"] = t["input"][0]
            t["input"] = [t["input"]]
    elif b["id"] == "t1_005":
        for t in b["test_cases"]:
            while len(t["input"]) == 1 and isinstance(t["input"][0], list):
                t["input"] = t["input"][0]
            t["input"] = [t["input"]]
    elif b["id"] == "t1_006":
        for t in b["test_cases"]:
            while len(t["input"]) == 1 and isinstance(t["input"][0], list):
                t["input"] = t["input"][0]
            t["input"] = [t["input"]]
    elif b["id"] == "t1_001":
        b["buggy_code"] = b["buggy_code"].replace("right = mid", "right = mid + 1")
    elif b["id"] == "t1_026":
        b["buggy_code"] = b["buggy_code"].replace("return prefix", "return prefix + 'x'")
    elif b["id"] == "t1_033":
        b["buggy_code"] = b["buggy_code"].replace("dp[1] = 0", "dp[1] = 9999")
    elif b["id"] == "t1_034":
        b["buggy_code"] = b["buggy_code"].replace("dp[i] = max(dp[i-1], dp[i-2] + nums[i])", "dp[i] = max(dp[i-1], nums[i])")

for b in TIER2_BUGS:
    if b["id"] == "t2_003":
        for t in b["test_cases"]:
            
            while len(t["input"]) == 1 and isinstance(t["input"][0], list) and len(t["input"][0]) == 2:
                t["input"] = t["input"][0]
            if len(t["input"]) == 2 and not isinstance(t["input"][0], list) and not isinstance(t["input"], tuple):
                t["input"] = [t["input"]]
            elif len(t["input"]) >= 2:
                t["input"] = [t["input"]]
    elif b["id"] == "t2_026":
        b["original_code"] = b["original_code"].replace("return (mn, mx)", "return [mn, mx]")
        b["buggy_code"] = b["buggy_code"].replace("return (mn, mn)", "return [mn, mn]")
        for t in b["test_cases"]:
            if isinstance(t["expected_output"], tuple):
                t["expected_output"] = list(t["expected_output"])
    elif b["id"] == "t2_029":
        for t in b["test_cases"]:
            if t["input"] == [[1, 2, 3]]:
                t["expected_output"] = [2, 3, 1]

for b in TIER3_BUGS:
    if b["id"] == "t3_002":
        for t in b["test_cases"]:
            
            while len(t["input"]) == 1 and isinstance(t["input"][0], list):
                t["input"] = t["input"][0]
            
            t["input"] = [t["input"]]
    elif b["id"] == "t3_007":
        b["buggy_code"] = b["buggy_code"].replace("calc_area(height, width)", "calc_area(height, height)")
    elif b["id"] == "t3_009":
        b["buggy_code"] = b["buggy_code"].replace("seen = set()", "seen = {1}")
    elif b["id"] == "t3_010":
        b["buggy_code"] = b["buggy_code"].replace("total = 0", "total = 10")
    elif b["id"] == "t3_011":
        b["buggy_code"] = b["buggy_code"].replace("def helper(val, lst=[]):", "def helper(val, lst=[1]):")
    elif b["id"] == "t3_012":
        b["buggy_code"] = b["buggy_code"].replace("calls = 0", "calls = 5")
    elif b["id"] == "t3_013":
        b["buggy_code"] = b["buggy_code"].replace("words_cache = []", "words_cache = ['ERROR']")
    elif b["id"] == "t3_014":
        b["buggy_code"] = b["buggy_code"].replace("errors = []", "errors = ['fatal']")

import pprint

def dump_var(f, name, val):
    f.write(f'{name} = ')
    f.write(pprint.pformat(val, sort_dicts=False, width=120))
    f.write('\n\n')

with open("data/generate_bugs.py", "w", encoding="utf-8") as f:
    f.write('"""\nAgentDebuggerEnv - Bug Dataset Generator\n\n')
    f.write('Generates three tiers of buggy Python functions for curriculum learning:\n')
    f.write('  Tier 1 (easy):   Off-by-one errors, wrong operators, simple logic inversions\n')
    f.write('  Tier 2 (medium): Incorrect algorithm logic, wrong variable references, subtle type errors\n')
    f.write('  Tier 3 (hard):   Multi-bug interactions, concurrency, edge-case-only failures\n\n')
    f.write('Usage:\n  python data/generate_bugs.py\n\n')
    f.write('Outputs:\n  data/bugs_tier1.jsonl  (~40 bugs)\n  data/bugs_tier2.jsonl  (~30 bugs)\n  data/bugs_tier3.jsonl  (~20 bugs)\n"""\n\n')
    f.write('import json\nimport os\n\n')
    
    dump_var(f, 'TIER1_BUGS', TIER1_BUGS)
    dump_var(f, 'TIER2_BUGS', TIER2_BUGS)
    dump_var(f, 'TIER3_BUGS', TIER3_BUGS)
    
    f.write('def write_jsonl(bugs: list, path: str):\n')
    f.write('    with open(path, "w") as f:\n')
    f.write('        for bug in bugs:\n')
    f.write('            f.write(json.dumps(bug) + "\\n")\n\n')
    f.write('if __name__ == "__main__":\n')
    f.write('    os.makedirs("data", exist_ok=True)\n')
    f.write('    write_jsonl(TIER1_BUGS, "data/bugs_tier1.jsonl")\n')
    f.write('    write_jsonl(TIER2_BUGS, "data/bugs_tier2.jsonl")\n')
    f.write('    write_jsonl(TIER3_BUGS, "data/bugs_tier3.jsonl")\n')
    f.write('    print(f"Tier 1: {len(TIER1_BUGS)}, Tier 2: {len(TIER2_BUGS)}, Tier 3: {len(TIER3_BUGS)}")\n')
    f.write('    print("\\nDone. Run training/train_grpo.py to start training.")\n')

print("Fix applied successfully.")
