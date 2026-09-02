# Phase 9 — AI Auto-Repair: Sandbox + Tests + Rollback

AI never writes directly to production.

Flow:
1. Error is classified outside the repair engine.
2. AI proposes a unified diff patch.
3. PatchSandbox rejects protected paths and traversal.
4. Patch is applied to an isolated copy.
5. Python compile + selected tests run in sandbox.
6. Only a passing patch may be applied.
7. Original files are backed up before apply.
8. Health monitoring can trigger rollback if the repaired service becomes unhealthy.

Protected by default:
- secrets / credentials / tokens / keys
- `.env`
- runtime `data/`
- sessions
- `.git`

This is deliberately conservative. Provider-specific AI proposal logic is not hard-wired here; it should use the existing AI Gateway and only return a patch.
