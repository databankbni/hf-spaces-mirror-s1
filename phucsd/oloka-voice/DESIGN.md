---
version: alpha
name: OmniVoice Gateway
colors:
  primary: "#4f46e5"
  secondary: "#f3f4f6"
  text-primary: "#111827"
  text-secondary: "#4b5563"
  bg-primary: "#f7f7f8"
  bg-card: "#ffffff"
  border: "#e5e7eb"
typography:
  h1:
    fontFamily: "Plus Jakarta Sans"
    fontSize: "2rem"
    fontWeight: "700"
  body:
    fontFamily: "Be Vietnam Pro"
    fontSize: "1rem"
rounded:
  card: "20px"
spacing:
  card-padding: "24px"
components:
  page:
    backgroundColor: "{colors.bg-primary}"
    textColor: "{colors.text-primary}"
  text-muted:
    textColor: "{colors.text-secondary}"
  divider:
    backgroundColor: "{colors.border}"
  button:
    backgroundColor: "{colors.primary}"
    textColor: "#ffffff"
    rounded: "12px"
  card:
    backgroundColor: "{colors.bg-card}"
    rounded: "{rounded.card}"
---

# Design System: OmniVoice Gateway

## 1. Overview

OmniVoice Gateway is a high-performance web interface for speech processing. The design philosophy centers on clean layout structures, high information density, and precise interactions. The atmosphere is clinical yet warm—like a modern architectural studio, optimizing developer productivity without cold sterility.

## 2. Colors

We employ a slate neutral canvas with a single calibrated Indigo accent to highlight action paths and focus states.

- **Primary Canvas Background** (`#f7f7f8` in light / `#0f1011` in dark) — Main page backing.
- **Card and Panel Surface** (`#ffffff` in light / `#17181a` in dark) — Enclosures for main tools and workspace items.
- **Ink Primary Text** (`#111827` in light / `#f5f5f5` in dark) — Highest contrast typography.
- **Steel Secondary Text** (`#4b5563` in light / `#cbd5e1` in dark) — Help texts, metadata labels, and instructions.
- **Whisper Border** (`#e5e7eb` in light / `#2a2b2f` in dark) — Thin structural boundaries.
- **Indigo Accent** (`#4f46e5` in light / `#636cf2` in dark) — The single accent color for primary actions, focus rings, and active states. (Saturation ~58% in light mode, ~75% in dark mode).

## 3. Typography

- **Display Headers**: `Plus Jakarta Sans` — Tight tracking (`-0.025em`), bold weights, and clean modern geometric forms.
- **Body & Controls**: `Be Vietnam Pro` — Highly legible, neutral, custom-tuned for Vietnamese-language text support.
- **Monospace Text**: `-apple-system-ui-monospace` or `monospace` — Used strictly for numbers, API responses, configuration data, and logs.
- **Banned Fonts**: `Inter` is banned to avoid generic AI styling tells.

## 4. Layout & Spacing

- All layouts enforce absolute grid-first containment (max-width of 1400px centered).
- Touch target sizes for interactive elements are kept at a minimum of `44px`.
- Layout sections stack cleanly. Overlapping elements and floating badges are banned.
- Sidebars scale fluidly (`clamp(220px, 14vw, 280px)`) to optimize responsive viewport utilization.

## 5. Elevation & Depth

- Cards use soft, diffused drop shadows tinted with the background hue to indicate depth without creating contrast noise.
- Borders use 1px width with neutral variables (`--border`) to define structural layout.

## 6. Shapes

- Primary workspace containers and large panels use a generous rounding (`20px`).
- Control elements like inputs, dropdowns, and button containers use medium rounding (`12px`).
- Status dots and audio player control buttons are rounded fully (`9999px`).

## 7. Components

- **Buttons**: Flat buttons with state translations. Active state translates by `translate-y-[1px]` for a physical press feel. Outer neon glows are banned.
- **Cards**: Soft borders (`1px`) with diffused drop shadows. Elevated content borders highlight the container only when strictly necessary for separation.
- **Form Inputs**: Labels sit strictly above the input fields, error blocks display below the inputs, and focus rings utilize the accent Indigo color.

## 8. Do's and Don'ts

### Do
- Maintain a unified Slate & Indigo palette with a single accent.
- Ensure all interactive touch elements are easily accessible (min `44px`).
- Use monospace for code blocks, token displays, and numeric measurements.
- Fallback gracefully on mobile viewports into single-column layouts.

### Don't
- Do not use decorative emojis in headings, UI buttons, or copy.
- Do not use the `Inter` font in style definitions.
- Do not use pure black (`#000000`) for surfaces or primary text.
- Do not use gradient text or neon glows for button active/hover states.
- Do not invent mock metrics or percentages (e.g. "99.9% uptime").
