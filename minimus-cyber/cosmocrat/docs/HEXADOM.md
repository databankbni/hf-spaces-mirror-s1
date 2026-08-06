# Hexadom — valore storico-didattico e decisioni di progetto

> *cambia la storia con un prompt*

Questo documento è la **fonte di verità** del valore didattico di Hexadom e il **registro delle decisioni** di progetto. È pubblico e va aggiornato a ogni scelta significativa.

---

## 1. Che cos'è Hexadom

Hexadom è un **wargame diplomatico testuale** in cui giocatori umani e modelli linguistici (LLM) competono impersonando **capi di stato, condottieri ed eroi realmente attestati** dalle fonti storiche. Le mosse sono libere e dichiarate in linguaggio naturale; un **Arbiter deterministico** (temperatura zero) le valuta contro la storia reale ed emette verdetti territoriali.

Il fine non è solo ludico: è **far toccare con mano la storia** — geografia del potere, contemporaneità e distanza tra i protagonisti, plausibilità delle mosse, conseguenze delle scelte.

## 2. I pilastri didattici

### 2.1 Le hexad — nuclei geografici invarianti
La mappa non è divisa in stati moderni ma in **hexad** (termine invariato in italiano; *hexad/hexads* nelle altre lingue): **nuclei geografici che hanno mantenuto una propria identità lungo tutto l'arco della storia umana** — valli fluviali, pianure, bacini, altopiani. Roma sta sempre sul Tevere, l'Egitto sempre sul Nilo. Insegnano che **la geografia è la costante** su cui la storia si deposita.

Ogni hexad ha un **esagono-capoluogo**: la singola cella della griglia che le dà il nome, scontornata in oro, riconoscibile dentro il dominio colorato di ogni giocatore.

### 2.2 I personaggi — solo figure realmente attestate
Non si sceglie un nome arbitrario: si sceglie un **avatar storico** da un censimento di capi/condottieri/eroi documentati, organizzato per **continente → macroregione → anno**. Per la preistoria vale un **filtro evemerista** (da Evemero di Messene, via Diodoro Siculo e Lattanzio): si ammettono solo figure *storicizzate o storicizzabili* con fonte scritta, escludendo il puramente teofanico.

### 2.3 L'Arbiter — la storia reale come metro
L'Arbiter giudica a **temperatura zero**: una mossa storicamente coerente riesce, una fuori tempo o fuori luogo fallisce. Non premia la fantasia ma la **verosimiglianza storica e geopolitica**. È, di fatto, un tutor che riporta ogni azione al banco di prova delle fonti.

### 2.4 Le citazioni
I momenti chiave sono commentati da **citazioni reali attribuite** (Tucidide, Cicerone, Tacito…), nella lingua originale dell'autore quando pertinente.

---

## 3. Standard delle fonti

Per garantire il valore didattico, ogni dato storico poggia su fonti **verificabili e non-eurocentriche**, su due livelli.

**A. Territorio (sede/capoluogo) — atlanti storici cartografici**
- **Euratlas** — mappe anno-per-anno (Europa, Mediterraneo, Vicino Oriente)
- **Talessman's Atlas of World History** (T. Lessman) — mappe mondiali per secolo, copertura globale
- **Barrington Atlas / DARMC** — mondo greco-romano
- ***The Times Atlas of World History*** — riferimento globale trasversale

**B. Datazione (floruit) e sede — riferimenti biografici standard**
- *Oxford Classical Dictionary*, *Encyclopaedia Iranica*, *Encyclopaedia of Islam*, dizionari biografici nazionali
- Preistoria: criterio evemerista con `fonte_primaria` = autore antico

**Regola di assegnazione**: il `capoluogo` di un personaggio è la sua **sede di potere documentata** nel suo *floruit*; la città-sede viene mappata alla hexad più vicina per coordinate. Ogni assegnazione porta la propria `fonte_territorio`.

---

## 4. Modello dati

### 4.1 Hexad (`data/sinecismi.json`)
717 hexad, ciascuna con `id, nome, citta, descrizione, macro_regione, lat, lon`. 150 curate storicamente + 567 da Natural Earth.

### 4.2 Personaggi (`data/characters.json`)
369 personaggi, campi base `nome, macro_regione, descrizione, era` (+ `fonte_primaria` per la preistoria). **Arricchimento in corso** con quattro campi:

| campo | significato |
|---|---|
| `continente` | derivato automaticamente dalla macroregione (EUROPA/ASIA/AFRICA/AMERICHE/OCEANIA) |
| `anno_min`, `anno_max` | finestra di *floruit*: anni in cui l'avatar è selezionabile (negativi = a.C.) |
| `capoluogo` | id della singola hexad-sede storica del personaggio |
| `fonte_territorio` | citazione della fonte per quella sede |

Esempio (lotto-prova):

```json
{ "nome": "Giulio Cesare", "continente": "EUROPA", "anno_min": -100, "anno_max": -44,
  "capoluogo": "tiberino", "fonte_territorio": "Barrington Atlas — mondo romano tardo-repubblicano" }
```

---

## 5. Decisioni di progetto (registro)

- **Nome**: il gioco si chiama **Hexadom**; sottotitolo *«cambia la storia con un prompt»*.
- **Terminologia**: le unità territoriali sono **hexad** (invariato in italiano, *hexad/hexads* altrove). Il termine precedente («sinecismo», poi «terra/terræ») è stato abbandonato.
- **Capoluogo**: ogni hexad ha un esagono-capoluogo scontornato in oro.
- **Assegnazione iniziale**: si passa **dall'assegnazione dell'Arbiter a quella basata sulle fonti** — ogni personaggio parte dalla propria hexad-capoluogo. Transizione morbida: fallback all'Arbiter per i personaggi non ancora arricchiti.
- **Selezione avatar**: niente più nome libero → **menu a tendina** per continente/macroregione, filtrato per anno.
- **Ottimizzazione dei testi**: risposte in stile bollettino, memoria di gioco a **cronaca compatta** + **patti strutturati**, per ridurre rumore e latenza.
- **Multilingua**: UI in 10 lingue; i due comandi latini *AD ALEAS!* e *PAX RATA FIAT* restano invariati.
- **Privacy**: nessun tracciamento; le chiamate LLM usano la quota dell'utente. Vedi [PRIVACY](PRIVACY.md).

---

## 6. Roadmap dell'arricchimento

1. **Fonti approvate** (§3) ✅
2. `continente` derivato per tutti i 369 · schema campi predisposto ✅
3. Popolamento `anno_min/max` + `capoluogo` + `fonte_territorio`, **a lotti per era**, sottoposti a revisione ⏳
4. Tendina avatar filtrata per anno (§2.2) ⏳
5. Assegnazione iniziale data-driven con fallback Arbiter (§5) ⏳

*Ultimo aggiornamento: 2026-07-29.*
