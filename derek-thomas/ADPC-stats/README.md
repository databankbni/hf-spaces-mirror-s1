---
title: ADPC Stats
emoji: "🏓"
colorFrom: blue
colorTo: green
sdk: static
app_file: index.html
pinned: false
license: mit
---

# ADPC Stats

Sixteen months of the Abu Dhabi Pickleball Club WhatsApp group, analysed.

- **[index.html](index.html)** - the case for public courts in Abu Dhabi, built from
  the group's own scheduling data: growth pace, organised sessions per month, and the
  hour-of-day pattern that shows play squeezed into the windows the climate allows.
- **[stats.html](stats.html)** - the underlying membership analysis: roster
  reconstruction from 908 membership events, joins vs departures, and posting activity
  against roster size.

## Data

Source is a single WhatsApp export covering 20 Apr 2025 - 8 Aug 2026: 38,165 lines,
13,577 messages, 908 membership events. Membership is rebuilt event-by-event and
reconciles to the 505 members WhatsApp reports. No personal data, message contents or
member names are published here - only aggregate counts.

Both pages are self-contained static HTML with inline SVG charts. No build step, no
external requests.
