# Deterministic execution-integrity gate

This revision prevents invalid hydraulic arrays from being presented as
successful SWMR results.

## Changes

1. Dynamic-wave preflight recognizes explicit zero values for `MAX_TRIALS`,
   `HEAD_TOLERANCE`, and `MIN_SURFAREA` as legacy/default sentinels. It creates
   an immutable derivative execution copy using unit-aware effective defaults,
   while preserving and hashing the original upload. Negative and non-numeric
   values remain blocking errors. Omitted values remain untouched.
2. Post-run integrity classification records `valid`, `limited`, or `invalid`
   using routing convergence and flow-routing continuity evidence.
3. A run is invalid when every routing step fails, at least 5% of routing
   steps fail, or the routing continuity error is at least 10%.
4. Invalid hydraulic arrays remain available in the audit database, but node,
   link, storage, control, capacity, spill, and depth-velocity conclusions are
   set to `Not assessed - hydraulic routing solution invalid`.
5. The executive summary and model identity disclose the execution gate.
6. Calgary screening returns no pass/fail hydraulic results for an invalid run.
7. Regression tests cover the Kincora zero-value failure and the corrected
   usable-run metadata.

## Kincora failure reproduced

The legacy input explicitly contained:

```ini
MAX_TRIALS       0
HEAD_TOLERANCE   0
```

The EPA SWMM 5.2 desktop interface resolves these values to effective defaults.
For SI models the derivative uses `MAX_TRIALS=8`, `HEAD_TOLERANCE=0.0015 m`,
and `MIN_SURFAREA=1.167 m2`. Every substitution, both hashes, and both INP files
are retained in the audit package. This is a disclosed compatibility action,
not a mutation of the uploaded engineering model.

## Validation

- Python compilation passed for all packaged modules.
- 35 deterministic unit checks passed.
- Preflight integration requires the Space dependencies and isolated
  OpenSWMM worker environment described in the existing README.
