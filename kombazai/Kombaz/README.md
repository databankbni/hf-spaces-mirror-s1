---
title: KOMBAZ Synth
emoji: 🎹
colorFrom: blue
colorTo: purple
sdk: docker
app_file: app.py
pinned: false
---

# 🎹 KOMBAZ SYNTH — Web Wavetable Synthesizer

סינתיסייזר Wavetable מלא שרץ בדפדפן — בהשראת Xfer Serum ו-Arturia Pigments.
מנוע אודיו אמיתי על Web Audio API, ללא ספריות חיצוניות.

## Features
- 🌊 2 Wavetable Oscillators — מורף רציף בין Sine → Tri → Saw → Square → Digital
- 🎛️ Unison עד 7 קולות + Detune + Stereo Spread לכל אוסילטור
- 🔻 Multi-mode Filter — LP / HP / BP / Notch + Resonance + Drive
- 📈 2 ADSR Envelopes — Amp + Filter Mod
- 🌀 LFO עם יעדים: Cutoff / Pitch / Wavetable Position
- ✨ FX Rack — Distortion, Chorus, Delay, Reverb (Convolution)
- 🎚️ 7 Presets — Pluck, Reese Bass, Hyper Saw, Pad, EP, Acid 303
- 🖥️ תצוגת Wavetable תלת-ממדית חיה + Oscilloscope
- 🎹 מקלדת מסך + נגינה ממקלדת המחשב (A W S E D F T G Y H U J K)
- 📱 תמיכה מלאה במגע (מובייל)

## Tech
- Pure Web Audio API (zero audio libraries)
- FastAPI static server (Docker SDK)
