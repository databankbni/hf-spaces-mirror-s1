---
title: Corner cafe
sdk: static
app_file: index.html
sdk_version: "1.17"
emoji: ☕
colorFrom: yellow
colorTo: gray
pinned: true
short_description: Hero cycles all 7 clips; lighter mobile load (v1.17)
---

# Corner cafe

**v1.17** — Home background now cycles the **full hero set** (all 7 clips in the HF `videos/hero` folder), including on mobile and Save-Data / 2G–3G. Open Monday–Sunday 9:00–17:00 at **9 Eskdail Court**, Dalkeith.

### Hero (v1.17)

- Restored the full set (including `pexels-video-35510475`); ordered lightest-first so the opening frame is ~112KB.
- Removed per-clip HTML `loop` — that was why phones looked stuck on one video when rotation was skipped.
- Rotation always runs (reduced-motion excepted). Each clip plays once, then advances; a max dwell (8s desktop / 10s mobile) covers stalled loads.
- Still downloads **one clip at a time**, warming only the next ahead so mobile radios stay light.

### v1.16 notes

- Fix: the hero logo `<img>` closed early after `src`, so `alt` / `width` / `fetchpriority` / `decoding` rendered as plain text on the page.

### v1.15 notes

- Menu-side gallery (spotlight): on viewports ≤1023px only **three** clips rotate, unused videos stay unloaded, autoplay dwell is longer, and fetch starts closer to the fold so the first frame arrives sooner on mobile and tablet radios.

### Responsive

- Breakpoint ranges tidied to phone (<768px), tablet (768–1023px), laptop (1024–1439px) and desktop (1440px+).
- Menu grid now resolves 1 / 2 / 3 columns; the old four-track grid left an empty column on wide screens.
- Fixed the 550px map iframe and the full-bleed contact band that could push the page sideways.
- 44px minimum hit areas on touch pointers, safe-area padding for notched phones, and `svh` hero heights so mobile browser chrome does not cause a jump.

### Loading

- Hero ships **one** video at a time and cycles the full set; the next clip is warmed during playback.
- Spotlight and gallery carousels stay unfetched until scrolled near the viewport.
- Gallery photography requested at `w=800` rather than `w=1920`; the lightbox alone asks for the large render.
- Google Fonts load without blocking first paint; `apple-touch-icon` is a 21KB 180×180 file instead of a 946KB image.

> **Policies / Legal & operations is hidden** while the wording is in draft — see the comment above `#policies` in `index.html` to restore it.

## Mail

- **Static HF Space:** form posts via FormSubmit AJAX to `pd3rvr@icloud.com` (same pattern as careTalk). First live send may need a one-time FormSubmit confirmation in that inbox.
- **Docker / `app.py` outgoing mail:** `POST /api/contact` sends over SMTP. Set secrets `SMTP_USER` + `SMTP_PASSWORD` (iCloud app-specific password), optional `SMTP_HOST=smtp.mail.me.com`, `SMTP_PORT=587`, `MAIL_TO`, `SMTP_FROM`.

> Hugging Face free tier no longer allows new Docker Spaces, so this Space uses the **static** SDK. `Dockerfile` / `app.py` remain for local Docker runs with the SMTP mail server.
