# Teaching LLMs to Debug Like Engineers, Not Gamblers

How we built a reinforcement learning environment that forces language models to reason before they act — and why that distinction matters more than most people think.

---

## The Problem With How LLMs Debug Code

Ask any LLM to fix a bug, and it'll give you an answer. Often it's even right. But watch what happens when the bug is subtle, or when the context spans multiple files, or when the model has seen something superficially similar but structurally different in training. The output devolves into what we started calling *"pattern-matching theater"* — the model produces plausible-looking fixes with high confidence, none of which address the actual root cause.

This isn't an intelligence failure. It's an incentive failure. Language models trained on static datasets learn to complete text, not to solve problems. They have no mechanism that rewards them for slowing down, forming a hypothesis, and testing it. So they don't.

We built *AgentDebuggerEnv* to change that incentive structure from the ground up — a reinforcement learning environment where the reward signal is explicitly designed to punish blind guessing and reward structured, hypothesis-driven debugging. The result: a model that learns to behave less like autocomplete and more like a junior engineer who actually reads the stack trace.

---

## What We Built

AgentDebuggerEnv is a training environment for fine-tuning code LLMs using *Group Relative Policy Optimization (GRPO)*. At its core, it enforces a strict cognitive loop on every agent action:


OBSERVATION → HYPOTHESIS → ACTION


No hypothesis, no reward. This isn't a soft nudge — it's a hard architectural constraint baked into the grading subsystem. The model learns that skipping the reasoning step is literally unprofitable.

The environment wraps this loop around a tiered curriculum of progressively harder Python bugs, evaluated inside a secure execution sandbox, with a hybrid grader that combines deterministic execution testing with LLM-based semantic evaluation of the reasoning quality.

Training is orchestrated via HuggingFace TRL's GRPO pipeline, with live metrics streaming to a Weights & Biases dashboard and a Gradio UI for real-time monitoring.

---

## Architecture: Five Systems, One Training Loop

Understanding the system requires understanding how its five components interact during a single training step.

### 1. The OpenEnv Core

The environment is built on *OpenEnv*, which manages state transitions across agent turns. Each episode begins with the agent receiving a buggy Python snippet. The state object tracks:

- The original buggy code
- The agent's current hypothesis
- The action taken (proposed fix)
- Execution output from the sandbox
- Cumulative reward signal

The core enforces episode structure: an agent cannot submit an ACTION without a preceding HYPOTHESIS in the same response. This is validated structurally before the grader ever runs.

### 2. The Grader Subsystem

This is where most of the engineering complexity lives. We built a two-layer grader:

*Hard Grader* — deterministic, execution-based:
- Runs the buggy code and captures the failure mode
- Executes the agent's proposed fix in an isolated sandbox
- Computes a delta: did the fix actually resolve the regression?
- Uses AST matching for structural equivalence checks

The hard grader specifically does not reward fixes that accidentally pass tests by sidestepping the bug (e.g., returning a hardcoded value). Early runs exposed this attack vector immediately — the model found it within the first 50 training steps.

*Soft Grader* — semantic, LLM-based (Llama-3.1-70B):
- Evaluates the quality of the hypothesis, independent of whether the fix worked
- Scores reasoning clarity, specificity, and causal accuracy
- Provides a partial reward signal even for correct diagnosis with an incorrect fix

This separation matters architecturally: it means the model gets a training signal for thinking correctly, not just for fixing correctly. A model that correctly identifies a null pointer dereference but writes a slightly wrong fix still learns something useful.

### 3. The Execution Sandbox

Evaluating arbitrary LLM-generated code is a Remote Code Execution (RCE) problem in disguise. Our sandbox:

- Replaces all exec() calls with a controlled execution harness
- Enforces CPU time limits and memory caps per execution
- Runs in a container-isolated environment
- Returns deterministic pass/fail signals with captured stdout/stderr

This took more engineering time than expected. The naive approach — just exec() the fix in a subprocess — fails immediately in a hackathon-grade RL loop because one adversarial output (import os; os.system("rm -rf /")) can destroy your training run.

### 4. The GRPO Training Pipeline

We chose GRPO over PPO for a practical reason: GRPO eliminates the need for a separate value network, which halves the VRAM requirement on constrained hardware. For a hackathon running on Colab T4s, this isn't a nice-to-have — it's the difference between training and not training.

The pipeline uses HuggingFace TRL with LoRA adapters on *Qwen2.5-Coder-7B-Instruct*. Hardware detection at runtime automatically configures:

| Hardware | batch_size | grad_accum | dtype |
|---|---|---|---|
| A100/H100 | 8 | 2 | bfloat16 |
| T4 | 2 | 8 | float16 |

This isn't just convenience — it's the reason our notebook runs reproducibly for judges on any GPU tier without manual config edits.

### 5. The Live Monitor

A Gradio dashboard streams stdout and W&B metrics directly from the active training container. This served two purposes: debugging during development, and providing judges with live evidence of the training run rather than static screenshots.

---

## The Curriculum: Why Flat Bug Distributions Fail

One of our most important design decisions came from a failure.

In early runs, we trained on a flat distribution of bugs — syntax errors, logic flaws, and type errors all mixed together. The policy collapsed within 100 steps. The model found a local optimum: memorize the three most common bug patterns, ignore everything else.

We implemented a *3-tier curriculum*:

- *Tier 1:* Structural formatting bugs, missing brackets, simple syntax errors
- *Tier 2:* Localization bugs — correct syntax, wrong variable or index
- *Tier 3:* Logic bugs — semantically plausible but algorithmically incorrect code

