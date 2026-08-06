---
title: Stremio Simkl Personal
emoji: ⭐
colorFrom: red
colorTo: purple
sdk: docker
pinned: false
app_port: 7860
---

# ⭐ Stremio Simkl Personal Addon

Addon Stremio/Nuvio con **raccomandazioni personali basate su ciò che guardi**, cataloghi streaming italiani, anime e trending da Simkl/TMDB/Kitsu.

## 📦 Catalog inclusi

| Catalog | Tipo | Login richiesto |
|---|---|---|
| 🔍 Cerca | Movie/Series | ❌ |
| ⭐ Consigliati per Te | Movie/Series | ✅ |
| 🔥 Popolari | Movie/Series | ❌ |
| 📈 Di Tendenza | Movie/Series | ❌ |
| 🏆 Più Votati | Movie/Series | ❌ |
| 🆕 Nuove Uscite | Movie/Series | ❌ |
| 🇮🇹 Italiani | Movie/Series | ❌ |
| 🎯 Simili alla Watchlist | Movie/Series | ✅ |
| 🧠 Simili ai Tuoi Visti | Movie/Series | ✅ |
| 💥 Azione / 🩸 Horror / 🕵️ Thriller / 🚀 Sci-Fi | Movie/Series* | ❌ |
| 🚔 Crime / 😄 Commedia / 🎙️ Documentari | Movie/Series | ❌ |
| 🔴 Netflix | Movie/Series | ❌ |
| 🔵 Disney+ | Movie/Series | ❌ |
| 🟡 Amazon Prime | Movie/Series | ❌ |
| 🧒 Bambini | Movie/Series | ❌ |
| 🍥 Anime Trending/Popolari/in Corso/Serie/Film | Series | ❌ |

---

## 🚀 Setup su Hugging Face

### 1. Crea un nuovo Space Docker

