# 🏛 ARCHITECTURE — Weltkrieg

## Filosofia

Weltkrieg è progettato come **applicazione statica vanilla**: HTML/CSS/JS senza framework, senza build step, senza dipendenze runtime obbligatorie.

Vantaggi:
- Deploy ovunque ci sia un file server (GitHub Pages, S3, qualsiasi static host)
- Funziona offline dopo il primo caricamento
- Zero overhead di bundling, zero supply-chain attack surface
- Codice leggibile e modificabile direttamente da chiunque

## Struttura

```
weltkrieg/
├── index.html              Landing page (selezione modalità + lingua)
├── play-ai/index.html      Modalità AI completa (self-contained)
├── play/index.html Modalità Classica (in sviluppo)
├── locales/
│   ├── it.json             Stringhe UI italiane (default)
│   └── en.json             Stringhe UI inglesi
├── data/
│   ├── countries.json      Risorse per paese (6 categorie × ~200 paesi)
│   ├── capitals.json       Coordinate capitali (lat, lon)
│   ├── eras.json           Periodi storici (anno, nome, descrizione)
│   ├── characters.json     Personaggi storici per era
│   └── moments.json        Momenti storici interattivi
├── shared/
│   ├── i18n.js             Engine traduzione
│   └── audio.js            Sound FX procedurali
├── assets/
│   └── world-110m.json     Mappa Natural Earth (TopoJSON)
└── docs/
    ├── ARCHITECTURE.md     Questo file
    ├── PRIVACY.md          Disclaimer dati
    └── RULES.md            Regole gioco
```

## Modalità AI — Flusso di un turno

```
┌─────────────────────────────────────────────────────────────┐
│  TURNO N                                                    │
│                                                             │
│  FASE I — Arbitro                                           │
│    Input: HISTORIA.txt + risorse + alleanze/guerre          │
│    Output: bollettino situazionale                          │
│    Chiamata Groq #1 (≈600 token)                            │
│                                                             │
│  FASE II — Discorsi di apertura                             │
│    Per ogni giocatore:                                      │
│      Umano → textarea input                                 │
│      AI    → Chiamata Groq #N (≈240 token ciascuna)         │
│                                                             │
│  FASE III — Reazioni                                        │
│    Per ogni giocatore:                                      │
│      Vede i discorsi di apertura di TUTTI                   │
│      Umano → textarea input                                 │
│      AI    → Chiamata Groq #N (≈240 token ciascuna)         │
│                                                             │
│  FASE IV — Verdetto                                         │
│    Input: tutti i discorsi + risorse + diplomazia           │
│    Output: dado 1-6 + analisi + conseguenze territoriali    │
│    Chiamata Groq #1 (≈900 token)                            │
│                                                             │
│  Side effects:                                              │
│    - Trasferimento territori (paesi citati nel verdetto)    │
│    - Aggiornamento risorse giocatori                        │
│    - Parsing alleanze/guerre dichiarate                     │
│    - Snapshot per timelapse                                 │
│    - Avanzamento anno                                       │
└─────────────────────────────────────────────────────────────┘
```

**Totale chiamate Groq per turno**: 2 + 2 × N_AI giocatori

Esempio con 4 AI: 2 + 8 = 10 chiamate, ~3'000 token totali per turno.

## Sistema risorse

Ogni paese ha 6 risorse calibrate su valori reali (1-10):

| Codice | Risorsa     | Esempio top |
|--------|-------------|-------------|
| `tech` | Tecnologica | Giappone 10, Germania 10, Svizzera 10 |
| `trade`| Commerciale | Cina 10, USA 10, Paesi Bassi 10 |
| `mil`  | Militare    | USA 10, Cina 10, Russia 10 |
| `mine` | Mineraria   | Australia 9, Russia 9, Sudafrica 9 |
| `ener` | Energetica  | Arabia Saudita 10, Qatar 10, Norvegia 10 |
| `agri` | Agricola    | Brasile 10, USA 9, Argentina 9 |

Quando un giocatore conquista un paese, le sue risorse si **sommano** al suo dominio totale. Quando un paese passa di mano, le risorse vengono sottratte al precedente proprietario e aggiunte al nuovo.

## Modalità Classica — Meccaniche

### Flusso del turno
Ogni turno è composto da N sotto-turni (uno per giocatore) + una fase di risoluzione:

```
TURNO N
├── Sotto-turno Rosso → sceglie 1 azione + bersaglio
├── Sotto-turno Blu   → sceglie 1 azione + bersaglio
├── Sotto-turno Verde → sceglie 1 azione + bersaglio
└── RISOLUZIONE → tutte le azioni applicate in ordine, con tiro di dado per ciascuna
```

