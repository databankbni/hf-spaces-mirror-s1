# ⚔ HEXADOM ⚔

**The Arbiter of Terræ** — a geopolitically plausible diplomatic wargame, fully browser-playable.

🌐 **[Play now](https://minimus-cyber.github.io/cosmocrat/)** · 🇮🇹 [README italiano](README.md)

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Status: Beta](https://img.shields.io/badge/status-beta-orange.svg)
![No tracking](https://img.shields.io/badge/tracking-none-green.svg)

---

## What is Hexadom

Hexadom is a turn-based strategy wargame where each player embodies a Head of State (Red, Blue, Green…) and leads their nation through rounds of diplomacy, alliances, and conquest on a rotatable, zoomable globe with Risk-inspired aesthetics.

Each turn:

1. **The Arbiter** reads world history and generates a situational briefing
2. **Each Leader delivers an opening speech** in first person
3. **Each Leader reacts to others' speeches** and declares their final move
4. **The Arbiter issues a verdict** with a dice roll (1–6) that modulates the outcome

Country resources (tech, trade, military, mining, energy, agriculture) are calibrated against real data: Saudi Arabia has energy 10, Germany tech 10, Russia military 10.

## Two modes

### 🎲 Classic Mode (offline)
> ✅ **Ready to play · with the Magister Minimus**

Deterministic wargame with built-in narrator-mentor. The **Magister Minimus** — Keeper of the World's Memory, dressed in the manner of Giordano Bruno — welcomes you with a prologue, explains the rules, guides you turn by turn with monologues, whispers, and contextual advice. Every victory, defeat, alliance is commented upon. Summon him at any time via the 🕯 MAGISTER button in the header.

Under the narrative: simplified Lanchester formulas, 1-6 dice, 10 strategic actions, deterministic greedy bots. No API key, no external service, reproducible.

### 🤖 AI Narrative Mode (available)
> ✅ **Ready to play**

Diplomatic dialogue, reactions, and verdicts are generated in real-time by **Llama 3.3 70B** via [Groq](https://groq.com). Requires a free Groq API key (5,000 requests/day on free tier).

## How to get a free Groq API key

1. Go to [console.groq.com](https://console.groq.com)
2. Sign up (Google/GitHub login works)
3. *API Keys* section → *Create API Key*
4. Copy the `gsk_...` key and paste it into Hexadom at first launch

The key is **never** sent to Hexadom servers. It stays in your browser and is used only to call `api.groq.com` directly. [See PRIVACY](docs/PRIVACY.md).

## Features

- 🗺️ **Natural Earth globe** rotatable, zoomable, with real borders
- ⚫ **Capitals** marked with golden diamonds, hover for resource detail
- ⏱️ **Timelapse** slider to replay game evolution turn by turn
- 📜 **Historical eras** from 3000 BCE to present, with characters (Caesar, Napoleon, Bismarck…)
- ⚡ **Historical moments** for human players: choose whether to cross the Rubicon
- 🤝 **Formal diplomacy**: alliances and wars animated on the map with pulsing lines
- 🔊 **Procedural audio** via Web Audio API (toggleable)
- 🌍 **Multilingual**: native Italian, English, browser autodetect
- 📱 **Responsive**: works on desktop, plays best on screens ≥ 1280px

## Quickstart

```bash
git clone https://github.com/minimus-cyber/cosmocrat.git
cd cosmocrat
# Open index.html in any browser — works from file://
# Or local server:
python3 -m http.server 8000
# Navigate to http://localhost:8000
```

No build step. Vanilla HTML/CSS/JS.

## License

[MIT](LICENSE) © 2026 minimus-cyber

## Credits

- Cartographic data: [Natural Earth](https://www.naturalearthdata.com/) (public domain)
- TopoJSON: [Mike Bostock](https://github.com/topojson/world-atlas) (MIT)
- Fonts: [Cinzel](https://fonts.google.com/specimen/Cinzel) + [IM Fell English](https://fonts.google.com/specimen/IM+Fell+English) (OFL)
- LLM inference: [Groq](https://groq.com)
