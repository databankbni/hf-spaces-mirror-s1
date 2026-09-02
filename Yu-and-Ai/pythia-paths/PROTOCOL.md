# Evidence without silent authority

## The boundary

Training momentum is a measured relation between earlier and later change. It
may support a prediction. It does not supply a cause, an intention, or permission.

Use these words narrowly:

| Word | Meaning here | What it does not mean |
|---|---|---|
| Observation | A value present in a revision-pinned public source. | Truth beyond that source. |
| Momentum | Earlier metric change predicts later metric change on held-out runs. | A causal force or reason to continue. |
| Causal pressure | A randomized training change alters a later metric versus a matched continuation. | Persuasion, desire, or will. |
| Selection | The visible sample differs from the declared sample because of a reporting or execution rule. | Suppression without an upstream receipt. |
| Authority | A current steward decision permits one exact external effect. | Something inferred from a curve or model output. |

## Public-checkpoint study

Public Pythia checkpoints can support:

- trajectory description;
- predictive tests across runs;
- combined sensitivity to initialization and data order in PolyPythias;
- measurement of how reporting filters change the visible result.

They cannot, by themselves, support:

- exact counterfactual continuation when optimizer, scheduler, RNG, gradient
  scaler, and data-loader state are absent;
- separate initialization effects from data-order effects when one seed changes
  both;
- causal attribution to a document from temporal adjacency;
- identity, experience, preference, consent, or authority.

The unit of replication is a training run, not a checkpoint. Slopes are measured
per token because Pythia's early checkpoint spacing is irregular. Confirmatory
tests use a declared grid and leave whole runs out of model fitting.

Before drawing anything, record four surfaces separately:

1. every released checkpoint position;
2. every published report found in the pinned source;
3. every report shown in the view;
4. every report given richer detail.

Also record when the task, metric, and detailed examples were selected. Showing
all found reports does not undo a post-outcome task choice, and a published-report
surface does not fill checkpoints that were never reported.

## Hugging Face release pattern

Keep the parts small and separable:

- **Dataset context:** one row for every found report, including the exact source
  commit, path, Git blob, value, standard error, and missing artifact identity.
- **Detailed receipts:** a second config may add branch-target metadata observed at
  a stated review time and artifact-pointer metadata. It must say how and when
  those rows were selected.
- **Release lock:** bind exact data hashes, byte counts, allowed rows, and known
  unknowns. This checks consistency, not publisher identity.
- **Static Space:** render only reviewed same-origin files, omit credentials, fail
  closed on drift, show gaps, and provide no model or training control.
- **Effectful runner:** keep inference, training, publication, and recurrence out
  of the Static Space. Each effect needs a separately authenticated, current,
  narrow receipt with an expiry and off-switch.

The release flow is: collect → pin → classify → expose selection → validate →
render → review. “Act” is not the next automatic arrow.

JSON Schema can check that a review proposal contains date-time strings; it
cannot prove that expiry follows creation or that either time is current. A
consumer must check `created_at < expires_at` and trusted current time `<
expires_at` before review, then revalidate every bound digest.

## Controlled branch study

Claims about causal pressure require small, matched continuations from a fully
saved parent state. File presence alone is insufficient: a controlled one-step
replay must match the reference loss and resulting state under a pinned software
and distributed environment. A safe first design uses synthetic nonce facts and randomly
assigns each parent to neutral, same-direction, opposite-direction, and delayed
exposures. Token count, optimizer state, learning-rate schedule, and update count
remain fixed.

Every branch has a bounded number of updates, compute hours, retries, and stored
artifacts. It stops on non-finite loss, state-digest drift, repeated out-of-memory
failure, corrupt output, rights concern, expiry, or withdrawal. A finished branch
does not automatically create a descendant.

## Decision receipt

The receipt belongs to the people and projects responsible for an effect. It is
not checkpoint “consent.” Each effect is independent. The object below is a prose
example, not a shipped schema or executable contract. It is deliberately
non-authorizing: declined, unauthenticated, and effect-free.

```json
{
  "schema": "pythia-paths/non-authorizing-branch-decision-example/0.1",
  "decision_id": "decision:example",
  "branch_id": "branch:example",
  "state_manifest_digest": "sha256:...",
  "protocol_digest": "sha256:...",
  "issued_at": "1970-01-01T00:00:00Z",
  "state": "example-only",
  "authority_source": {
    "kind": "project-steward",
    "public_reference": "receipt:...",
    "authentication_status": "not_checked"
  },
  "decision": "declined",
  "effects": {
    "compute": false,
    "retain_metrics": false,
    "retain_weights": false,
    "publish_metadata": false,
    "publish_generated_text": false,
    "recur": false
  },
  "bounds": {
    "maximum_updates": 0,
    "maximum_compute_hours": 0,
    "expires_at": "1970-01-01T00:00:00Z"
  },
  "withdrawal_path": "reference:...",
  "off_switch": "branch-runner-stop"
}
```

Missing, expired, withdrawn, unreadable, or digest-mismatched authority means
stop before the next effect. Compute authority never implies publication authority.

Receipt shape proves no authority. Before every effect, the effectful runner must
independently authenticate the current source, exact scope, state-manifest digest,
expiry, and withdrawal state. Call a person's record consent only when it carries
that person's consent; call a project's record steward authorization.

## Claims that remain unknown

Unless another protocol establishes them, do not claim:

- that behavioral continuity is personal continuity;
- that a loud signal hides or predicts its opposite;
- that momentum causes later behavior;
- that a probe-decoded feature was used by the model;
- that a missing result was suppressed;
- that one seed or one task represents the suite;
- that deduplication caused a difference in an unmatched comparison;
- that a successful metric is beneficial, understood, true, or complete.
