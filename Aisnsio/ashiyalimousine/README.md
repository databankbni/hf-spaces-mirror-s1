---
title: Ashiya Limousine Service
emoji: 🥂
colorFrom: indigo
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# Ashiya Limousine Service — 芦屋リムジンサービス

A luxury stretch-limousine hire service site — night-cruise navy, champagne gold, and a
9,000 mm blueprint measurement line as the signature device. Bilingual (EN / 日本語),
fully self-contained, and served by a small static Express server.

## Routes

- `/` — the site (hero, fleet, plans/packages, gallery, online booking, admin gate)
- `/healthz` — health check, returns `{ "status": "ok" }`

## What's inside

A single self-contained page: inline styles/scripts, embedded photography (base64), an
EN/JA language toggle, an online **booking** flow with a live quote, and a passcode-gated
**admin** console (bookings table + CSV export). All data is client-side demo data held in
`localStorage` — there is no database, no auth backend, and no external network calls
beyond Google Fonts.

## Stack

Node 22 + Express serving `public/` only. No DB, no secrets required to run.

## Local run

```
npm install
node server.js   # http://localhost:7860
```
