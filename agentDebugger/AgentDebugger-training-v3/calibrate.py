import json
import subprocess
import tempfile
import os
import sys

def test_passes(code, func, inp, expected):
    if isinstance(inp, (list, tuple)):
        args = ', '.join(repr(x) for x in inp)
    else:
        args = repr(inp)
    
    script = f"""{code}

try:
    r = {func}({args})
    expected = {repr(expected)}
    print("PASS" if r == expected else f"FAIL: got { r} ")
except Exception as e:
    print(f"ERROR: { e} ")
"""
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(script)
            fname = f.name
        r = subprocess.run(
            [sys.executable, fname],
            capture_output=True, text=True, timeout=5
        )
        os.unlink(fname)
        return 'PASS' in r.stdout
    except:
        return False

for tier in [1, 2, 3]:
    bugs = [json.loads(l) for l in open(f'data/bugs_tier{tier}.jsonl') if l.strip()]
    
    broken_original = []
    buggy_not_failing = []
    
    for b in bugs:
        orig_passes = all(
            test_passes(b['original_code'], b['function_name'],
                       t['input'], t['expected_output'])
            for t in b['test_cases']
        )
        buggy_fails_some = any(
            not test_passes(b['buggy_code'], b['function_name'],
                           t['input'], t['expected_output'])
            for t in b['test_cases']
        )
        
        if not orig_passes:
            broken_original.append(b['id'])
        if not buggy_fails_some:
            buggy_not_failing.append(b['id'])
    
    print(f'\nTier {tier}:')
    if broken_original:
        print(f'  BROKEN original_code: {broken_original}')
    if buggy_not_failing:
        print(f'  BUGGY code not failing: {buggy_not_failing}')
    if not broken_original and not buggy_not_failing:
        print(f'  All good!')