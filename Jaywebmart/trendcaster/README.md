---
title: TrendCaster
emoji: 📈
colorFrom: gray
colorTo: gray
sdk: gradio
app_file: app.py
pinned: false
license: mit
short_description: Predict short-form video trend trajectories
---

# TrendCaster

A short-form video trend trajectory classifier.

Given pre-posting features of a TikTok or YouTube Shorts video, the model
predicts whether the trajectory will be rising, stable, declining or seasonal.

## Methodology

- Trained an XGBoost classifier on a synthetic 2025 short-form video dataset (50,000 rows)
- Features were filtered to remove engagement-based leakage (likes, shares, view rates)
- Applied SMOTE on training data only to handle class imbalance
- Compared against Logistic Regression and Random Forest; XGBoost won on macro F1

## Results

- Test accuracy: 57.1%
- Macro F1: 0.455
- Beats the 55.4% majority-class baseline with balanced predictions across all four classes

## Project context

Built as a worked example for a teenage machine learning bootcamp, covering the full
CRISP-DM workflow: data understanding, feature filtering, encoding, resampling,
model comparison, evaluation, and deployment.

## License

MIT.
