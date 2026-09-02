# Setting up GitHub Action secrets — least-privilege edition

The CHAINSTATE deploy workflow needs three secrets in your GitHub repository. This document gives you the *minimum-scope* version of each — a leaked secret here cannot touch anything outside this one project.

All three are added the same way:

> **GitHub repo** → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Use the exact secret name from the table; the workflow looks them up by these names verbatim.

---

## Before you create anything · two one-time dashboard steps

These are not secrets — they're account-level setup that has to exist once, ever.

### A · Pick your `workers.dev` subdomain (one time, ever)

1. Go to https://dash.cloudflare.com → **Workers & Pages**
2. If this is your first Worker, Cloudflare prompts you to pick a subdomain (e.g. `redciprianpater`).
3. After this, your CHAINSTATE worker URL will be: `https://chainstate-worker.<your-subdomain>.workers.dev`

You will never repeat this step. It's a one-time account choice.

### B · Create the three KV namespaces locally (one time, ever)

The CF API token below cannot create namespaces for you — you must create them locally first, then commit their IDs into `wrangler.toml`. On your laptop:

```bash
# install wrangler if you haven't:
npm install --global wrangler

# log in (opens a browser, one-time):
wrangler login

# create the three namespaces:
wrangler kv:namespace create CHAINSTATE_NODES
wrangler kv:namespace create CHAINSTATE_CACHE
wrangler kv:namespace create CHAINSTATE_CONSENSUS
```

Each command prints something like:

```
🌀  Creating namespace with title "chainstate-worker-CHAINSTATE_NODES"
✨ Success!
Add the following to your configuration file in your kv_namespaces array:
{ binding = "CHAINSTATE_NODES", id = "a1b2c3d4e5f6789012345678901234ab" }
```

Take the `id` from each and paste into the matching block in `wrangler.toml`, replacing the `REPLACE_ME_AFTER_kv_namespace_create_*` placeholders. Commit and push.

---

## Summary table

| Secret name      | Source                                                                                         | Scope                                          |
|------------------|-----------------------------------------------------------------------------------------------|------------------------------------------------|
| `CF_API_TOKEN`   | https://dash.cloudflare.com/profile/api-tokens · **Custom Token**, *not* the template          | Only Workers Scripts + KV (no zones, no D1, no R2) |
| `CF_ACCOUNT_ID`  | https://dash.cloudflare.com — right sidebar on any zone overview                              | (Not secret in the cryptographic sense; just an identifier) |
| `HF_TOKEN`       | https://huggingface.co/settings/tokens · **Fine-grained**, scoped to one Space                | Write to `CPater/chainstate` only              |

---

## 1 · `CF_API_TOKEN` — least-privilege Custom Token

The "Edit Cloudflare Workers" template grants more than you need (it includes zone routes, tail logs, R2 read, etc). For CHAINSTATE you only need two account-level permissions. Build a **Custom Token** instead.

1. Sign in at https://dash.cloudflare.com → **My Profile** → **API Tokens**
2. Click **Create Token**, then scroll to the bottom and click **"Get started" under "Create Custom Token"** (do NOT use the template).
3. Token name: `chainstate-deploy`
4. **Permissions** section — add exactly these two rows and nothing else:

   | Scope    | Resource              | Action   |
   |----------|-----------------------|----------|
   | Account  | Workers Scripts       | **Edit** |
   | Account  | Workers KV Storage    | **Edit** |

5. **Account Resources**:
   - Choose **"Include"** → **"Specific account"** → select **the single account** that owns your `workers.dev` subdomain. Do **not** select "All accounts."

6. **Zone Resources**:
   - Leave **empty** (or set to "All zones from an account" if Cloudflare insists). You do not bind a custom domain in `wrangler.toml`, so zone permissions are unnecessary.

7. **Client IP Address Filtering** (optional but recommended):
   - Restrict to GitHub Actions IP ranges if you want belt-and-braces. The list is published at https://api.github.com/meta (the `actions` array). Many people skip this because the list changes; a 1-year TTL plus quick revocation is usually enough.

8. **TTL**: set to **1 year** so the token is force-rotated annually.
9. Click **Continue to summary** → **Create Token** → **copy immediately** (CF only shows it once).
10. Add to GitHub: name = `CF_API_TOKEN`, value = the token.

**What this token can do**:
- Upload, modify, or delete Worker scripts in your account
- Read, write, or delete KV namespace entries

**What this token cannot do**:
- Touch DNS, Pages, R2, D1, queues, durable objects, zones, certificates, accounts, billing, or any other Cloudflare product
- Affect any of your other (non-Workers) services

### Even-tighter variant: dedicated CF account

If you want zero blast radius, create a *separate* Cloudflare account just for CHAINSTATE. Cloudflare lets you create multiple accounts on the same email (use sub-addressing like `you+chainstate@example.com`). Add the Custom Token within that account, and the token cannot reach any of your other Cloudflare work even by account compromise.

---

## 2 · `CF_ACCOUNT_ID` — just an identifier

This is the 32-hex Cloudflare account ID. It is not a secret in the cryptographic sense — it doesn't grant any access on its own. But it has to match the account the `CF_API_TOKEN` was created under, so it goes alongside it.

