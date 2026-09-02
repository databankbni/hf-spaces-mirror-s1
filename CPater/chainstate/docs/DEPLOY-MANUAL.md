# Deploying CHAINSTATE manually — step-by-step

You have two manual paths:

- **A · Wrangler CLI from your laptop** — the most reliable. Bypasses the dashboard entirely and is what professional CF Worker deploys look like. Recommended.
- **B · Dashboard editor retry** — fast, but you've already seen this 403 once. Documented below for completeness.

Neither path requires a `git push`. Neither path requires you to delete the existing worker.

---

## Path A · Wrangler CLI (5 minutes, one-time setup, then ~10 seconds per deploy)

### A1 · One-time setup on your laptop

```bash
# 1. Install wrangler globally
npm install --global wrangler

# 2. Check it's installed (should print version like 3.x.x)
wrangler --version
```

### A2 · Authenticate with Cloudflare · pick one

**Option A2-i · OAuth via browser** (easiest, no token needed):

```bash
wrangler login
```

A browser tab opens. Click **Allow** to grant `wrangler` access to your CF account. Done.

**Option A2-ii · Reuse your `CF_API_TOKEN`** (no browser interaction, good if A2-i fails):

```bash
# Replace <your-token> with the value of CF_API_TOKEN from your GitHub secrets
export CLOUDFLARE_API_TOKEN='<your-token>'
```

Either option authenticates `wrangler` so it can talk to your CF account.

### A3 · Deploy

```bash
# From the chainstate repo root
cd /path/to/chainstate

# Deploy — reads wrangler.toml, packages workers/edge-worker.js, ships to CF
wrangler deploy
```

Expected output (succinct):

```
 ⛅️ wrangler 3.x.x
-------------------
Total Upload: 18.43 KiB / gzip: 6.20 KiB
Uploaded chainstate-worker (x.xx sec)
Published chainstate-worker (x.xx sec)
  https://chainstate-worker.ciprianpater.workers.dev
Current Deployment ID: <some uuid>
```

That's it. The worker is updated in-place — same URL, same bindings, new code.

### A4 · Verify the deploy worked

Open https://chainstate-worker.ciprianpater.workers.dev/status in a browser. You should see JSON with:

```json
{
  ...
  "worker_version": "0.2.0-cors-hardened-2026-06-30",
  "cors_enabled": true,
  ...
}
```

If `worker_version` is missing or shows an older value, the deploy didn't land — re-run `wrangler deploy` from the right directory.

Alternative one-line check from the terminal:

```bash
curl -s https://chainstate-worker.ciprianpater.workers.dev/status | grep worker_version
```

Or inspect the response headers directly (the version is also stamped here on every response):

```bash
curl -I https://chainstate-worker.ciprianpater.workers.dev/status
# look for:    x-worker-version: 0.2.0-cors-hardened-2026-06-30
```

### A5 · Verify CORS is fixed

```bash
curl -i -H 'Origin: https://cpater-chainstate.static.hf.space' \
  https://chainstate-worker.ciprianpater.workers.dev/status
```

In the response you should see (in any order):

```
access-control-allow-origin: https://cpater-chainstate.static.hf.space
access-control-allow-methods: GET, POST, OPTIONS
vary: Origin
```

Once those headers are present, reload `https://cpater-chainstate.static.hf.space/` — the browser console should stop showing CORS errors, the API page KPI ticker should populate from live data, and SCAN tiles should show real `/status` numbers when toggled to LIVE.

---

## Path B · Dashboard editor retry (the 403 path you hit earlier)

If wrangler CLI isn't an option, the dashboard editor can still work after clearing the auth state that caused the 403. In order of likelihood:

### B1 · Refresh and retry (30 seconds, ~70 % of cases)

1. Hard refresh the dashboard tab: **Cmd-Shift-R** (Mac) or **Ctrl-Shift-R** (Win/Linux)
2. Re-open the worker's editor
3. Click **Save and Deploy**

If 403 again → step B2.

### B2 · Full log-out / log-back-in (1 minute)

1. Top-right of the dashboard → click your email → **Log out**
2. Sign back in (use SSO/2FA as usual)
3. Navigate back to **Workers & Pages** → `chainstate-worker` → **Edit Code**
4. Paste the file again (if the editor didn't keep your changes) and click **Save and Deploy**

If 403 again → step B3.

### B3 · Confirm you're in the right account

Multi-account users sometimes have a different account active than the one that owns the worker.

1. Top-right of the dashboard → click your email
2. In the dropdown, look at the **Account** selector
3. If you have multiple accounts, switch to the one that owns `chainstate-worker`
4. Retry the deploy

If still 403 → use Path A (wrangler CLI). The CLI uses a different auth path and is immune to dashboard cookie/session issues.

---

## Why your existing worker stays running on either path

Whether you deploy via wrangler CLI or the dashboard, the operation is an **update** of the existing worker named `chainstate-worker`. Cloudflare matches by name and replaces the code atomically.

| What's preserved on update         | Comment                                              |
|------------------------------------|------------------------------------------------------|
| The URL `chainstate-worker.ciprianpater.workers.dev` | Same hostname, same TLS cert       |
| Any KV bindings already attached   | `CHAINSTATE_NODES` etc., if you've created them      |
| Environment variables and secrets  | `SWARM_SIZE`, `RATE_LIMIT`, etc.                     |
| Custom domains / routes            | If you have any                                      |
| Usage statistics                   | The "live" status, request counters, etc.            |

| What changes                       | Comment                                              |
|------------------------------------|------------------------------------------------------|
| The code itself                    | Old `Hello World` → new CHAINSTATE worker            |
| The deployment ID                  | New UUID printed in the deploy output                |
| `X-Worker-Version` response header | Now reflects the new `WORKER_VERSION` constant       |

**Do not delete the worker.** Deleting it would release the URL (someone else could claim `chainstate-worker.ciprianpater.workers.dev` — unlikely, but possible), drop all bindings, and force you to recreate everything from scratch.

---

## Quick reference

```bash
# Install wrangler
npm install --global wrangler

# Authenticate (browser OAuth)
wrangler login

# Deploy
cd /path/to/chainstate
wrangler deploy

# Verify
curl -s https://chainstate-worker.ciprianpater.workers.dev/status | grep worker_version
```

That's the entire flow. Six commands. The worker is updated; CORS works; the HF Space's LIVE mode talks to the worker without browser errors.
