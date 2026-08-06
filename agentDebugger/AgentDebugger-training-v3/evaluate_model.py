import os
import json
import torch
import sys
import argparse
from tqdm import tqdm
from dotenv import load_dotenv
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel


load_dotenv()


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env.environment import DebuggerEnvironment
from env.models import parse_agent_output
from server.reward_calculator import DebugRewardCalculator


SYSTEM_PROMPT = """You are an expert Python debugger. You reason through bugs systematically.

You MUST respond in EXACTLY this format — no exceptions, no extra text:

OBSERVATION: [Specific observations about the code and error. Reference exact line numbers.]
HYPOTHESIS: [Your theory about the root cause. Must be at least 2 sentences. Reference specific variable names, operators, or logic.]
CONFIDENCE: [low | medium | high]
ACTION: [One of: inspect_lines | run_tests | propose_fix | request_context | give_up]
DETAIL: [For propose_fix: the complete corrected function code. For inspect_lines: line numbers. For others: specific details.]

Rules:
- Never omit any field
- HYPOTHESIS must explain WHY the bug causes the observed failure
- If proposing a fix, DETAIL must contain the complete function, not just the changed line
- Give up only if you have exhausted all reasonable hypotheses"""

def bug_to_prompt(bug: dict) -> str:
    return (
        f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\n"
        f"Debug this Python function:\n\n```python\n{bug['buggy_code']}\n```\n\n"
        f"Initial failure: {bug.get('initial_error', 'Some tests are failing.')}\n"
        f"<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Limit number of bugs to test per tier")
    parser.add_argument("--adapter", type=str, default="shashaank0707/AgentDebugger-trained", help="Hugging Face repo or local path of the adapter")
    parser.add_argument("--base-model", type=str, default="Qwen/Qwen2.5-Coder-3B-Instruct", help="Base model identifier")
    args = parser.parse_args()

    
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        print("WARNING: HF_TOKEN environment variable not set. Loading a private repository might fail.")

    print(f"Loading base model: {args.base_model}...")
    device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
    dtype = torch.float32 if device == "cpu" else torch.float16
    print(f"Using device: {device} | dtype: {dtype}")

    try:
        tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)
        tokenizer.pad_token = tokenizer.eos_token
        tokenizer.padding_side = "left"

        base_model = AutoModelForCausalLM.from_pretrained(
            args.base_model,
            torch_dtype=dtype,
            trust_remote_code=True,
            device_map="auto" if device == "cuda" else None
        )

        print(f"Loading LoRA adapter: {args.adapter}...")
        model = PeftModel.from_pretrained(
            base_model,
            args.adapter,
            token=hf_token
        )
        
        
        if device in ["mps", "cpu"]:
            print(f"Moving model to target device: {device}...")
            model = model.to(device)
            
        model.eval()
    except Exception as e:
        print(f"ERROR loading model: {e}")
        print("Please ensure your HF_TOKEN is valid and set in your .env file.")
        sys.exit(1)

    print("\nInitializing environment and loading bugs...")
    env = DebuggerEnvironment()
    calculator = DebugRewardCalculator()

    results = {}
    summary = {
        "model": args.adapter,
        "base_model": args.base_model,
        "tiers": {}
    }

    total_bugs_count = 0
    solved_bugs_count = 0

    for tier in [1, 2, 3]:
        path = f"data/bugs_tier{tier}.jsonl"
        if not os.path.exists(path):
            print(f"Skipping Tier {tier} - file not found at {path}")
            continue

        print(f"\nEvaluating Tier {tier} bugs...")
        bugs = []
        with open(path) as f:
            for line in f:
                if line.strip():
                    bugs.append(json.loads(line))

        if args.limit:
            bugs = bugs[:args.limit]

        tier_results = []
        tier_solved = 0

        for bug in tqdm(bugs):
            
            env.current_bug = bug
            env.current_episode_trajectory = []
            env.turn_number = 0

            
            prompt = bug_to_prompt(bug)
            inputs = tokenizer(prompt, return_tensors="pt").to(device)

            with torch.no_grad():
                out = model.generate(
                    **inputs,
                    max_new_tokens=300,
                    do_sample=False
                )
            
            completion = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)

            
            step_result = env.step_curriculum(completion)
            info = step_result["info"]
            reward_breakdown = info["reward_breakdown"]
            solved = info["solved"]

            if solved:
                tier_solved += 1
                solved_bugs_count += 1
            total_bugs_count += 1

            
            bug_detail = {
                "id": bug.get("id"),
                "function_name": bug.get("function_name"),
                "bug_type": bug.get("bug_type"),
                "difficulty": bug.get("difficulty"),
                "prompt": prompt,
                "raw_completion": completion,
                "parsed_action": {
                    "observation": info["history"][-1]["action"] if "history" in info and info["history"] else "unknown",
                    "solved": solved,
                },
                "reward": step_result["reward"],
                "reward_breakdown": reward_breakdown,
                "test_results": step_result["observation"]["test_results"],
                "solved": solved
            }
            tier_results.append(bug_detail)

        tier_solve_rate = tier_solved / len(bugs) if bugs else 0.0
        print(f"Tier {tier} Solve Rate: {tier_solve_rate:.1%} ({tier_solved}/{len(bugs)})")

        results[f"tier{tier}"] = tier_results
        summary["tiers"][f"tier{tier}"] = {
            "total": len(bugs),
            "solved": tier_solved,
            "solve_rate": tier_solve_rate,
            "mean_reward": sum(r["reward"] for r in tier_results) / len(tier_results) if tier_results else 0.0
        }

    summary["overall"] = {
        "total": total_bugs_count,
        "solved": solved_bugs_count,
        "solve_rate": solved_bugs_count / total_bugs_count if total_bugs_count else 0.0,
    }

    
    output = {
        "summary": summary,
        "results": results
    }

    with open("evaluation_results.json", "w") as f:
        json.dump(output, f, indent=2)

    print("\n==========================================")
    print("EVALUATION COMPLETE!")
    print(f"Overall Solve Rate: {summary['overall']['solve_rate']:.1%} ({solved_bugs_count}/{total_bugs_count})")
    print("Saved all results to evaluation_results.json")
    print("==========================================")

if __name__ == "__main__":
    main()