The agent only encounters Tier 2 bugs after Tier 1 format compliance stabilizes (monitored via the W&B dashboard). Tier 3 unlocks after Tier 2 localization accuracy crosses a threshold. The training curve shows a textbook drop-and-recover at step 150 — the Tier 2 transition — followed by steady policy improvement.

This is *curriculum learning applied to code reasoning*, and it's not a new idea in RL (it traces back to Bengio et al., 2009), but applying it to LLM fine-tuning in this structured way is still relatively underexplored. The NeurIPS 2025 work on hypothesis-driven debugging ([arXiv:2408.10215](https://arxiv.org/abs/2408.10215)) and Amazon's findings on LLM reasoning ([arXiv:2601.19100](https://arxiv.org/abs/2601.19100)) both informed our reward shaping architecture.

---

## Results: What 250 Steps Actually Looks Like

The training curves tell a clear story:

- *Format Compliance* hit 1.0 within 50 steps and stayed there — the model learned the OBSERVATION/HYPOTHESIS/ACTION structure immediately and never broke it.
- *Total Reward* climbed from a baseline of ~0.4 to peaks of ~1.0 by step 250, representing roughly a 2.5x improvement in overall policy quality.
- The *Tier 2 transition at step 150* is visible as a transient dip — the policy briefly destabilizes when harder bugs appear, then recovers. This is the signature of a healthy curriculum; an unhealthy one would see permanent regression.

A 100% validation solve rate on tiered data structure bugs confirms the model isn't just gaming the reward function — it's developing a generalizable debugging policy within its training distribution.

---

## Engineering Trade-offs Worth Noting

*GRPO vs PPO:* GRPO's advantage is memory efficiency. Its disadvantage is that it can exhibit higher variance in early training. For a 250-step run, this trade-off is favorable. For longer runs at scale, PPO's stability properties may become more attractive — a direct comparison on this task would be a valuable follow-up experiment.

*LLM-as-a-Judge for Hypothesis Quality:* Using Llama-3.1-70B to evaluate hypothesis quality is semantically powerful but expensive and non-deterministic. We deliberately isolated this to hypothesis scoring only (not execution correctness), which limits the blast radius of its non-determinism. If cost is a constraint, this could be replaced with a smaller fine-tuned scorer — though you'd sacrifice some semantic nuance.

*Single-file scope:* The current environment operates on isolated Python snippets, not multi-file repositories. Real production bugs rarely present this cleanly. The environment is a training tool, not a deployment tool — this scope is intentional for now, but it's the primary limitation on real-world transfer.

---

## How the System Flows, End to End


1. Episode starts → agent receives buggy Python snippet

2. Agent produces structured response:
   OBSERVATION: [what the agent notices about the code]
   HYPOTHESIS:  [specific causal claim about the bug]
   ACTION:      [proposed fix]

3. Environment validates structure → no hypothesis = zero reward

4. Hard Grader runs:
   → Execute buggy code, capture failure signature
   → Execute proposed fix in sandboxed harness
   → Compute regression delta
   → Return binary execution reward

5. Soft Grader runs:
   → Send hypothesis to Llama-3.1-70B evaluator
   → Score reasoning quality (0.0 – 1.0)
   → Return semantic reward

6. Combined reward signal fed to GRPO update

7. W&B logs step metrics → Gradio dashboard updates live

8. Curriculum manager checks tier thresholds → escalates if ready


---

## What We'd Build Next

*Multi-file repository debugging* is the obvious next frontier. The current single-snippet scope is a necessary simplification for training stability, but real debugging involves tracing across call stacks, imported modules, and shared state. An LSP integration that gives the agent a live view of the codebase — with go-to-definition and symbol resolution — would transform this from a toy into a tool.

*Adversarial bug generation* is the more interesting research direction. Instead of a static tiered dataset, an adversarial LLM agent continuously mutates bugs to exploit the current policy's weaknesses. This creates a self-sustaining curriculum that doesn't plateau — the harder the primary agent gets, the harder the adversary makes the bugs. It's essentially a GAN applied to code reasoning.

*PPO vs GRPO benchmarking* on this specific task would produce publishable findings. The community has strong priors about when each algorithm excels, but empirical data on structured reasoning tasks with custom multi-objective rewards is sparse.

---

## Summary

AgentDebuggerEnv demonstrates that you can use reinforcement learning to teach an LLM to reason about bugs rather than pattern-match fixes. The key architectural choices — mandatory hypothesis formation, regression delta verification, curriculum learning, and hybrid deterministic/semantic grading — work together to close the gap between "outputs that look like debugging" and "outputs that actually debug."

The results are real: 2.5x reward improvement in 250 steps, zero reward hacking after grader hardening, and a training pipeline that runs reproducibly on hardware ranging from Colab T4s to A100 clusters.

More importantly, the architecture is extensible. Every component — the grader, the curriculum, the reward function, the sandbox — is modular and independently swappable. If you want to apply this framework to a different debugging domain, a different model family, or a different reward philosophy, the foundation is already there.

We built this in a hackathon sprint. We think it's worth building further.

---

Built by Team Endurance — Shashaank Jain & Pranav Pulipati — for the Scaler × Meta × PyTorch Hackathon.

[Live Space](https://huggingface.co/spaces/shashaank0707/AgentDebugger-training-v3) · [W&B Run](https://wandb.ai/shashaankjain07-keshav-memorial-college-of-law/AgentDebuggerEnv/runs/vylbqd5m?nw=nwusershashaankjain07) · [GitHub: @shasshaank](https://github.com/shasshaank)