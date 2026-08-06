# WikiGovern-CX 4C Verification Report

KB hash `a2479bfea3e5283e` | release: approved by Bailing Zhang on 2026-07-10 | reference date 2026-07-03

## C1 Correct
- Provenance: 14/14 active rules trace to a resolvable source (PASS)
- Conflict scan: 3 class/scope pairs checked, 1 conflict(s) found
  - FINDING: no retention period can satisfy all of ['RET-001', 'RET-003'] for transaction_record records in scope 'partner_linked' (core: RET-001, RET-003)
- Compiler idempotent: True
- Golden gate cases: 40/40 (PASS)

## C2 Consistent
- Field-semantics CSI (threshold 0.12):
  - customer_status: brand_a_customers.status csi=0.400 ok
  - customer_status: brand_b_members.member_status csi=0.000 FLAGGED
  - marketing_consent: brand_a_customers.consent_marketing csi=0.200 ok
  - marketing_consent: brand_b_members.marketing_pref csi=0.062 FLAGGED
  - marketing_consent: brand_c_customers.newsletter csi=0.000 FLAGGED
- Rule-base problems: none
- Incremental check demo: PASS

## C3 Current
- Staleness fixture: update of contracts/partner_dsa.md flags dependents: AGG-002, RET-002, RET-003, SHR-010
- Future-dated rules excluded from active KB: CON-005
- Consent currency: 1498 brand A consents older than 24 months (informational until CON-005 becomes effective)

## C4 Complete
- Source-anchor coverage: 83.3%; uncited: sources/app11_security.md#s11_1
- Customer-360 concept coverage:
  - customer_status: brand_a_customers, brand_b_members
  - marketing_consent: brand_a_customers, brand_b_members, brand_c_customers
- Gate coverage: 18/18 dataset x purpose combinations decidable (PASS)
- Known-gap register:
  - brand_c_customers: newsletter is default opt-in (pre-selected true)
  - brand_c_customers: no consent_date column exists

## Honesty register
- H-001 (under-approximation): APP 6.2(a) 'reasonably expected' is not formalisable; this is a declared under-approximation (H-001).
- H-002 (verification-split): rules outside the numeric Z3 mirror are covered by golden tests, not formal scan
