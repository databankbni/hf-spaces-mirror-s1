
import os
import sys
import json
import argparse
import random
import subprocess
import tempfile
import shutil
from importlib import metadata


parser = argparse.ArgumentParser()
parser.add_argument("--test", action="store_true", help="Run 10 steps for testing (Colab/GPU)")
parser.add_argument("--test-local", action="store_true", dest="test_local",
                    help="Sanity-check reward function locally without any model or GPU")
parser.add_argument("--resume", type=str, default=None, help="Local path to checkpoint")
parser.add_argument("--hub-resume", type=str, default=None, help="HF repo to resume LoRA from (e.g. shashaank0707/AgentDebugger-trained-checkpoints)")
parser.add_argument("--step-offset", type=int, default=0, help="Steps already completed if using hub-resume")
parser.add_argument("--max_steps", type=int, default=500)
args = parser.parse_args()






if not args.test_local:
    
    
    
    
    import importlib.util, importlib
    _needs_cuda_torch = True
    if importlib.util.find_spec("torch") is not None:
        import torch as _t
        if _t.cuda.is_available():
            _needs_cuda_torch = False
        del _t
    if _needs_cuda_torch:
        print("Installing CUDA-enabled torch (cu121)...", flush=True)
        _r = os.system(
            f"{sys.executable} -m pip install -q --no-cache-dir "
            "torch --index-url https://download.pytorch.org/whl/cu121"
        )
        if _r != 0:
            print("ERROR: CUDA torch install failed.", flush=True)
            sys.exit(1)
        print("CUDA torch installed.", flush=True)

    _TRAIN_DEPS = [
        "wandb==0.18.7",
        "datasets==3.0.2",
        "transformers==4.48.3",
        "accelerate==1.0.1",
        "trl==0.15.2",
        "peft==0.13.2",
    ]
    print("Installing training dependencies...", flush=True)
    ret = os.system(
        f"{sys.executable} -m pip install -q --no-cache-dir " + " ".join(f'"{d}"' for d in _TRAIN_DEPS)
    )
    if ret != 0:
        print("ERROR: pip install failed. Training cannot continue.", flush=True)
        sys.exit(1)
    print("Dependencies installed.", flush=True)


if not args.test_local:
    import torch
    import wandb
    from datasets import Dataset
    from transformers import (
        AutoModelForCausalLM, AutoTokenizer, TrainerCallback
    )
    from peft import get_peft_model, LoraConfig, TaskType
    from trl import GRPOTrainer, GRPOConfig

    def _pkg_ver(name: str) -> str:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return "not-installed"

    print(
        "Runtime package versions | "
        f"python={sys.version.split()[0]} "
        f"torch={_pkg_ver('torch')} "
        f"transformers={_pkg_ver('transformers')} "
        f"trl={_pkg_ver('trl')} "
        f"accelerate={_pkg_ver('accelerate')} "
        f"peft={_pkg_ver('peft')}"
    )

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server.reward_calculator import DebugRewardCalculator
from server.models import parse_agent_output


MODEL_NAME = "Qwen/Qwen2.5-Coder-3B-Instruct"
HF_REPO = "shashaank0707/AgentDebugger-trained"
MAX_STEPS = (10 if args.test else args.max_steps) - args.step_offset
CHECKPOINT_DIR = "./checkpoints"


WANDB_API_KEY = os.environ.get("WANDB_API_KEY", "") if not args.test_local else ""
HF_TOKEN = os.environ.get("HF_TOKEN")

if WANDB_API_KEY:
    wandb.init(
        project="AgentDebuggerEnv",
        name=f"grpo-qwen-7b-{'test' if args.test else 'full'}",
        config={
            "model": MODEL_NAME,
            "algorithm": "GRPO",
            "curriculum": "tier1->tier2->tier3",
            "max_steps": MAX_STEPS,
            "reward_components": ["format", "hypothesis", "localization", "fix", "semantic", "efficiency"],
            "paper_citations": ["Masud et al. 2026", "Ibrahim et al. 2024"],
        }
    )


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


def load_bugs(tier: int) -> list[dict]:
    path = f"data/bugs_tier{tier}.jsonl"
    if not os.path.exists(path):
        print(f"WARNING: {path} not found. Run data/generate_bugs.py first.")
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]

def get_bugs_for_step(step: int) -> list[dict]:
    tier1 = load_bugs(1)
    if step < 150:
        return tier1
    elif step < 600:
        return tier1 + load_bugs(2)
    return tier1 + load_bugs(2) + load_bugs(3)

