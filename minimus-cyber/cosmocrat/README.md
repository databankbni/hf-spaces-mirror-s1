---
title: Hexadom
colorFrom: yellow
colorTo: red
sdk: static
pinned: false
license: mit
short_description: L'Arbiter dei Terræ — wargame diplomatico con LLM
tags:
  - wargame
  - llm-competition
  - geopolitical
  - history
  - italian
  - multilanguage
app_file: index.html
hf_oauth: true
hf_oauth_scopes:
  - inference-api
hf_oauth_expiration_minutes: 480
---

# ⚔ HEXADOM ⚔

**L'Arbiter dei Terræ** — un wargame diplomatico geopoliticamente verosimile, giocabile interamente nel browser.

🌐 **[Gioca ora](https://huggingface.co/spaces/minimus-cyber/cosmocrat)** · 🇬🇧 [English README](README.en.md) · 📜 **[Valore storico-didattico e decisioni di progetto](docs/HEXADOM.md)**

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Status: Beta](https://img.shields.io/badge/status-beta-orange.svg)
![No tracking](https://img.shields.io/badge/tracking-none-green.svg)

---

## Cos'è Hexadom

Hexadom è un wargame strategico in tempo reale dove ogni giocatore impersona un Capo di Stato (Rosso, Blu, Verde…) e guida la propria nazione attraverso turni di diplomazia, alleanze e conquiste su un mappamondo orientabile e zoomabile, con grafica ispirata al Risiko storico.

A ogni turno:

1. **L'Arbitro** legge la storia del mondo e genera un bollettino situazionale
2. **Ogni Capo tiene un discorso di apertura** in prima persona
3. **Ogni Capo reagisce ai discorsi altrui** e dichiara la mossa finale
4. **L'Arbitro pronuncia il verdetto** con tiro di dado (1–6) che modula l'esito

Le risorse di ogni paese (tecnologiche, commerciali, militari, minerarie, energetiche, agricole) sono calibrate su dati reali: l'Arabia Saudita ha energia 10, la Germania tecnologia 10, la Russia militare 10.

## Due modalità

### 🎲 Modalità Classica (offline)
> ✅ **Pronta all'uso · con il Magister Minimus**

Wargame deterministico con narratore-mentore integrato. Il **Magister Minimus** — custode della Memoria del Mondo, vestito alla maniera di Giordano Bruno — vi accoglie con un prologo, vi spiega le regole, vi guida turno per turno con monologhi, sussurri e consigli contestuali.

Ogni vittoria, ogni sconfitta, ogni alleanza viene commentata. Quando l'anno della partita attraversa una data storica significativa (la caduta di Troia, il Rubicone, Costantinopoli 1453, Hastings, la Pace di Westfalia, Hiroshima…), Magister narra l'evento — **30 eventi storici** dal 3000 a.C. al 2020. Potete consultarlo a richiesta tramite il pulsante 🕯 MAGISTER nell'header.

Suoni proceduali Web Audio (campana per i monologhi, chime per i sussurri, suoni distinti per battaglie e conquiste, toggleable 🔊). **Salvataggio automatico** della partita in localStorage dopo ogni turno; export/import come file JSON dal menu ⋯.

Sotto la narrazione: formule Lanchester semplificate, dado 1-6, 10 azioni strategiche, bot deterministici greedy basati sulle proprie risorse. Nessuna API key, nessun servizio esterno, riproducibile.

### 🤖 Modalità Narrativa AI (disponibile)
> ✅ **Pronta all'uso**

Il dialogo diplomatico, le reazioni e i verdetti sono generati in tempo reale da **Llama 3.3 70B** via [Groq](https://groq.com). Richiede una API key Groq gratuita (5'000 richieste/giorno nel free tier).

## Come ottenere una API key Groq gratis

1. Vai su [console.groq.com](https://console.groq.com)
2. Registrati (Google/GitHub login OK)
3. Sezione *API Keys* → *Create API Key*
4. Copia la chiave `gsk_...` e incollala in Hexadom al primo avvio

La chiave non viene **mai** inviata ai server di Hexadom. Resta nel tuo browser e viene usata solo per chiamare direttamente `api.groq.com`. [Vedi PRIVACY](docs/PRIVACY.md).

## Funzionalità

- 🗺️ **Mappamondo Natural Earth** orientabile, zoomabile, con confini reali
- ⚫ **Capitali** marcate da rombi dorati con dettaglio risorse al passaggio del mouse
- ⏱️ **Timelapse** scorrevole per rivedere l'evoluzione della partita turno per turno
- 📜 **Periodi storici** dal 3000 a.C. al presente, con personaggi (Cesare, Napoleone, Bismarck…)
- ⚡ **Momenti storici** per giocatori umani: scegli se varcare il Rubicone o no
- 🤝 **Diplomazia formale**: alleanze e guerre animate sulla mappa con linee pulsanti
- 🔊 **Audio proceduale** Web Audio API (toggleable)
- 🌍 **Multilingua**: italiano nativo, inglese, autodetect dal browser
- 📱 **Responsive**: funziona da desktop, gioca meglio da schermo ≥ 1280px

## Quickstart

```bash
git clone https://github.com/minimus-cyber/cosmocrat.git
cd cosmocrat
# Apri index.html in qualsiasi browser — funziona da file://
# Per server locale:
python3 -m http.server 8000
# Naviga a http://localhost:8000
```

Nessuna build necessaria. Vanilla HTML/CSS/JS.

## Struttura del progetto

```
cosmocrat/
├── index.html              # Landing page (selettore modalità + lingua)
├── play-ai/                # Modalità AI (Groq)
├── play/           # Modalità Classica (in sviluppo)
├── locales/                # Traduzioni UI (it.json, en.json)
├── data/                   # Risorse paesi, ere, personaggi
├── shared/                 # Codice condiviso (i18n, audio, mappa)
├── assets/                 # world-110m.json (Natural Earth)
└── docs/                   # ARCHITECTURE, PRIVACY, RULES
```

## Stack tecnico

- HTML5 + CSS3 + Vanilla JS (no framework, no build step)
- [D3.js v7](https://d3js.org) per proiezione mappa
- [topojson-client v3](https://github.com/topojson/topojson-client) per il rendering
- Web Audio API per suoni proceduali
- LLM: [Groq Llama 3.3 70B Versatile](https://groq.com/) (solo modalità AI)

## Contribuire

Pull request benvenute, soprattutto per:
- Traduzioni in altre lingue (`locales/`)
- Calibrazione risorse per paesi mancanti (`data/countries.json`)
- Nuovi momenti storici (`data/moments.json`)
- Bug report con screenshot

## Licenza

[MIT](LICENSE) © 2026 minimus-cyber

## Crediti

- Dati cartografici: [Natural Earth](https://www.naturalearthdata.com/) (public domain)
- TopoJSON: [Mike Bostock](https://github.com/topojson/world-atlas) (MIT)
- Font: [Cinzel](https://fonts.google.com/specimen/Cinzel) + [IM Fell English](https://fonts.google.com/specimen/IM+Fell+English) (OFL)
- Inferenza LLM: [Groq](https://groq.com)
