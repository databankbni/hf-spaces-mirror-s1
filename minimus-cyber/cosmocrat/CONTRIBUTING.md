# Contribuire a Weltkrieg

Grazie per l'interesse! Questo progetto è volutamente piccolo e vanilla — niente framework, niente build step. Modificarlo dovrebbe essere alla portata di chiunque conosca HTML/CSS/JS di base.

## Setup locale

```bash
git clone https://github.com/minimus-cyber/weltkrieg.git
cd weltkrieg
python3 -m http.server 8000
# apri http://localhost:8000
```

## Aree dove un PR è benvenuto

### 🌍 Traduzioni nuove lingue
1. Copia `locales/it.json` in `locales/<codice-lingua>.json`
2. Traduci ogni stringa
3. Modifica `shared/i18n.js` aggiungendo il codice all'array `supported`
4. Modifica `index.html` per aggiungere il pulsante lingua

### 📊 Calibrazione risorse paesi
Il file principale è `play-ai/index.html`, oggetto `BASE_RES`. I valori vanno 1-10. Documenta brevemente la fonte (World Bank, CIA Factbook, ecc.) nel commento del PR.

### ⚡ Momenti storici
In `play-ai/index.html`, array `HIST_MOMENTS`. Schema:
```js
{
  id: 'unique_id',
  era: -50,                    // anno di riferimento
  char: 'Nome Personaggio',    // matching string per attivazione
  turn: 2,                     // turno in cui appare
  title: 'Titolo',
  situation: 'Descrizione del dilemma...',
  choices: [
    { t:'NOME', txt:'Frase pronunciata', historic:true, effect:'+3 mil, ...' }
  ]
}
```

### 🐛 Bug report
Apri una issue con:
- Browser + versione
- Screenshot se possibile
- Passi per riprodurre
- Output console (`F12` → Console)

## Stile codice

- Indentazione 2 spazi
- Niente semicolon stripping aggressivo (sii consistente con lo stile presente)
- Nomi variabili abbreviati ok dove c'è precedente (es. `S` per state)
- Commenta solo logica non ovvia

## Pull Request

1. Fork del repo
2. Branch dal `main`: `git checkout -b fix/descrizione-breve`
3. Commit chiari: `git commit -m "Aggiunta traduzione spagnola"`
4. Push e apri PR verso `main`

## Codice di Condotta

Sii rispettoso. Niente harassment, niente politiche partigiane nelle discussioni tecniche. Storicità dei personaggi ≠ supporto delle loro ideologie.