1. https://dash.cloudflare.com → click into any zone (any domain you own; or **Workers & Pages** if you have no domains)
2. Right sidebar: **Account ID** — 32 lowercase hex chars
3. Copy and add to GitHub: name = `CF_ACCOUNT_ID`, value = the hex string

---

## 3 · `HF_TOKEN` — fine-grained, scoped to one Space

A "Write" role token grants write access to every repo and Space on your HuggingFace account. Use a **fine-grained token** scoped to just `CPater/chainstate`:

1. Sign in at https://huggingface.co
2. **Settings** → **Access Tokens** (or https://huggingface.co/settings/tokens)
3. Click **+ Create new token**
4. **Token type**: select **"Fine-grained"** (do NOT select Read or Write).
5. **Token name**: `chainstate-deploy`
6. **Token expiration**: set to **1 year** to force rotation.
7. Scroll to **"Repositories permissions"**:
   - Click **"Add a repository"**
   - Repository: `CPater/chainstate`
   - Type: **Space** (not Model, not Dataset)
   - Permission: **Write contents** (this is the only one you need; do not check "Manage repository settings")
8. **Leave every other section unchecked**:
   - User permissions: none
   - Organization permissions: none
   - Inference endpoints: none
   - Billing: none
9. Click **Create token** → copy the `hf_...` value immediately.
10. Add to GitHub: name = `HF_TOKEN`, value = the `hf_...` token.

**What this token can do**:
- Write files into `CPater/chainstate` Space repo

**What this token cannot do**:
- Touch any of your other Spaces, models, or datasets
- Read or write your account profile
- Bill anything on your account
- Read private repos you own
- Use inference endpoints

---

## Verifying the secrets are wired correctly

After all three are added, push a no-op commit to `main`:

```bash
git commit --allow-empty -m "trigger first deploy"
git push origin main
```

In the GitHub Actions tab you should see two jobs:

- **`cf-worker`** — succeeds when wrangler deploys the Worker. The job log prints the Worker URL near the end (`Worker is uploaded… https://chainstate-worker.<your-subdomain>.workers.dev`). If you see "permission denied on KV namespace", the IDs in `wrangler.toml` are wrong — re-create with `wrangler kv:namespace list` and update.
- **`hf-space`** — succeeds when `huggingface_hub.upload_folder` finishes. Last line is `HF Space updated ✓`. If you see "Token is unauthorized", the token is missing the repo binding — fix in step 3.7 above.

Then test the Worker directly:

```bash
curl https://chainstate-worker.<your-subdomain>.workers.dev/status

curl -X POST https://chainstate-worker.<your-subdomain>.workers.dev/query \
  -H 'Content-Type: application/json' \
  -d '{"query": "∫∂x → ?", "swarmSize": 20, "consensusDepth": 3}'
```

Verify the HF Space at `https://cpater-chainstate.static.hf.space/`. The Query/Terminal/SCAN pages will use the Worker once you wire its URL into the Space — easiest way is to add this script tag to `index.html` (somewhere before the closing `</body>`):

```html
<script>window.__CHAINSTATE_WORKER = "https://chainstate-worker.<your-subdomain>.workers.dev";</script>
```

Or set it temporarily via the browser console:

```js
window.__CHAINSTATE_WORKER = "https://chainstate-worker.<your-subdomain>.workers.dev"
```

---

## Triggering deploys

The workflow ships on **three** triggers:

1. **Push to `main`** — every commit on the main branch deploys. Useful for fast iteration.
2. **GitHub Release** — publish a release (e.g. `v0.1.0`) and the workflow runs. Useful for tagging stable deploys.
3. **Manual dispatch** — go to GitHub repo → **Actions** → **deploy** → **Run workflow**. Useful when you want to retry without a commit.

To publish a release:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Then in GitHub: **Releases** → **Draft new release** → choose `v0.1.0` → **Publish release**. The workflow fires automatically.

---

## Rotating secrets

CF tokens have no built-in expiry by default but we set a 1-year TTL above. HF fine-grained tokens also have an explicit expiry. To rotate:

1. Create a new token following the steps above
2. **GitHub repo** → **Settings → Secrets → Actions** → click the existing secret → **Update**
3. Paste the new value, save
4. Delete the old token at the source (CF dashboard / HF tokens page)

There is no need to re-run any workflow; the next push or release will use the new value.

---

## Security notes

- These secrets are **repository-scoped** in GitHub — they're available to workflow jobs in this one repo only. They are not exposed to forks or PRs from forks.
- The values are encrypted at rest in GitHub and decrypted only inside the runner VM. Any line containing the literal value is masked as `***` in logs.
- **Anyone with push access to `main`** can effectively use these secrets via a malicious workflow change. Protect `main` with required reviews / branch protection if you have collaborators.
- Both Cloudflare and HuggingFace let you revoke a token immediately if it leaks; you should not rely on git history scrubbing if a token was committed accidentally — **revoke first**, then clean.
- If you ever suspect a token is compromised: revoke at source (CF or HF dashboard), then generate a new one and update the GitHub secret. The workflow uses the new value on the very next run.
