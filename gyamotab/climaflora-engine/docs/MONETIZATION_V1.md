# ClimaFlora monetization v1

The subscription plumbing is implemented. The Supabase runtime migration was
applied to project `haclvcuxadvuigtefeqz` on 2026-08-24. Stripe Checkout stays
disabled until sandbox keys, Prices and a webhook signing secret are configured.

## Product mapping

| Public offer | Internal plan | Monthly | Annual |
| --- | --- | ---: | ---: |
| Découverte | FREE | €0 | €0 |
| Plus | PLUS | €8.90 | €97 |
| Pro | PRO | €17.90 | €197 |

The live Stripe catalog contains separate Products for Plus and Pro, each with
monthly and annual recurring Prices. Configure the Customer Portal to cancel at period end.
Enable Smart Retries and failed-payment emails in the Stripe Dashboard.

The production webhook endpoint `we_1U7t157pMOezeNU3kGltup6S` targets
`https://gyamotab-climaflora-engine.hf.space/api/v1/billing/webhook`. It remains
disabled until its signing secret and a restricted Stripe key are installed in HF.

## Required server secrets

- `CLIMAFLORA_SUPABASE_URL`
- `CLIMAFLORA_SUPABASE_ANON_KEY`
- `CLIMAFLORA_SUPABASE_SERVICE_ROLE_KEY`
- `CLIMAFLORA_STRIPE_RESTRICTED_KEY` (least-privilege `rk_` key)
- `CLIMAFLORA_STRIPE_WEBHOOK_SECRET`
- `CLIMAFLORA_STRIPE_PRICE_PLUS_MONTHLY=price_1U7ssA7pMOezeNU3ZX3Txwu7`
- `CLIMAFLORA_STRIPE_PRICE_PLUS_YEARLY=price_1U7srv7pMOezeNU3OeoGXz7L`
- `CLIMAFLORA_STRIPE_PRICE_PRO_MONTHLY=price_1U7ss77pMOezeNU34I3KrzuV`
- `CLIMAFLORA_STRIPE_PRICE_PRO_YEARLY=price_1U7ss17pMOezeNU3kTXFBHMG`

Use separate test and production keys. Never expose restricted/service-role keys
to OVH JavaScript, logs, committed env files, or error responses.

## Tax gate

`automatic_tax` is intentionally absent. Before enabling it, confirm the Stripe
Tax head-office setting, the appropriate product tax code and at least one active
tax registration with the business's tax adviser. Enabling automatic tax alone
does not collect tax without a registration.

## Safe rollout

1. Keep the applied Supabase migration under version control.
2. Create and verify a Stripe webhook endpoint.
3. Set the live Price IDs and restricted Stripe key in HF, then set `BILLING_ENABLED=true`.
4. Exercise checkout, portal, renewals, replayed/out-of-order events and failed payments.
5. Run tests and a secret scan, then perform a manual security review.
6. Keep Stripe Tax disabled until an active registration and tax treatment are confirmed.

Rollback: disable `CLIMAFLORA_BILLING_ENABLED`; existing scientific search remains
available and all paid access resolves fail-closed to FREE when subscription state
is missing or inactive.
