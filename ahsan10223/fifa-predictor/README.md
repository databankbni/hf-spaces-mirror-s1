---
title: FIFA World Cup Predictor 2026
emoji: "⚽"
colorFrom: red
colorTo: yellow
sdk: docker
sdk_version: "1.0"
app_file: app.py
pinned: false
---

# FIFA World Cup Predictor 2026

AI-powered FIFA match predictor with intelligent outcome forecasting.

## How It Works

This application uses an XGBoost machine learning model trained on over 40,000 international football matches to predict match outcomes.

### Features
- Select any two teams from the 2026 World Cup qualified teams
- Get real-time win/draw/loss probabilities
- Beautiful, mobile-friendly dashboard

### Tech Stack
- **Backend**: Flask + XGBoost
- **Model**: Trained on historical international matches with Elo-based features
- **Frontend**: HTML, CSS, JavaScript