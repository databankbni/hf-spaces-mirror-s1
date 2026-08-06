# Aletheia — Frontend Design Plan (write once, build exactly to this)

## The 10-line plan

1. **Identity:** `ALETHEIA` wordmark in Instrument Serif, italic serif tagline *the
   un-forgetting*; Inter for UI; IBM Plex Mono for anything data-shaped (ids, counts,
   the ledger). Google Fonts, preconnected.
2. **Palette (CSS custom properties, exact):** bg `#0E0A1F` with radial vignette to
   `#1B1140` centered behind the graph; text `#EDEAF7`; muted `#8B84A8`; panel
   `rgba(20,14,46,0.72)` with 1px `#2A2150` borders. Source hues by `color_index`:
   `#7C6CFF` `#C86CFF` `#5FD4E8` `#FFB454`. Structural nodes `#4A4468`. Retraction
   `#FF4D5E`. Answer pulse `#6CFFA8`.
3. **Layout:** graph canvas is full-bleed and owns the whole viewport; a slim header
   (wordmark left, live `N memories · M links` counters right) and two glass panel
   columns (Sources+Ledger 300px left, Ask 360px right) float OVER it. The
   constellation is never boxed in — panels are guests on its sky.
4. **The signature moment — retraction:** the Retract button morphs its source card
   into a red "armed" state inline (*"Retract — this cannot be unread"*), no modal.
   On confirm: card desaturates to a ruin, its nodes ignite red and collapse over
   1.6s, the force sim reheats and the sky physically re-settles, the ledger types
   its new line in. Every other element stays still — the moment owns the screen.
5. **Micro-interactions (framer-motion):** press scale 0.98; panel content staggers
   in 160ms ease-out; source cards/chips glow on hover; glass toasts slide from
   bottom-right, verb-first (*"Source retracted — 41 memories removed"*).
6. **Loading is designed:** shimmer skeleton cards for sources/graph; the chat's
   thinking indicator is a tiny pulsing constellation (3 nodes, 2 links — not dots);
   ingestion shows a progress card: *"Reading this source, ~60s"* with a slow scan bar.
7. **Type scale:** wordmark 26px serif; panel titles 11px uppercase, +0.12em
   letterspacing, muted; body 14px Inter; mono 12px; `tabular-nums` on every counter.
8. **Depth:** SVG film-grain at ~3% over the bg; radial glow behind graph center;
   panels get `backdrop-filter: blur(14px)`, inset hairline highlight + soft 40px
   drop shadow.
9. **Graph rendering:** custom `nodeCanvasObject` — soft-glow discs, radius 3–9px by
   degree, hue by source; structural nodes dim; hover tooltip is a dark mono card
   (Name / Type / ID / Description) deliberately echoing cognee's own visualizer.
   Node lifecycle states drive everything: `entering` (grow-in, 600ms staggered),
   `pulsing` (green sine glow 3s on answers), `dying` (red collapse 1.6s).
10. **States & access:** empty state = faint static constellation sketch + *"Aletheia
    hasn't read anything yet. Load the demo scenario or add a source."*;
    `prefers-reduced-motion` swaps every animation for instant transitions; 2px
    violet focus ring on all focusables; custom thin scrollbars; violet selection.

## Self-critique (what read generic, and the revision)

- **"Glass panels on dark purple" is the 2026-generic AI-SaaS look.** What makes this
  NOT a template: the editorial serif/mono pairing (research journal meets lab
  instrument, no geometric-sans startup voice), the constellation as the actual
  protagonist (panels float over it, it is never a widget in a card), and one
  authored moment (the retraction) that everything else stays quiet for.
- **Three-dot "thinking" indicator was generic** → revised to the pulsing
  mini-constellation (line 6).
- **A confirm modal for retraction was generic** → revised to the inline card
  morph into an armed red state (line 4); a modal would also cover the constellation
  at the exact moment it matters most.
- **Bottom-right toasts are conventional** — kept deliberately: the demo needs the
  eye on the graph and the ledger, so notifications must be peripheral, not novel.

Build exactly to the above. If a change becomes necessary, update this file first.

## Amendment 1 — Onboarding & progressive disclosure (post-QA)

**Problem:** the left column front-loaded every control and detail (buttons, badges,
dates, retract buttons, full ledger prose) — expert-dense, newcomer-hostile.

11. **Onboarding = the story, then the demo.** First visit gets three full-screen
    glass slides in Aletheia's editorial voice (serif headings, one idea per slide):
    *what it is → the constellation is real memory → knowledge can be taken back.*
    Ends with "Start the guided flight" or "Explore on my own". Re-openable from a
    header help button. Never shown twice uninvited (localStorage).
12. **The Guided Flight:** a small glass checklist floating at the bottom-left of the
    constellation that walks the five demo beats (load demo → ask → retraction
    arrives → retract → ask again). Steps check themselves off from REAL app state —
    the onboarding literally is the demo script. Dismissible; completes with a quiet
    payoff line, then never returns.
13. **Sources become calm rows** (hue dot + title + badge). Details — kind, date,
    memory count, reason, the Retract action — live behind a click (one card expanded
    at a time). Status that can't wait (reading progress, errors) stays inline.
    Header actions are icon-only with tooltips.
14. **The ledger becomes scannable:** one line per event (icon + short title + signed
    memory count in mono). Newest entry still types in and flashes. Three most recent
    shown; "Show all" expands.
15. **The flight spotlight:** while a step is active, the stage dims behind an SVG-mask
    cutout that springs to the exact control (breathing violet ring + floating hint
    pill). Strictly polite: pointer-events pass through (guides, never walls), it
    steps aside whenever Aletheia is busy, and it holds during retraction so the
    dimmer can never mute the money shot. The flight card and toasts stay lit above it.