### 10 Azioni disponibili

| Icona | Azione | Requisito | Effetto |
|-------|--------|-----------|---------|
| ⚔️ | Attacco Militare | stato di guerra | Lanchester (atk·dice − def) |
| 🔥 | Dichiara Guerra | giocatore neutrale | apre stato di war |
| 🤝 | Proponi Alleanza | giocatore neutrale | check trade+tech vs trade+tech avversario |
| 💔 | Rompi Alleanza | giocatore alleato | -2 trade reputazione |
| ⚙️ | Sviluppo Tecnologico | nessuno | +2 tech |
| 🪙 | Sviluppo Economico | nessuno | +2 trade |
| 🛡️ | Mobilita Esercito | agri≥3 | +3 mil, -1 agri |
| 🕵 | Spionaggio | tech≥4 | -1/-2/-3 risorsa casuale avversario |
| 🚫 | Embargo Commerciale | trade≥5 | -2 trade avversario |
| 🏰 | Fortifica Confini | nessuno | +50% difesa al prossimo attacco |

### Risoluzione attacco (Lanchester semplificata)

```
attackerPower  = atk.mil + atk.tech × 0.5
defenderPower  = def.mil + def.tech × 0.5 + def.agri × 0.3
if defender is fortified: defenderPower *= 1.5

diceModifier   = 0.5 + (dice - 1) × 0.2     // 1=0.5x, 6=1.5x
finalAttack    = attackerPower × diceModifier
result         = finalAttack - defenderPower

if result > 0: vittoria → trasferisci min(3, round(atk/def)) paesi
               casualties attaccante: -30% del defenderPower in mil
if result ≤ 0: sconfitta → casualties attaccante: -50% di |result| in mil
```

### Bot AI (greedy deterministica)
Ogni bot valuta tutte le azioni disponibili e assegna uno score basato su:
- Vantaggio militare vs nemici dichiarati
- Risorse correnti (preferisce sviluppare ciò che gli manca)
- Stato di guerra/alleanza (più aggressivo se in guerra)
- Soglia: mil>15 attacca proattivamente, mil<10 cerca alleanze

## Sistema diplomazia (entrambe modalità)

Tre stati possibili tra due giocatori:
- **Neutralità** (default)
- **Alleanza** (linea verde pulsante sulla mappa, condivisione di obiettivi)
- **Guerra** (linea rossa pulsante, abilita conquiste territoriali)

Transizioni:
- Dichiarate manualmente dai giocatori umani
- Dichiarate automaticamente dall'Arbitro nel verdetto
- Una nuova guerra cancella un'eventuale alleanza precedente
- Una nuova alleanza cancella un'eventuale guerra

## Timelapse

Snapshot della struttura `{turno, anno, owners: {paese → giocatore_id}}` salvato ad ogni fine turno. Slider per scorrere all'indietro, pulsante Play per animazione automatica (frame ogni 800ms).

## Sistema i18n

Engine minimale (~10 righe):

```javascript
async function loadLocale() {
  const browserLang = navigator.language.split('-')[0];
  const supported = ['it', 'en'];
  const lang = supported.includes(browserLang) ? browserLang : 'en';
  const res = await fetch(`locales/${lang}.json`);
  window.L = await res.json();
  document.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = window.L[el.dataset.i18n] || el.textContent;
  });
}
```

Markup:
```html
<button data-i18n="startCampaign">⚔ INIZIA LA CAMPAGNA ⚔</button>
```

I prompt al modello LLM includono dinamicamente la lingua del browser:
```
"Rispondi sempre in lingua: it"
```

Llama 3.3 70B parla decentemente italiano, inglese, spagnolo, francese, tedesco, portoghese, russo, cinese, giapponese.

## Performance

- Caricamento iniziale: ~110KB JSON mappa + ~80KB HTML + ~5KB locales = **~200KB totali**
- D3 + topojson-client da CDN: ~150KB cached
- First Contentful Paint: <500ms su connessione decente
- Time to Interactive: <1s

## Sicurezza

- API key Groq mai esposta ad altri servizi (chiamata diretta browser → Groq)
- CSP header (da configurare in `index.html`) limita le origini di script/connect
- Nessun `eval()`, nessun `innerHTML` con input utente non sanitizzato
- I dati dei verdetti dall'AI vengono filtrati prima di essere applicati alla mappa (matching solo su nomi paesi noti)
