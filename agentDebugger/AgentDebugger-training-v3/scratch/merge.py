import sys
import os


sys.path.append(os.path.abspath('.'))

from data.generate_bugs import TIER1_BUGS as T1_OLD
from data.generate_bugs import TIER2_BUGS as T2_OLD
from data.generate_bugs import TIER3_BUGS as T3_OLD

from scratch.data_tier1 import t1_bugs
from scratch.data_tier2 import t2_bugs
from scratch.data_tier3 import t3_bugs

t1_all = T1_OLD + t1_bugs
t2_all = T2_OLD + t2_bugs
t3_all = T3_OLD + t3_bugs


print(f"Tier 1: {len(t1_all)}")
print(f"Tier 2: {len(t2_all)}")
print(f"Tier 3: {len(t3_all)}")

import json
def pretty_list(lst, name):
    lines = [f"{name} = ["]
    for item in lst:
        lines.append("    {")
        for k, v in item.items():
            if isinstance(v, str):
                if '\n' in v:
                    lines.append(f'        "{k}": (')
                    for line in v.split('\n'):
                        lines.append(f'            {repr(line + "\\n")}')
                    lines[-1] = lines[-1][:-4] + "'" + lines[-1][-3:] 
        
        
        pass


with open("data/generate_bugs.py", "w", encoding="utf-8") as f:
    f.write('"""\n')
    f.write('AgentDebuggerEnv — Bug Dataset Generator\n\n')
    f.write('Generates three tiers of buggy Python functions for curriculum learning:\n')
    f.write('  Tier 1 (easy):   Off-by-one errors, wrong operators, simple logic inversions\n')
    f.write('  Tier 2 (medium): Incorrect algorithm logic, wrong variable references, subtle type errors\n')
    f.write('  Tier 3 (hard):   Multi-bug interactions, concurrency, edge-case-only failures\n\n')
    f.write('Usage:\n')
    f.write('  python data/generate_bugs.py\n\n')
    f.write('Outputs:\n')
    f.write('  data/bugs_tier1.jsonl  (~40 bugs)\n')
    f.write('  data/bugs_tier2.jsonl  (~30 bugs)\n')
    f.write('  data/bugs_tier3.jsonl  (~20 bugs)\n')
    f.write('"""\n\n')
    f.write('import json\n')
    f.write('import os\n\n')
    
    
    import pprint
    
    def dump_var(name, val):
        f.write(f'{name} = ')
        f.write(pprint.pformat(val, sort_dicts=False, width=120))
        f.write('\n\n')
        
    dump_var('TIER1_BUGS', t1_all)
    dump_var('TIER2_BUGS', t2_all)
    dump_var('TIER3_BUGS', t3_all)
    
    f.write('def write_jsonl(bugs: list, path: str):\n')
    f.write('    with open(path, "w") as f:\n')
    f.write('        for bug in bugs:\n')
    f.write('            f.write(json.dumps(bug) + "\\n")\n')
    f.write('    print(f"Tier {path[-12]}: {len(bugs)}")\n')  
    
    
    f.write('\n\n')
    f.write('if __name__ == "__main__":\n')
    f.write('    os.makedirs("data", exist_ok=True)\n')
    f.write('    write_jsonl(TIER1_BUGS, "data/bugs_tier1.jsonl")\n')
    f.write('    write_jsonl(TIER2_BUGS, "data/bugs_tier2.jsonl")\n')
    f.write('    write_jsonl(TIER3_BUGS, "data/bugs_tier3.jsonl")\n')
    f.write('    print(f"Tier 1: {len(TIER1_BUGS)}, Tier 2: {len(TIER2_BUGS)}, Tier 3: {len(TIER3_BUGS)}")\n')
    f.write('    print("\\nDone. Run training/train_grpo.py to start training.")\n')

print("generate_bugs.py rewritten.")
