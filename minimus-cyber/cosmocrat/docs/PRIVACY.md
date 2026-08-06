# 🔒 PRIVACY — Weltkrieg

## TL;DR

**Weltkrieg non raccoglie, archivia o trasmette alcun dato verso server controllati dagli autori.**  
Tutto resta nel tuo browser.

## Cosa succede tecnicamente

Weltkrieg è un'applicazione **statica** servita da GitHub Pages. Non c'è backend, non c'è database, non c'è telemetria.

### Modalità Classica (offline)
- Funziona completamente offline dopo il primo caricamento della pagina
- Nessuna chiamata di rete tranne il caricamento iniziale dei file statici
- Nessun cookie, nessun tracker
- **Salvataggio in `localStorage`**: lo stato della partita viene salvato automaticamente alla fine di ogni turno nella chiave `weltkrieg.classic.save`. Resta solo nel tuo browser. Puoi esportarlo come file JSON, importarlo, o cancellarlo dal pulsante "⋯" nell'header. Viene cancellato automaticamente al raggiungimento della vittoria finale.

### Modalità Narrativa AI
Per generare i dialoghi tra capi di stato, il browser dell'utente effettua chiamate dirette a `https://api.groq.com`.

Cosa significa:

- ✅ La tua **API key Groq** viene memorizzata **solo nel tuo browser** (in memoria durante la sessione, opzionalmente in `localStorage` se attivi "Ricordami")
- ✅ Le tue **partite e la cronologia** restano **solo nel tuo browser**
- ✅ Le richieste vanno **direttamente** da te a Groq, senza passare da noi
- ⚠️ Groq vede le tue richieste come da loro [Privacy Policy](https://groq.com/privacy-policy/)
- ⚠️ I dati delle partite **non** vengono salvati permanentemente — se chiudi il browser senza esportare l'Historia, perderai la cronologia testuale (la mappa attuale resta in `localStorage` se hai attivato il salvataggio)

## Servizi terzi caricati

Quando carichi la pagina, il browser scarica risorse statiche da:

| Servizio | Cosa | Perché |
|---|---|---|
| **GitHub Pages** | HTML, CSS, JS, JSON | Hosting |
| **Google Fonts** | Cinzel, IM Fell English | Tipografia |
| **api.groq.com** (solo modalità AI) | Llama 3.3 70B | Generazione testi |

Tutti i dati cartografici e di gioco sono ospitati nel repo stesso (`assets/world-110m.json`, `data/`), nessuna CDN esterna per quelli.

## Cookie

Weltkrieg **non usa cookie**. Usa esclusivamente `localStorage` opzionale per salvare:
- La tua API key Groq (se attivi "Ricordami")
- Lo stato della partita corrente (se attivi "Salva partita")
- La lingua scelta

Puoi cancellare tutto in qualsiasi momento da DevTools → Application → Local Storage → cancella `weltkrieg.*`.

## Diritti GDPR

Non hai dati presso di noi, quindi non c'è nulla da richiedere, esportare o cancellare. Se attivi `localStorage`, sei tu il titolare dei dati che restano nel tuo dispositivo.

## Domande

Apri una [issue su GitHub](https://github.com/minimus-cyber/weltkrieg/issues) per qualsiasi dubbio.

---

*Ultimo aggiornamento: 2026-06*
