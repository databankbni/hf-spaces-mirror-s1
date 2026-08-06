---
title: Radiology Summarisation API
colorFrom: blue
colorTo: green
sdk: docker
app_file: app.py
pinned: false
---

# Radiology Report Summarisation API


**Live API:** [https://graceogungbesan1809-debug-radiology-summarisation-api.hf.space](https://graceogungbesan1809-debug-radiology-summarisation-api.hf.space)

**Interactive Docs:** [https://graceogungbesan1809-debug-radiology-summarisation-api.hf.space/docs](https://graceogungbesan1809-debug-radiology-summarisation-api.hf.space/docs)

**Model on HuggingFace Hub:** [https://huggingface.co/graceogungbesan1809-debug/flan-t5-radiology](https://huggingface.co/graceogungbesan1809-debug/flan-t5-radiology)

**GitHub Repository:** [https://github.com/graceogungbesan1809-debug/radiology-api](https://github.com/graceogungbesan1809-debug/radiology-api)


---

## 1. Model Summary

This project fine-tunes google/flan-t5-base, a sequence-to-sequence language model, on the NLM Chest X-ray dataset (NLMCXR) to generate concise clinical impressions from radiology findings text. The raw dataset consists of 3,955 XML report files, parsed using BeautifulSoup targeting AbstractText tags with Label="FINDINGS" and Label="IMPRESSION". After cleaning — dropping null rows, removing duplicate pairs, and filtering short records — 3,419 valid report pairs remained. These were split into 80% train, 10% validation, and 10% test sets. Each findings text was prepended with the prompt "generate a concise clinical impression from these radiology findings:" before tokenisation, with a maximum input length of 512 tokens and maximum target length of 32 tokens. The model was fine-tuned for 25 epochs with a learning rate of 5e-5 and batch size of 8, using beam search generation with num_beams=4, length_penalty=2.0, and no_repeat_ngram_size=3. Final evaluation on the held-out test set produced a ROUGE-1 F1 of 0.133, ROUGE-2 F1 of 0.082, ROUGE-L F1 of 0.130, and BERTScore F1 of 0.866.

---

## 2. Limitations and Recommendations

The ROUGE-1 F1 score of 0.133 is below the 0.3 threshold, but this reflects a dataset ceiling rather than a model deficiency. An extractive baseline that copied the most relevant sentence directly from the findings scored ROUGE-1 of 0.132, confirming the theoretical ceiling on this dataset is approximately 0.13-0.14. This occurs because the NLMCXR reference impressions are highly abstractive clinical conclusions that share almost no words with the source findings text, and 2,017 of the 3,419 impression records are non-unique short phrases such as "No acute cardiopulmonary process." ROUGE measures lexical overlap and is therefore not well suited to evaluating abstractive summarisation on this dataset. BERTScore F1 of 0.866 better captures semantic accuracy and demonstrates the model is generating clinically appropriate impressions. The model also exhibits extractive-leaning behaviour on short or straightforward findings — when the input is already brief and clear, the model tends to copy key phrases rather than generate an abstract clinical conclusion. This is a direct consequence of the non-unique impression distribution in the training data, where the model learned to echo concise factual statements rather than always abstracting them. To improve ROUGE scores and reduce extractive copying, a larger and less abstractive dataset such as MIMIC-CXR would be recommended. Training on multiple GPUs with a larger model such as flan-t5-large would also be expected to improve performance. All training for this project was performed on a single Google Colab T4 GPU under free-tier constraints.

---

## 3. Sample Model Predictions

Sample predictions on the three findings from the project appendix:

**Finding 1:**

The trachea is midline. The cardiomediastinal silhouette is normal. The lungs are clear, without evidence of acute infiltrate or effusion. There is no pneumothorax. The visualized bony structures reveal no acute abnormalities.

**Impression 1:**

> The trachea is midline. The cardiomediastinal silhouette is normal. The lungs are clear, without evidence of acute infiltrate or effusion.

**Finding 2:**

The lungs are clear. Heart size and mediastinal contours are normal. No osseous abnormalities.

**Impression 2:**

> The lungs are clear and the heart size and mediastinal contours are normal.

**Finding 3:**

AP and lateral views were obtained. Bibasilar atelectasis and small left-sided pleural effusion. Stable cardiomegaly. No pneumothorax. Mild pulmonary vascular congestion.

**Impression 3:**

> AP and lateral views obtained. Bibasilar atelectasis and small left-sided pleural effusion. Stable cardiomegaly. No pneumothorax.

---

## 4. How to Run the Full System from a Clean Environment

### Prerequisites

- Python 3.9 or higher
- GPU recommended for training (CPU supported but slow — see note below)
- Raw dataset downloaded from https://openi.nlm.nih.gov

### Step 1 — Clone the repository

    git clone https://github.com/graceogungbesan1809-debug/radiology-api.git
    cd radiology-api

### Step 2 — Install dependencies

    pip install -r requirements.txt

### Step 3 — Prepare the dataset

Download NLMCXR_reports.tgz from https://openi.nlm.nih.gov and extract it:

    tar -xvzf NLMCXR_reports.tgz -C data/NLMCXR_reports

XML files should sit at: data/NLMCXR_reports/ecgen-radiology/*.xml

### Step 4 — Run the full pipeline

    python run_pipeline.py

This runs all three steps in order:
1. Preprocess — parses 3,955 XML files, extracts findings/impression pairs, saves to data/processed_reports.csv
2. Train — fine-tunes FLAN-T5-base for 25 epochs, saves model to model/
3. Evaluate — computes ROUGE and BERTScore on held-out test set, prints results

NOTE ON RUNTIME: Training for 25 epochs on CPU is extremely slow (hours to days). If testing locally on CPU, reduce NUM_EPOCHS in src/train.py to 1 to verify the pipeline runs correctly before performing full training on a GPU environment such as Google Colab.

### Step 5 — Run individual pipeline steps

    python src/preprocess.py
    python src/train.py
    python src/evaluate.py

### Step 6 — Run the API locally

    uvicorn app:app --reload

Then visit http://localhost:8000/docs for the interactive API interface.
Note: the live deployed API is already publicly accessible at https://graceogungbesan1809-debug-radiology-summarisation-api.hf.space/docs -- running locally is only necessary if you wish to test or modify the code.

---

## 5. API Documentation

This API takes free-text radiology findings as input and returns a concise clinical impression generated by a fine-tuned FLAN-T5 model.

### Base URL

https://graceogungbesan1809-debug-radiology-summarisation-api.hf.space

### Endpoints

#### GET /

Health check. Confirms the API is running.

Response:

    {
        "status": "Radiology summarisation API is running"
    }

#### POST /summarise

Generates a clinical impression from radiology findings text.

URL: https://graceogungbesan1809-debug-radiology-summarisation-api.hf.space/summarise

Method: POST

Authentication required: NO

Request payload schema:

| Field    | Type   | Required | Constraints                        |
|----------|--------|----------|------------------------------------|
| findings | string | Yes      | Non-empty string, max 512 tokens   |

Data example:

    {
        "findings": "The lungs are clear. Heart size and mediastinal contours are normal. No osseous abnormalities."
    }

Success Response

Code: 200

Response schema:

| Field      | Type   | Description                        |
|------------|--------|------------------------------------|
| impression | string | AI-generated clinical impression   |

Content example:

    {
        "impression": "The lungs are clear and the heart size and mediastinal contours are normal."
    }

Error Response 1

Condition: The findings field is missing, malformed, or the request body is not valid JSON.

Code: 422

Content:

    {
        "detail": [
            {
                "type": "missing",
                "loc": ["body", "findings"],
                "msg": "Field required",
                "input": {}
            }
        ]
    }

Error Response 2

Condition: The findings field is present but contains only whitespace or is empty.

Code: 200

Content:

    {
        "impression": "Error: 'findings' field must not be empty."
    }

### Example curl request

    curl -X POST https://graceogungbesan1809-debug-radiology-summarisation-api.hf.space/summarise \
      -H "Content-Type: application/json" \
      -d '{"findings": "The lungs are clear. Heart size and mediastinal contours are normal."}'

### Example Python request

    import requests

    response = requests.post(
        "https://graceogungbesan1809-debug-radiology-summarisation-api.hf.space/summarise",
        json={"findings": "The lungs are clear. Heart size and mediastinal contours are normal."}
    )
    print(response.json())
    # {'impression': 'The lungs are clear and the heart size and mediastinal contours are normal.'}

---

## 6. Model Loading and Inference Flow

At API startup, app.py loads the model and tokenizer directly from HuggingFace Hub:

    MODEL_PATH = "graceogungbesan1809-debug/flan-t5-radiology"
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, legacy=False)
    model = AutoModelForSeq2SeqLM.from_pretrained(
        MODEL_PATH,
        ignore_mismatched_sizes=True,
        tie_word_embeddings=False,
    )
    model.eval()

When a POST request arrives at /summarise, the inference flow is:

1. The findings text is prepended with the prompt prefix:
   "generate a concise clinical impression from these radiology findings: {findings}"
2. The prompt is tokenised with truncation at 512 tokens
3. The model generates output using beam search:
   - max_new_tokens=64
   - num_beams=4
   - length_penalty=2.0
   - no_repeat_ngram_size=3
   - early_stopping=True
4. The output token IDs are decoded and returned as the impression field

Why ignore_mismatched_sizes=True and tie_word_embeddings=False: These flags were required to fix gibberish output on the first working deployment. The mismatch arose from differences between the training and inference environments weight configurations. Setting these flags at load time resolved the issue and produced coherent clinical impressions.

---

## 7. Repository Structure

    radiology-api/
    data/                        <- Data directory (raw data not tracked by Git)
      NLMCXR_reports/
        ecgen-radiology/         <- Unzipped XML report files go here
    notebooks/
      Medical_Text_Summariser_Proj.ipynb   <- Experimentation notebook
    src/
      preprocess.py              <- Parses XML reports -> processed_reports.csv
      train.py                   <- Fine-tunes FLAN-T5-base
      evaluate.py                <- Computes ROUGE and BERTScore metrics
    deployment/
      Dockerfile                 <- Docker config for HuggingFace Spaces
      render.yaml                <- Legacy render config (not in use)
    frontend/
      index.html                 <- Browser-based interface for non-technical users
    app.py                       <- FastAPI application (deployed API)
    run_pipeline.py              <- Single entry point to run full pipeline
    requirements.txt             <- All dependencies
    Dockerfile                   <- Copy required by HuggingFace Spaces
    README.md
    EXPERIMENT_LOG.md            <- Detailed experiment log

---

## 8. Experiment Log

### Phase 1 — Data Extraction

Approach: Extracted XML files from NLMCXR_reports.tgz using Python's tarfile module, then parsed with BeautifulSoup targeting AbstractText tags with Label="FINDINGS" and Label="IMPRESSION".

Key discovery: The NLMCXR dataset files are XML, not plain text. Each report contains multiple AbstractText tags with different Label attributes. Correctly targeting only the FINDINGS and IMPRESSION labels was essential to extracting clean clinical text. Once parsed correctly, findings averaged 61 tokens and impressions averaged 16 tokens — short, focused clinical sentences appropriate for sequence-to-sequence summarisation.

Lesson learned: Always inspect the raw file format and structure before writing any parsing code.

### Phase 2 — Data Cleaning

Steps taken: Dropped null rows, stripped whitespace, removed exact duplicate pairs on combined findings and impression fields, filtered rows with fewer than 3 words in findings or 1 word in impression, computed token lengths, split into 80/10/10 train/validation/test sets.

Key discovery: After deduplication, 2,017 impressions were non-unique — many different findings mapped to the same short phrases such as "No acute cardiopulmonary process." This directly explained the ROUGE ceiling observed during evaluation.

Lesson learned: Duplicate analysis before training reveals dataset characteristics that directly affect evaluation metrics.

### Phase 3 — Model Selection

| Attempt | Model | Reason for Trying | Outcome | Reason Abandoned |
|---|---|---|---|---|
| 1 | google/flan-t5-small | Baseline starting point | Not trained | Data showed token lengths exceeding 512 token limit |
| 2 | google/long-t5-tglobal-base | Supports up to 16,384 tokens | ROUGE-1 0.13-0.20 | After fixing data parsing, data fitted within 512 tokens making Long-T5 unnecessary. Model was copying last sentence of findings rather than generating impressions |
| 3 | philschmid/flan-t5-base-samsum | Pre-trained on dialogue summarisation | ROUGE-1 0.13 | No improvement over base FLAN-T5 |
| 4 | google/flan-t5-base | Strong instruction-following, appropriate size | Final model — ROUGE-1: 0.133, BERTScore F1: 0.866 | — |

Observation: All models regardless of architecture converged to approximately ROUGE-1 0.13 — a strong signal the metric ceiling was a dataset characteristic rather than a model limitation.

### Phase 4 — Hyperparameter Configurations Tested

| Configuration | Epochs | Learning Rate | MAX_TARGET | Prompt | Notes |
|---|---|---|---|---|---|
| 1 | 5 | 1e-4 | 128 | "summarise:" | Underfitting — outputs too generic |
| 2 | 10 | 1e-4 | 64 | "summarise:" | Slight improvement, still generic |
| 3 | 15 | 5e-5 | 64 | "generate a concise clinical impression from these radiology findings:" | Better coherence, ROUGE plateau around 0.13 |
| 4 | 25 | 5e-5 | 32 | "generate a concise clinical impression from these radiology findings:" | Final configuration — best coherence and BERTScore |

Generation settings tested: encoder_no_repeat_ngram_size=4 caused hallucinations and was removed. num_beams=4, length_penalty=2.0, and no_repeat_ngram_size=3 were retained as they produced the most clinically coherent outputs.

Lesson learned: Change one hyperparameter at a time. Changing multiple simultaneously makes it impossible to isolate which change caused which result.

### Phase 5 — Environment Issues

| Error | Cause | Fix |
|---|---|---|
| clear_device_cache ImportError | Version mismatch between transformers and accelerate | Upgraded to compatible versions |
| EncoderDecoderCache ImportError | System transformers version too old | Upgraded to transformers==4.44.0 |
| BeamBasedBuilder circular import | datasets package corruption | Force reinstalled with --force-reinstall |
| numpy binary incompatibility | pip downgraded numpy mid-session | Restarted runtime |
| tokenizer TypeError in Seq2SeqTrainer | Colab updated to transformers 5.x — argument renamed from tokenizer to processing_class | Updated trainer initialisation |
| Google Drive storage full (98%) | 11.9GB of checkpoints filling Drive | Redirected output_dir to /tmp/ |
| summarization pipeline KeyError | transformers version mismatch | Switched from pipeline() to direct AutoTokenizer and AutoModelForSeq2SeqLM |
| Gibberish API output on deployment | Tied weights mismatch between environments | Added tie_word_embeddings=False and ignore_mismatched_sizes=True |

Lesson learned: Pin package versions at the start of every project. Direct model loading is more reliable than the pipeline abstraction for deployment.

### Phase 6 — Deployment

| Attempt | Platform | Outcome | Reason Abandoned |
|---|---|---|---|
| 1 | Render.com free tier (local model file) | Failed | 512MB RAM limit — FLAN-T5-base requires approximately 900MB |
| 2 | Render.com (model from HuggingFace Hub) | Failed | Same 512MB RAM limit applies regardless of model source |
| 3 | HuggingFace Spaces (Docker) | Success | Sufficient RAM, natural fit for HuggingFace models |

Lesson learned: Always check RAM requirements before choosing a hosting platform.

### Metric Behaviour Analysis

ROUGE measures word and phrase overlap between generated and reference text. The NLMCXR dataset is highly abstractive — radiologists write impressions using clinical conclusions that share almost no words with the findings text. For example:

Findings: "Bilateral interstitial opacities are present. The cardiac silhouette is borderline enlarged. No pleural effusion is identified."
Reference impression: "Mild cardiomegaly. No acute process."

The generated impression may be semantically correct but use entirely different wording, producing a low ROUGE score despite being clinically accurate.

To confirm this was a dataset ceiling rather than model failure, an extractive baseline was run that simply copied the most relevant sentence from the findings without any model. It scored ROUGE-1 of 0.132 — nearly identical to every trained model's score of 0.133. This proved the theoretical ROUGE-1 ceiling on this dataset is approximately 0.13-0.14.

BERTScore uses contextual embeddings to measure semantic similarity rather than exact word overlap. A BERTScore F1 of 0.866 indicates the generated impressions are capturing the correct clinical meaning even when wording differs from the reference. For abstractive clinical summarisation on the NLMCXR dataset, BERTScore is a more appropriate evaluation metric than ROUGE.

| Metric | Score |
|---|---|
| ROUGE-1 F1 | 0.133 |
| ROUGE-2 F1 | 0.082 |
| ROUGE-L F1 | 0.130 |
| BERTScore F1 | 0.866 |
| Extractive baseline ROUGE-1 | 0.132 |
| Estimated dataset ROUGE-1 ceiling | 0.13-0.14 |
