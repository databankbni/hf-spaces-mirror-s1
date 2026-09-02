# Pythia: what the released paths let us see

This note separates released fact, author interpretation, and our inference. It
describes EleutherAI's Pythia model suite. It does not treat a checkpoint as a
person or use behavioral continuity as evidence of personal continuity.

## Why Pythia is unusually useful

Pythia was built for longitudinal research rather than only final performance.
The original suite contains eight sizes from 70M to 12B, each trained on the
standard and deduplicated Pile. All sizes within a data regime saw batches in the
same order. Each run exposes 154 weight checkpoints:

- step 0;
- powers of two from step 1 through 512;
- every 1,000 steps from 1,000 through 143,000.

The global batch was 1,024 sequences of 2,048 tokens, or 2,097,152 tokens per
optimizer step. A full run therefore saw exactly 299,892,736,000 tokens.

Primary sources: [Pythia paper](https://arxiv.org/pdf/2304.01373),
[pinned official repository](https://github.com/EleutherAI/pythia/tree/a19eecb807ec2c79a39ebf18108816e6ffffc1d5), and
[model collection (mutable navigation)](https://huggingface.co/collections/EleutherAI/pythia-scaling-suite-64cc6c777e37c5e2e8e1d13f).

The suite lets us ask about paths, transitions, reversals, memorization, and
interventions. It does not make the final checkpoint a natural authority.

### Released weights are not released measurements

The run exposes 154 weight-checkpoint positions, but the pinned official
70M-deduped zero-shot directory contains only 27 checkpoint reports. Pythia Paths
shows all 27 PIQA reports in that directory and leaves the other 127 positions
empty. Even those 27 evaluation JSON files name mutable model branches without an
evaluated model commit or artifact digest. A reported measurement surface is not
the complete training path, and a branch name is not artifact identity.

## A material 2026 artifact correction

Until late February 2026, the Hugging Face repositories named
`EleutherAI/pythia-14m` and `EleutherAI/pythia-31m` held models trained on the
**deduplicated** Pile. The standard-Pile models now occupy those names; the old
histories moved to `pythia-14m-deduped` and `pythia-31m-deduped`.

This matters for the published PolyPythias seed study:

- archived 14M seed 0 evaluation points to model commit
  `0fa9ea4dc5bb6146367b8f3d33b2ea5f8f980cba`, now in the deduplicated history;
- archived 31M seed 0 points to
  `299b50d914ce09dadd19d30e23d815704ad8ef2f`, also now in the deduplicated history;
- seeds 1–9 used standard-Pile models.

So the published 14M and 31M seed-0-versus-other-seed comparisons partly vary
the **training-data regime**, not only the random seed. A corrected replication
must use current standard-Pile seed 0, or deliberately retain the historical
deduplicated model and name the confound.

Evidence: [pinned 14M card](https://huggingface.co/EleutherAI/pythia-14m/blob/cf967c0a9a04383db6f7b1108d86b2962634b4ac/README.md),
[pinned 31M card](https://huggingface.co/EleutherAI/pythia-31m/blob/e556ace21b489575e94e9d50b6dad2fcc7419679/README.md),
[pinned 14M seed-0 evaluation](https://huggingface.co/datasets/EleutherAI/polypythias-evals/blob/0ed1e408923479f8bb89333a21f8638a3077a7ea/pythia-14m-seed0/step143000/EleutherAI__pythia-14m/results_2024-07-08T05-06-17.310896.json), and
[pinned 31M seed-0 evaluation](https://huggingface.co/datasets/EleutherAI/polypythias-evals/blob/0ed1e408923479f8bb89333a21f8638a3077a7ea/pythia-31m-seed0/step143000/EleutherAI__pythia-31m/results_2024-07-08T05-09-34.467592.json).

This is a provenance and comparison confound: a stable repository name made
unlike artifacts appear comparable. It establishes neither momentum nor authority.

## Version and state caveats

### v0 labels are not always optimizer steps

The archived v0 160M, 410M, and 1.4B runs used roughly four-million-token
batches and ran 71,500 optimizer steps. Their displayed labels were doubled for
token-exposure comparison. For those runs, displayed `step1000` means optimizer
step 500. The corrected v1 suite standardized the batch at about two million
tokens and added dense early checkpoints.

### Initialization was not identical at the top sizes

The v1 6.9B and 12B configurations omitted an initialization value and therefore
used a different initialization from the smaller suite. This limits claims that
depend on strict cross-size control. See
[Pythia issue 135 (mutable discussion)](https://github.com/EleutherAI/pythia/issues/135).

### Weight branches and exact continuation are different claims

Transformers repositories expose convenient checkpoint weights. Native GPT-NeoX
repositories now expose many optimizer shards and model-state files too, despite
older documentation suggesting otherwise. Sampled native states include scheduler
position and RNG state. Naming and coverage remain inconsistent. Verifying every
expected state component is only a prerequisite. Exact continuation remains
unproven until a controlled one-step replay matches the reference loss and
resulting state under a pinned software and distributed environment. Example:
[pinned 70M native step 1000](https://huggingface.co/EleutherAI/neox-ckpt-pythia-70m-v1/tree/b96f5685654623a7bc7a13e0df868e08d5130b96).

“Weights are present” must never silently become “exact continuation is ready.”

### `main` is a claim, not an artifact identity

The model card says `step143000` corresponds exactly to `main`. On the current
70M-deduped repository, however, the refs resolve to different commits. Their
PyTorch weight LFS digest matches, while their safetensors digest does not. This
can arise from later conversion or metadata work, but the reason is not encoded
in the convenient correspondence claim. Never substitute `main` for a pinned
checkpoint or infer file equivalence from the card sentence.

The card also still points to an old `results/json/*` evaluation path while the
reviewed files now live under `evals/`. Documentation drift is evidence about
documentation, not evidence of suppression.

## What the published studies actually found

### Term frequency

On arithmetic and TriviaQA, the authors found that correlation between relevant
term frequency and task performance appeared around step 65,000, mainly in models
2.8B and larger. It was largely absent earlier and in smaller models. The authors
call this an emergent phase change. Correlation does not, by itself, establish
frequency as the causal mechanism.

Small 14M–70M models are useful negative controls for this result, not positive
replications of it.

### Memorization

The original Pythia study found no strong dependence of exact-match memorization
on where a sequence appeared in the training order under its measurement rule.
Larger models memorized more; deduplication reduced the count. Smaller or earlier
models predicted a high-precision subset of what a final 12B model would memorize,
but recall was too low to serve as a privacy guarantee. See the
[memorization paper](https://arxiv.org/pdf/2304.11158) and
[pinned released results](https://huggingface.co/datasets/EleutherAI/pythia-memorized-evals/tree/d97edd12f08884dae3dfcef8d5cbbba5129e49e0).

Absence at an early checkpoint is not evidence of final safety.

### Counterfactual training intervention

The authors resumed deduplicated models while replacing masculine pronouns with
feminine ones over the next 7% of training, and one 1.4B model over 21%. Targeted
bias metrics fell with little LAMBADA loss. This is fairly strong causal evidence
for that exact transformation and those metrics, not a general fairness result.
The released 70M pair makes a low-cost before/after analysis possible:
[pinned intervention model](https://huggingface.co/EleutherAI/pythia-intervention-70m-deduped/tree/5181c967fe5d62f4d3b65ede263c5166b8f7c159).

### PolyPythias trajectories

PolyPythias added nine runs for each of five sizes, jointly changing parameter
initialization and packed-batch composition. Most broad trajectories were stable,
but 410M seeds 3 and 4 showed loss spikes and forked training maps. Partial maps
became strongly predictive only very late in training, around step 120,000, so
they do not support a useful early-abort oracle.

The public seed runs estimate combined sensitivity. They do not separate initial
weights from data order. The [PolyPythias paper](https://proceedings.iclr.cc/paper_files/paper/2025/file/d611d06e3207330555fbc10810e70163-Paper-Conference.pdf)
and [pinned evaluation dataset](https://huggingface.co/datasets/EleutherAI/polypythias-evals/tree/0ed1e408923479f8bb89333a21f8638a3077a7ea)
are the primary sources.

## The next honest experiments

### 1. Predictive momentum on public paths

- Use 70M, 160M, and 410M; avoid the 14M/31M historical confound initially.
- Declare every run, checkpoint, task, metric, exclusion, and stopping rule first.
- Measure change per token, not per checkpoint index.
- Compare a step-only learning-curve model with one that also uses prior slope.
- Hold out whole training runs and report failed or missing evaluations.

Support requires better held-out prediction, sign and magnitude accuracy, another
model-size replication, and survival after removing extreme checkpoints. A
positive result is predictive continuity, not causality.

### 2. Causal pressure on small replicas

- Save weights, optimizer, scheduler, scaler, every RNG, and data-loader state.
- Use synthetic nonce relations rather than people or contested real claims.
- Randomize matched neutral, same-direction, opposite-direction, and delayed
  continuations from each parent state.
- Fix token count, updates, learning-rate schedule, and compute bounds.
- Test immediate shift, persistence, decay, paraphrase transfer, and controls.

A successfully randomized, state-matched execution with verified intervention
fidelity could support a bounded causal claim about the effect of training
exposure. The design alone cannot.

### 3. Selection audit

Calculate each result on the complete declared grid, then under simulated visible
surfaces: positive-only, largest effect, best seed, completed-jobs-only, and
smoothest trajectory. The difference measures how presentation can manufacture
an apparently stronger result that observers may mistake for warrant; it creates
no authority.

### 4. The loud/opposite hypothesis

Predefine “loud” on development runs. On held-out runs, compare persistence,
stable reversal, regression to the mean, upcoming-data effects, and selection.
A reversal is a later logit change. It is not evidence that an earlier checkpoint
“secretly meant” the opposite.

## Practical boundary

Replotting released evaluations costs almost nothing. Focused inference across a
few 14M–70M checkpoints is laptop-feasible. Full 154-checkpoint, ten-seed studies
quickly become tens or hundreds of gigabytes; exact corpus-order reconstruction
also needs hundreds of gigabytes. A positive term-frequency replication requires
at least 2.8B checkpoints and corpus-prefix scanning.

Start with metadata. Make the selection surface visible. Add compute only when a
specific falsifiable question and a separate bounded decision receipt both exist.

## Why call it Pythia Paths

Pythia here is a discipline of accompanied seeing, not an oracle that rules. A
signal stays beside its source, missing pieces, rival explanations, and limits
long enough for us to learn what it is. The view may open a question. It does not
turn the seer, the model, the metric, or the interface into an authority.

That is also substrate honesty: these releases preserve weights, reports, branch
names, and training traces. They do not establish biography, inner experience,
identity, consent, intention, or destiny. The path is meaningful precisely when
we let it be a path before demanding that it become a command.