→ [huggingface.co/new-space](https://huggingface.co/new-space) — SDK: **Docker**

Carica i file: `app.py`, `Dockerfile`, `requirements.txt`, `README.md`

### 2. Aggiungi i Secret (Settings → Variables and Secrets)

| Variabile | Descrizione | Obbligatorio |
|---|---|---|
| `SIMKL_CLIENT_ID` | Client ID dell'app gratuita Simkl | ✅ |
| `TMDB_API_KEY` | Chiave API TMDB (per poster) | ⚠️ Consigliato |
| `BASE_URL` | URL pubblico del tuo Space senza slash finale (es. `https://user-stremio-trakt-personal.hf.space`) | ✅ |
| `HIDE_WATCHED` | Nasconde dai cataloghi pubblici i contenuti completati su Simkl (`true`/`false`) | ❌ Default `true` |
| `FAST_CATALOGS` | Carica più velocemente cataloghi/copertine TMDB usando ID `tmdb:` senza conversione IMDb preventiva | ❌ Default `true` |
| `CATALOG_LIMIT` | Numero massimo di elementi elaborati per pagina catalogo | ❌ Default `40` |
| `PRELOAD_CATALOGS` | Precarica molti cataloghi all'avvio dello Space | ❌ Default `false` |
| `BACKGROUND_REFRESH` | Aggiorna cataloghi automaticamente in background ogni 5 ore | ❌ Default `false` |
| `MIN_VOTE_COUNT` | Numero minimo di voti TMDB per cataloghi pubblici | ❌ Default `20` |
| `MIN_RATING` | Voto minimo TMDB per cataloghi pubblici (`0` disattiva) | ❌ Default `0` |
| `EXCLUDE_REALITY` | Esclude reality/talk dai cataloghi serie | ❌ Default `true` |
| `ONLY_RELEASED` | Esclude contenuti non ancora usciti dai cataloghi pubblici | ❌ Default `true` |
| `UPSTASH_REDIS_REST_URL` | URL REST Upstash Redis per salvare token e cache | ⚠️ Consigliato |
| `UPSTASH_REDIS_REST_TOKEN` | Token REST Upstash Redis | ⚠️ Consigliato |

### 3. Configura l'app Simkl

1. Vai su [simkl.com/settings/developer/new](https://simkl.com/settings/developer/new/)
2. Crea gratuitamente l'app e copia il **Client ID**.
3. Salvalo nei secret Hugging Face come `SIMKL_CLIENT_ID`.
4. L'addon usa il PIN flow ufficiale Simkl: non serve salvare un Client Secret.

### 4. Fai il login

Dopo il deploy, apri il tuo Space nel browser:
```
https://TUO-USERNAME-stremio-trakt-personal.hf.space
```
Clicca su **"Connetti Simkl"**, apri Simkl e autorizza il codice mostrato.

### 5. Installa in Stremio

In Stremio → Add-ons → Community → **Add by URL**:
```
https://TUO-USERNAME-stremio-trakt-personal.hf.space/manifest.json
```

---

## 🔄 Aggiornamenti automatici

Questo Space si aggiorna automaticamente quando fai push dei file su Hugging Face.

Da PowerShell, nella cartella del progetto:

```powershell
$env:HF_TOKEN="hf_il_tuo_token"
.\deploy.ps1 "Aggiorna cataloghi"
```

Lo script:

1. verifica la sintassi di `app.py`
2. crea un commit con le modifiche
3. fa push allo Space Hugging Face
4. Hugging Face rebuilda e pubblica automaticamente l'addon

In Stremio non devi reinstallare l'addon se l'URL resta lo stesso:

```text
https://TUO-USERNAME-stremio-trakt-personal.hf.space/manifest.json
```

---

## ⚠️ Note importanti

- Il token OAuth Simkl viene salvato prima su Upstash Redis, se configurato, e poi come fallback in `/tmp/simkl_tokens.json`.
- L'addon espone anche `/stream/{type}/{id}.json`: legge sorgenti autorizzate da `stream_sources.json` o `STREAM_SOURCES_JSON` e scarta URL che rispondono con errore, HTML o contenuto non video.
- Le sorgenti stream non vengono cercate automaticamente: vanno configurate esplicitamente con URL legittimi per ID IMDb/TMDB.
- Le sorgenti torrent legittime possono essere configurate con `magnet` o `infoHash`; l'addon normalizza l'infoHash e scarta righe malformate prima di inviarle a Nuvio.
- Se `REALDEBRID_TOKEN` è configurato come secret e `REALDEBRID_FILTER_CACHED=true`, l'addon prova a controllare la disponibilità Real-Debrid dei torrent. Se l'endpoint RD non è disponibile, non blocca sorgenti legittime configurate a meno che `REALDEBRID_REQUIRE_CACHED=true`.
- La modalità TorLink-legale usa solo provider manuali in `legal_torrent_sources.json`: feed RSS/search autorizzati con placeholder `{title}`, `{year}`, `{query}` o `{query_plus}`. I provider predefiniti di TorLink non vengono usati.
- Modalità MediaFusion-like: configura `PROWLARR_URL` e `PROWLARR_API_KEY` come secret/variabili dello Space. Quando Nuvio chiede uno stream, l'addon cerca titolo+anno su Prowlarr, normalizza magnet/infoHash, filtra/ordina e applica Real-Debrid.
- In alternativa puoi usare `TORZNAB_ENDPOINTS_JSON`, una lista JSON di endpoint Torznab manuali: `[{"name":"Indexer","url":"https://example/api","apikey":"...","enabled":true}]`.
- Simkl fornisce storico e watchlist; l'addon genera gratuitamente le raccomandazioni tramite TMDB.
- I cataloghi Netflix, Disney+ e Prime sono basati su TMDB con regione `IT`.
- Il filtro `HIDE_WATCHED=true` si applica ai cataloghi pubblici, non a Consigliati.
- I cataloghi italiani usano TMDB con lingua originale italiana e regione Italia.
- La pagina `/status` mostra se Simkl è loggato, se Redis è configurato e dove sono salvati i token.
- La pagina `/problems` mostra le cause più probabili se un catalogo è vuoto o incompleto.
- La pagina `/admin` permette refresh cataloghi, svuotamento cache, logout/login Simkl e controllo configurazione.
- La ricerca usa TMDB in italiano e inglese, deduplica i risultati e filtra poster mancanti/risultati di bassa qualità.
- Cache: trending/popular 2 ore, già visti Simkl 1 ora, cataloghi normali 6 ore.
- `FAST_CATALOGS=true` evita chiamate extra TMDB→IMDb per ogni copertina e rende più rapidi i cataloghi.
- `CATALOG_LIMIT=40` riduce il rischio di timeout Stremio; alza il valore solo se lo Space risponde velocemente.
- `PRELOAD_CATALOGS=false` e `BACKGROUND_REFRESH=false` evitano che lo Space faccia troppe chiamate API appena avviato.
- I cataloghi "Nuove Uscite" mostrano titoli usciti negli ultimi 75 giorni e già disponibili come usciti.
- I cataloghi "Simili" usano watchlist/storico Simkl come semi e TMDB recommendations/similar come fonte.
- Gli anime ora sono separati in serie, film e in corso quando Kitsu espone il subtype.
- Le trame anime e le trame episodi anime vengono tradotte in italiano e salvate in cache dedicata.
- I cataloghi anime non mostrano descrizioni inglesi non tradotte: usano cache italiana o lasciano vuoto per restare veloci.
- I trailer sono solo in italiano: prima TMDB italiano, poi YouTube API con query italiana; se non trova un trailer italiano, non usa fallback inglese.
- *Horror è disponibile come catalogo film; per le serie TMDB non ha un genere horror dedicato affidabile, quindi viene coperto meglio da Thriller/Sci-Fi.