def bug_to_prompt(bug: dict) -> str:
    return (
        f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\n"
        f"Debug this Python function:\n\n```python\n{bug['buggy_code']}\n```\n\n"
        f"Initial failure: {bug.get('initial_error', 'Some tests are failing.')}\n"
        f"<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )

def _run_fix(proposed_code: str, bug: dict) -> dict:
    test_cases = bug.get("test_cases", [])
    func_name = bug.get("function_name", "")
    if not proposed_code or not test_cases or not func_name:
        return {"passed": 0, "failed": 0, "total": len(test_cases), "newly_broken": 0}

    passed = 0
    for test in test_cases:
        inp = test["input"]
        args_str = ", ".join(repr(x) for x in inp)
        script = (
            f"{proposed_code}\n"
            f"try:\n"
            f"    r={func_name}({args_str})\n"
            f"    print('PASS' if r=={repr(test['expected_output'])} else 'FAIL')\n"
            f"except Exception as e:\n"
            f"    print(f'ERROR: { e} ')\n"
        )
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(script)
                fname = f.name
            python = shutil.which("python3") or shutil.which("python") or sys.executable
            r = subprocess.run([python, fname], capture_output=True, text=True, timeout=5)
            os.unlink(fname)
            if "PASS" in r.stdout:
                passed += 1
        except Exception:
            pass

    return {"passed": passed, "failed": len(test_cases) - passed, "total": len(test_cases), "newly_broken": 0}


MOCK_GOOD = """
OBSERVATION: The loop condition on line 4 uses <= instead of 
HYPOTHESIS: This causes an off-by-one error because Python lists are 
0-indexed, so the last valid index is len(arr)-1 not len(arr)
CONFIDENCE: high
ACTION: propose_fix
DETAIL: def binary_search(arr, target):
    left, right = 0, len(arr) - 1
    while left < right:
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1
"""

MOCK_BAD = """
I think there might be a bug somewhere in the code.
Let me try fixing it.
"""


if args.test_local:
    print("=" * 60)
    print("LOCAL TEST MODE — no model loaded, testing reward function only")
    print("=" * 60)

    bugs = load_bugs(1)
    if not bugs:
        print("ERROR: No bugs found in data/bugs_tier1.jsonl. Run data/generate_bugs.py first.")
        sys.exit(1)

    bug = bugs[0]
    print(f"\nUsing bug: {bug.get('function_name', '?')} — {bug.get('bug_type', '?')}\n")

    calculator_local = DebugRewardCalculator()

    def _score(label: str, completion: str) -> float:
        try:
            agent_output = parse_agent_output(completion)
            test_results = {"passed": 0, "failed": 0, "total": 0, "newly_broken": 0}
            if agent_output.action == "propose_fix":
                test_results = _run_fix(agent_output.detail, bug)
            breakdown = calculator_local.compute_turn_reward(
                agent_output=agent_output,
                ground_truth={
                    "bug_function": bug.get("bug_location", {}).get("function", ""),
                    "bug_line": bug.get("bug_location", {}).get("line_start", -1),
                    "bug_type": bug.get("bug_type", ""),
                    "canonical_fix_code": bug.get("original_code", ""),
                },
                test_results=test_results,
                turn_number=0,
            )
            print(f"--- {label} reward breakdown ---")
            for field, value in breakdown.__dict__.items():
                print(f"  {field}: {value}")
            print(f"  TOTAL: {breakdown.total}\n")
            return breakdown.total
        except Exception as e:
            print(f"Reward error for {label}: {e}")
            return -0.3

    good_score = _score("MOCK_GOOD", MOCK_GOOD)
    bad_score = _score("MOCK_BAD", MOCK_BAD)

    print(f"MOCK_GOOD score: {good_score:.4f}")
    print(f"MOCK_BAD  score: {bad_score:.4f}")

    assert good_score > bad_score, (
        f"ASSERTION FAILED: MOCK_GOOD ({good_score:.4f}) should be > MOCK_BAD ({bad_score:.4f})"
    )
    print("\nLOCAL TEST PASSED")
    sys.exit(0)


_gpu_vram_gb = 0
_is_ampere_plus = False  
if torch.cuda.is_available():
    _props = torch.cuda.get_device_properties(0)
    _gpu_vram_gb = _props.total_memory / 1e9
    _is_ampere_plus = _props.major >= 8
    print(f"GPU: {_props.name} | VRAM: {_gpu_vram_gb:.1f}GB | "
          f"Compute cap: {_props.major}.{_props.minor} | "
          f"bfloat16: {'yes' if _is_ampere_plus else 'no'}")

COMPUTE_DTYPE = torch.bfloat16 if _is_ampere_plus else torch.float16



if _gpu_vram_gb >= 70:          
    _batch       = 8
    _grad_accum  = 1            
    _num_gen     = 8            
    _max_comp    = 256
    _lora_r      = 16
elif _gpu_vram_gb >= 40:        
    _batch       = 4
    _grad_accum  = 2            
    _num_gen     = 4            
    _max_comp    = 256
    _lora_r      = 16
elif _gpu_vram_gb >= 20:        
    _batch       = 2
    _grad_accum  = 4
    _num_gen     = 2            
    _max_comp    = 192
    _lora_r      = 8
else:                           
    _batch       = 2
    _grad_accum  = 4
    _num_gen     = 2            
    _max_comp    = 160
    _lora_r      = 8

print(f"Training config: batch={_batch} grad_accum={_grad_accum} "
      f"num_gen={_num_gen} max_comp={_max_comp} lora_r={_lora_r} "
      f"dtype={COMPUTE_DTYPE}")




print(f"Loading {MODEL_NAME} in {COMPUTE_DTYPE}...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
tokenizer.pad_token = tokenizer.eos_token
tokenizer.padding_side = "left"

model = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME,
    device_map="auto",
    trust_remote_code=True,
    torch_dtype=COMPUTE_DTYPE,
)
model.config.use_cache = False

if args.hub_resume:
    from peft import PeftModel
    print(f"\nResuming LoRA adapter from Hub: {args.hub_resume}")
    model = PeftModel.from_pretrained(model, args.hub_resume, is_trainable=True)
else:
    lora_config = LoraConfig(
        r=_lora_r,
        lora_alpha=_lora_r * 2,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0.0,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )
    model = get_peft_model(model, lora_config)
model.enable_input_require_grads()
model.gradient_checkpointing_enable()
print(f"Trainable params: {model.num_parameters(only_trainable=True):,}")


def _select_runtime_device(model) -> str:
    def _cuda_usable() -> bool:
        try:
            if not torch.cuda.is_available():
                return False
            
            _ = torch.zeros(1, device="cuda")
            return True
        except Exception as e:
            print(f"WARNING: CUDA initialization failed ({e}). Falling back to CPU.")
            return False

    
    try:
        model_device = str(next(model.parameters()).device)
        if model_device.startswith("cuda") and not _cuda_usable():
            return "cpu"
        return model_device
    except Exception:
        pass

    
    if _cuda_usable():
        return "cuda"
    return "cpu"


RUNTIME_DEVICE = _select_runtime_device(model)
print(f"Using generation/training runtime device: {RUNTIME_DEVICE}")


calculator = DebugRewardCalculator()

def reward_fn(completions: list[str], prompts: list[str], **kwargs) -> list[float]:
    rewards = []
    bugs_raw = kwargs.get("bug_metadata", [{}] * len(completions))
    bugs = [json.loads(b) if isinstance(b, str) else b for b in bugs_raw]

    for completion, bug in zip(completions, bugs):
        try:
            agent_output = parse_agent_output(completion)

            
            test_results = {"passed": 0, "failed": 0, "total": 0, "newly_broken": 0}
            if agent_output.action == "propose_fix" and bug:
                test_results = _run_fix(agent_output.detail, bug)

            breakdown = calculator.compute_turn_reward(
                agent_output=agent_output,
                ground_truth={
                    "bug_function": bug.get("bug_location", {}).get("function", ""),
                    "bug_line": bug.get("bug_location", {}).get("line_start", -1),
                    "bug_type": bug.get("bug_type", ""),
                    "canonical_fix_code": bug.get("original_code", ""),
                },
                test_results=test_results,
                turn_number=0,
            )

            if WANDB_API_KEY:
                wandb.log({k: v for k, v in breakdown.__dict__.items()})

            rewards.append(breakdown.total)

        except Exception as e:
            print(f"Reward error: {e}")
            rewards.append(-0.3)

    return rewards


def run_baseline(n: int = 20) -> dict:
    print("\nRunning baseline evaluation on UNTRAINED model...")
    model.eval()
    bugs = load_bugs(1)[:n]
    rewards = []
    solved = 0
    for bug in bugs:
        prompt = bug_to_prompt(bug)
        inputs = tokenizer(prompt, return_tensors="pt").to(RUNTIME_DEVICE)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=200, do_sample=False)
        completion = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        r = reward_fn([completion], [prompt], bug_metadata=[bug])
        rewards.append(r[0])
        if r[0] > 0.20:
            solved += 1

    result = {"solve_rate": solved / max(len(bugs), 1), "avg_reward": sum(rewards) / max(len(rewards), 1), "rewards": rewards}
    with open("baseline_results.json", "w") as f:
        json.dump(result, f)
    print(f"Baseline: solve_rate={result['solve_rate']:.1%}, avg_reward={result['avg_reward']:.3f}")
    if WANDB_API_KEY:
        wandb.log({"baseline/solve_rate": result["solve_rate"], "baseline/avg_reward": result["avg_reward"]})
    return result

