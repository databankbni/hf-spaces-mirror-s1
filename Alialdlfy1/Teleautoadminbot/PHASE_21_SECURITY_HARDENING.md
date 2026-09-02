# PHASE 21 — Security, Secrets & Production Hardening

- Added runtime secret-value redaction and security findings.
- Added RBAC for control-plane sensitive operations.
- Added encrypted SecretManager master-key rotation without changing existing secret names.
- Existing SecretRegistry discovery and legacy environment names remain untouched.
- Sensitive repair/rollback/rotation actions can be restricted to admin.
- Added security regression tests.
