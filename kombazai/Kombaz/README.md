---
title: KOMBAZ Synth
emoji: 🎹
colorFrom: blue
colorTo: purple
sdk: docker
app_file: app.py
pinned: false
---

# 🎹 KOMBAZ SYNTH — Web Music Studio

סטודיו הפקה מלא בדפדפן: סינתיסייזר רב-מנועי, מנוע תופים עם עריכת סאונד,
מיקסר, sidechain, לופר ובניית טראק שלם עם ייצוא WAV עד 8 דקות.
בהשראת Xfer Serum ו-Arturia Pigments. Web Audio API טהור.

## מדריך אינטראקטיבי
בכניסה הראשונה נפתח סיור מודרך עם דפדוף (Continue / Got it) ותיבת
"אל תציג שוב". לפתיחה מחדש — כפתור **?** בפינה.

## Features
- 🌊 6 מנועי סינת' לכל אוסילטור: Wavetable · FM · Analog · Additive · Vocal (formant/choir) · Pulse (PWM)
- 🎛️ Unison · Detune · Filter · 2 ADSR · LFO
- ✨ FX Rack: Distortion, Chorus, Delay, Reverb, Bitcrusher, Phaser, EQ, Stereo Widener, Compressor
- 🥁 Rhythm Engine — 10 ערוצים כולל **KICK2** (קיק פסיטראנס סגנון Astrix/Infected)
- 🎚️ Drum Mixer + עריכת סאונד לכל ערוץ (Pitch/Decay/Tone) + פילטר master
- 💥 Sidechain (PUMP + RELEASE)
- 🅰️ Pattern Chaining (A/B/C/D) למבנה טראק
- 🔴 Looper עם Quantize
- ⬇ Export WAV — אורך נבחר: 30 שניות / 1 / 2 / 5 / 8 דקות
- 🎹 Web MIDI · 💾 Storage API
- 🥁 8 קיטים: Psytrance, Full-On, Darkpsy, Techno, House, DnB, Trap, Ambient
- ♿ נגישות · 📱 PWA · 📲 מותאם נייד

## הערה על "VST" ו"ווקאל"
- דפדפן לא יכול לטעון תוספי VST (קוד מקומפל) — במקום זה יש 6 מנועי סינת' מובנים.
- מנוע Vocal מחקה תנועות קול (אה/אֶה/אִי/אוֹ/אוּ) עם הרמוניה — לא מילים אמיתיות
  (זה דורש שירות AI חיצוני עם שרת).

## Tech
- Pure Web Audio API · FastAPI + Pydantic · PWA · Docker

## אחסון ב-Hugging Face
האחסון של Space רגיל זמני. להתמדה הפעל **Persistent Storage** (data ב-/app/data).