baseline = run_baseline()
model.train()


def make_dataset(step: int) -> Dataset:
    bugs = get_bugs_for_step(step)
    return Dataset.from_list([{"prompt": bug_to_prompt(b), "bug_metadata": json.dumps(b)} for b in bugs])


config = GRPOConfig(
    output_dir=CHECKPOINT_DIR,
    max_steps=MAX_STEPS,
    per_device_train_batch_size=_batch,
    gradient_accumulation_steps=_grad_accum,
    learning_rate=2e-5,
    lr_scheduler_type="cosine",
    warmup_steps=10 if args.test else 30,
    num_generations=_num_gen,
    max_completion_length=_max_comp,
    temperature=0.9,
    logging_steps=5,
    save_steps=25,               
    save_strategy="steps",
    report_to="wandb" if WANDB_API_KEY else "none",
)

trainer = GRPOTrainer(
    model=model,
    args=config,
    train_dataset=make_dataset(0),
    reward_funcs=reward_fn,
    processing_class=tokenizer,
)


class CurriculumCallback(TrainerCallback):
    def on_step_end(self, callback_args, state, control, **kwargs):
        step = state.global_step + args.step_offset
        if step in [150, 350]:
            trainer.train_dataset = make_dataset(step)
            print(f"\nCurriculum advanced at step {step}!")
            if WANDB_API_KEY:
                wandb.log({"curriculum/step": step})

