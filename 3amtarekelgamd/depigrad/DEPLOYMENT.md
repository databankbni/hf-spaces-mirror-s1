# Hugging Face Docker Space Deployment

1. Go to Hugging Face and create a new Space.
2. Choose `Docker` as the Space SDK and select the `Blank` template.
3. Upload these files into the Space repository: `app.py`, `requirements.txt`, `Dockerfile`, `fraud_classifier_phase3.pkl`, `fraud_quantile_transformer.pkl`, and `fraud_classifier_threshold_meta.pkl`.
4. Commit the files in the browser editor or via the web UI to trigger the automatic Docker build.
5. Wait until the Space status changes to `Running`.
6. Open the public Space URL shown on the Space page; that URL is your live API endpoint.

## How to Use the Frontend

1. Start the frontend dev server from `frontend` with `npm run dev`.
2. Open the app in your browser and set the `API Endpoint` field to your backend URL.
3. Enter `Time` and `Amount` manually, or use `Load Normal Sample` / `Load Fraud Sample` to prefill the form.
4. Upload a CSV file if you want to load a full transaction row.
5. Click `Analyze Transaction` to send the request to `POST /predict`.

## What to Expect

- While the request is in progress, the UI shows `Evaluating security profiles...`.
- If the backend is unreachable, the UI shows a clear server error instead of staying blank.
- If the backend responds successfully, the result panel shows either `HIGH RISK DETECTED` or `TRANSACTION APPROVED`.
- The result panel also shows the risk score out of 100 and the primary risk factor returned by the model.

## Expected CSV Format

The CSV uploader reads the first header row and the first data row only.

- Required columns: `Time`, `Amount`, `V1` through `V28`
- Optional column: `Class` is ignored if present
- Column order can vary, but the header names must match exactly

Example CSV:

```csv
Time,Amount,V1,V2,V3,V4,V5,V6,V7,V8,V9,V10,V11,V12,V13,V14,V15,V16,V17,V18,V19,V20,V21,V22,V23,V24,V25,V26,V27,V28,Class
12045.0,145.99,-1.359807,-0.072781,2.536347,1.378155,-0.338321,0.462388,0.239599,0.098698,0.363787,0.090794,-0.551600,-0.617801,-0.991390,-0.311169,1.468177,-0.470401,0.207971,0.025791,0.403993,0.251412,-0.018307,0.277838,-0.110474,0.066928,0.128539,-0.189115,0.133558,-0.021053,0
```

If a CSV has fewer columns or missing names, those fields stay at `0.0` in the frontend state.
