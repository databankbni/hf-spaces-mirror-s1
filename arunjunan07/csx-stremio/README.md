---
title: Provider Bridge Addon
emoji: 🐳
colorFrom: purple
colorTo: gray
sdk: docker
app_port: 7860
---

# Provider Bridge Addon

This addon bridges stream extractor modules from `vega-providers-main` into Stremio `stream` responses.

## What it does

- Decodes a `vp_...` stream request id
- Loads the matching provider module from `vega-providers-main/dist/<provider>/stream.js`
- Normalizes provider output into Stremio stream objects
- Includes a local fixture verifier in `verify-extraction.js`

## Important

Only connect sources you are authorized to access and stream.

## Setup

1. Install dependencies:
   ```bash
   npm install
   ```
2. Start the addon:
   ```bash
   npm start
   ```
3. Install it in Stremio from your Space URL plus `/manifest.json`

## Deploying to Hugging Face

- Deploy the repo root without vendoring `vega-providers-main`; the Space will clone it during build.
- The Space always clones the latest upstream provider repo on rebuild, then generates `dist` there.
- The Dockerfile builds `vega-providers-main/dist` during the Space build, so the generated files stay up to date.

## Encode a request

Use the helper in `src/providerBridge.js`:

```js
const { encodeProviderRequest } = require('./src/providerBridge');

const id = encodeProviderRequest({
  provider: 'tokyoInsider',
  link: 'https://example.test/page',
  type: 'movie',
});
```

That encoded id is what Stremio requests as the stream id.

## Verification

Run the local fixture test:

```bash
npm run verify
```

It checks two cases:

- `tokyoInsider` fixture extraction
- `vadapav` direct URL pass-through

## Notes

- The local runtime uses a lightweight HTTP/HTML helper so it can run without the broken bundled provider context.
- More complex providers may need extra selector or request support if you want them to work here too.

