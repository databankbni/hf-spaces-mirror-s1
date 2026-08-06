---
title: CKB 17-variable Risk Predictor
emoji: 🧬
colorFrom: blue
colorTo: indigo
sdk: gradio
sdk_version: 6.20.0
app_file: app.py
python_version: 3.12
pinned: false
license: other
---

# CKB 17-variable Prediction API and Demo

This Hugging Face Space wraps the model package in `predictions/` with:

- a browser-based Gradio demo;
- a compact JSON API named `/predict`;
- automatic API documentation through the Space footer's **Use via API** link.

The model is loaded lazily on the first prediction and then cached. Inference is
serialized because the package maintains lazy in-memory model caches. Requests
are stateless: input data and generated JSON files are not retained by the app.

## Automatic startup and warm-up

When a visitor opens a paused Space, Hugging Face resumes the container before
the page can be served. After the Gradio page becomes available, its `load`
event automatically warms all prediction-time artifacts in the background. The
visitor can fill in the form while this happens; a submission made before the
warm-up finishes waits in the one-at-a-time inference queue.

The platform's cold-start screen is controlled by Hugging Face, so no Space app
can render its own input form before the container has resumed.

## API request

Replace `YOUR-USERNAME` and `YOUR-SPACE` after the Space has been created:

```bash
# 1. Submit the request. Copy the event_id from the JSON response.
curl -X POST \
  "https://YOUR-USERNAME-YOUR-SPACE.hf.space/gradio_api/call/v2/predict" \
  -H "Content-Type: application/json" \
  -d '{
    "request": {
      "sample_id": "example_001",
      "features": {
        "sex": 0,
        "age": 59,
        "edu_level": 1,
        "marital_status": 1,
        "work": 1,
        "retire": 0,
        "hh_size": 5,
        "smoking": 1,
        "alcohol": 1,
        "height_cm": 163.8,
        "weight_kg": 59.6,
        "waist_cm": 81.1,
        "sbp_mmhg": 125,
        "dbp_mmhg": 67,
        "bp_drugs": 0,
        "self_health": 2,
        "chronic_pain": 0
      }
    }
  }'

# 2. Replace EVENT_ID with the returned value and stream the result.
curl -N \
  "https://YOUR-USERNAME-YOUR-SPACE.hf.space/gradio_api/call/predict/EVENT_ID"
```

The response contains an `event_id`. Poll the URL returned by the API until the
server-sent event named `complete` arrives. The Space's **Use via API** page
generates the exact two curl commands for the deployed URL.

Browser JavaScript example:

```javascript
import { Client } from "https://cdn.jsdelivr.net/npm/@gradio/client/dist/index.min.js";

const app = await Client.connect("YOUR-USERNAME/YOUR-SPACE");
const request = {
  sample_id: "visitor_001",
  features: {
    sex: 0,
    age: 59,
    edu_level: 1,
    marital_status: 1,
    work: 1,
    retire: 0,
    hh_size: 5,
    smoking: 1,
    alcohol: 1,
    height_cm: 163.8,
    weight_kg: 59.6,
    waist_cm: 81.1,
    sbp_mmhg: 125,
    dbp_mmhg: 67,
    bp_drugs: 0,
    self_health: 2,
    chronic_pain: 0,
  },
};

const result = await app.predict("/predict", { request });
console.log(result.data[0]);
```

For a private Space, pass a Hugging Face read token when connecting. Do not put
a private token in public browser JavaScript.

## Deploy

1. Create a new **Gradio Space** on Hugging Face and choose the free ZeroGPU
   hardware option if your account is eligible.
2. Install Git LFS locally and make sure the patterns in `.gitattributes` are
   active before committing the model artifacts.
3. Add this folder as the Space Git remote, commit, and push.
4. Wait for the Space build. The first prediction is slower because the
   approximately 600 MB model bundle is loaded lazily.

Large `.pkl`, `.joblib`, `.npy`, and `.npz` model artifacts are configured for
Git LFS. Do not commit generated files under `predictions/predictions/`.

## Model safeguards

- All 17 numeric variables are required. Missing-value imputation is not
  performed.
- Categorical values must use the original CKB training codes.
- Cluster assignments can be marked `uncertain` or `unclassified_ood`.
- Outcome risk classes use the frozen Youden thresholds from `manifest.json`.
- This is a research model, not a clinical diagnosis or medical device.
