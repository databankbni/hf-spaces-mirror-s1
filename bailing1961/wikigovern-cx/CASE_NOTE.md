# WikiGovern-CX - Case Note

## What problem does this solve?

Retail groups with several brands hold customer data in separate
systems. Marketing, analytics and partner teams constantly ask: "can we
use this data for that?" Today the answer lives in scattered contracts,
privacy policies and tribal knowledge - so teams either move slowly or
take risks without knowing it.

WikiGovern-CX is an agent that answers that question instantly, with
receipts. Every answer is decided by written rules compiled from the
actual source documents (privacy principles, retention policies,
partner contracts), and every "no" tells you exactly which rule said no
and which document that rule came from.

## Who is it for?

Data, analytics, marketing and privacy teams in multi-brand consumer
businesses, and the partners they share data with.

## What do you put in?

A question about using customer data, built from four choices:
which data (one brand, a cross-brand join, or an aggregate), for what
purpose (service, marketing, internal analytics), for which records
(optional filters), and - for analytics - which approved use case.

## What do you get out?

One of three answers, per record, never a guess:
- ALLOW - every selected record may be used for that purpose.
- PARTIAL / DENY - some or all records are blocked, with a count per
  rule and a citation chain: rule -> policy statement -> source
  document and clause.
- UNKNOWN - the information needed to decide safely was never captured
  (for example, consent without a date). Unknown always beats allow:
  the agent refuses to guess.

Plus a standing audit report (the "4C" report): whether every rule
traces to a source, whether any rules contradict each other (found by a
formal solver, not by eyeballing), which fields mean different things
across brands, what goes stale when a contract changes, and which
regulation clauses have no rule yet.

## Safety boundaries (read this part)

- All customer data in this demo is SYNTHETIC - generated for the demo,
  with defects planted on purpose so the audit has something real to
  find. No real person appears here.
- The agent never lets a language model decide permission. Verdicts and
  date arithmetic are deterministic code over compiled rules.
- Identity matching between brands can only make the agent stricter,
  never looser. A matching error over-blocks; it cannot leak.
- Records under a deletion request are excluded from everything,
  including the matching step.
- When two rules genuinely conflict (this demo ships one real conflict
  between a retention policy and a partner contract), the agent blocks
  use, keeps the records, and escalates the conflict to humans. It does
  not pick a side silently.
- This is a research demonstrator, not legal advice, and not a
  substitute for your privacy counsel.

## What is deliberately not shown

The compiler that turns policy documents into rules, the conflict
scanner, the audit harness, the approval workflow and the deployment
tooling are private. This demo shows their OUTPUTS working end to end.