trainer.add_callback(CurriculumCallback())






HUB_PUSH_EVERY = 50  

class CheckpointPushCallback(TrainerCallback):

    def on_step_end(self, callback_args, state, control, **kwargs):
        step = state.global_step + args.step_offset
        if not HF_TOKEN or step == 0 or step % HUB_PUSH_EVERY != 0:
            return
        try:
            push_repo = HF_REPO + "-checkpoints"
            print(f"\n[HubPush] Pushing checkpoint at step {step} to {push_repo}...", flush=True)
            model.push_to_hub(
                push_repo,
                token=HF_TOKEN,
                private=True,
                commit_message=f"checkpoint-step-{step}",
            )
            tokenizer.push_to_hub(
                push_repo,
                token=HF_TOKEN,
                private=True,
                commit_message=f"tokenizer checkpoint-step-{step}",
            )
            
            with open("./last_hub_push.txt", "w") as _f:
                _f.write(str(step))
            print(f"[HubPush] ✓ Step {step} pushed to HF Hub.", flush=True)
            if WANDB_API_KEY:
                wandb.log({"hub/last_pushed_step": step})
        except Exception as e:
            
            print(f"[HubPush] WARNING: push failed at step {step}: {e}", flush=True)

if not args.test:  
    trainer.add_callback(CheckpointPushCallback())
    print(f"HF Hub checkpoint push enabled every {HUB_PUSH_EVERY} steps → {HF_REPO}-checkpoints")
else:
    print("[TEST MODE] Hub checkpoint push disabled.")


print(f"\nStarting GRPO training. Max steps: {MAX_STEPS}")
print(f"Baseline solve rate: {baseline['solve_rate']:.1%} — target: >60% after training")
trainer.train(resume_from_checkpoint=args.resume)


model.eval()
bugs = load_bugs(1)[:20]
post_rewards = []
post_solved = 0
for bug in bugs:
    prompt = bug_to_prompt(bug)
    inputs = tokenizer(prompt, return_tensors="pt").to(RUNTIME_DEVICE)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=200, do_sample=False)
    completion = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    r = reward_fn([completion], [prompt], bug_metadata=[bug])
    post_rewards.append(r[0])
    if r[0] > 0.20:
        post_solved += 1

post_solve_rate = post_solved / max(len(bugs), 1)
print(f"\n{'='*60}")
print(f"RESULTS:")
print(f"Before training: {baseline['solve_rate']:.1%} solve rate")
print(f"After training:  {post_solve_rate:.1%} solve rate")
print(f"Improvement:     +{post_solve_rate - baseline['solve_rate']:.1%}")
print(f"{'='*60}")

if WANDB_API_KEY:
    wandb.log({"final/solve_rate": post_solve_rate, "final/improvement": post_solve_rate - baseline["solve_rate"]})
    wandb.finish()


model.save_pretrained("./final_model")
tokenizer.save_pretrained("./final_model")

if HF_TOKEN and not args.test:
    model.push_to_hub(HF_REPO, token=HF_TOKEN, private=True)
    tokenizer.push_to_hub(HF_REPO, token=HF_TOKEN, private=True)
    print(f"Pushed to https://huggingface.co/{HF_REPO}")