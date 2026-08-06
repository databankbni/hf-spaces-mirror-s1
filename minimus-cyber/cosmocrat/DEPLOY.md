# Deploy di Cosmocrat su Hugging Face Spaces

Questo file è pensato per essere letto da un'assistente (Claude Code)
o dall'utente, per pubblicare Cosmocrat come Static Space su HF con
**OAuth attivato** (i visitatori si autenticano con il proprio account HF,
senza copia-incolla del token).

## Prerequisiti (l'utente li fa PRIMA)

1. Account Hugging Face attivo — https://huggingface.co
2. Space già creato dal browser:
   - Vai su https://huggingface.co/new-space
   - Space name: `cosmocrat` (o altro nome a scelta)
   - License: `mit`
   - **SDK: Static** (fondamentale, non Gradio né Streamlit)
   - Visibility: Public
   - Clicca "Create Space" — si crea un repo Git vuoto

3. Token HF con permessi **write** (diverso da quello usato per l'inference):
   - https://huggingface.co/settings/tokens → New token
   - Tipo: **Write**, oppure Fine-grained con scope
     "Write access to contents of all repos under your personal namespace"
   - Salvarlo in modo sicuro (keychain OS, password manager) — NON incollarlo in chat

## Comandi da eseguire (Claude Code)

L'utente fornirà:
- `HF_USERNAME` — il proprio username Hugging Face
- `SPACE_NAME` — di solito `cosmocrat`
- `HF_TOKEN` — token write; da chiedere all'utente al momento del push,
  non da salvare in file di configurazione visibili

Passi:

```bash
# 1. Andare nella cartella estratta dello zip cosmocrat-repo
cd /path/to/cosmocrat

# 2. Inizializzare git se non già fatto
git init
git branch -m main

# 3. Configurare identità git (se non già globale)
git config user.name "$HF_USERNAME"
git config user.email "email@associato-al-account.hf"

# 4. Aggiungere tutti i file, escludendo eventuali .DS_Store
git add .
git status  # mostra all'utente cosa sarà commitato

# 5. Primo commit
git commit -m "Cosmocrat initial release"

# 6. Aggiungere remote HF Spaces
git remote add origin "https://huggingface.co/spaces/${HF_USERNAME}/${SPACE_NAME}"

# 7. Push - autenticazione HTTPS con token
# Metodo consigliato: chiedere il token via input e usarlo come URL temporaneo
# senza salvarlo nel file .git/config
# NB: il token qui è quello WRITE, non quello per l'inference

git push -u "https://${HF_USERNAME}:${HF_TOKEN}@huggingface.co/spaces/${HF_USERNAME}/${SPACE_NAME}" main

# In alternativa, se l'utente preferisce, configurare credential helper:
# git config --global credential.helper store  # Linux
# git config --global credential.helper osxkeychain  # macOS
# git config --global credential.helper manager-core  # Windows
```

## Cosa succede dopo il push

- HF Spaces rileva il push, legge `README.md` (front matter YAML con `sdk: static`)
- Serve `index.html` come pagina principale (`app_file: index.html`)
- Build automatico in 30-90 secondi
- Il Space è live su:
  - Short URL: `https://<HF_USERNAME>-<SPACE_NAME>.hf.space/`
  - HF page: `https://huggingface.co/spaces/<HF_USERNAME>/<SPACE_NAME>`

## Verifica post-deploy

Aprire lo Space nel browser e controllare:
- [ ] Landing page carica correttamente
- [ ] Selettore lingua funziona
- [ ] Cliccando "INIZIA LA CAMPAGNA" si apre il setup
- [ ] Nel setup appare il blocco giallo "🤗 SIGN IN" (visibile solo su HF Spaces con OAuth)
- [ ] Cliccando SIGN IN si viene reindirizzati a huggingface.co per autorizzazione
- [ ] Dopo autorizzazione si torna al gioco con il token auto-riempito
- [ ] La mappa (planisphere.png) si carica
- [ ] Il Codex si apre e mostra 5 tab
- [ ] I sinecismi cliccabili mostrano il tooltip

Se qualcosa non funziona:
- Su HF, tab "Files and versions" → controlla che tutti i file siano
  effettivamente pushati
- Tab "Community" → controlla i log di build

## Aggiornamenti successivi

Ogni volta che si modificano i file:

```bash
git add .
git commit -m "descrizione modifica"
git push
```

HF ribuilda automaticamente ad ogni push.

## Sicurezza

- Il file `.git/config` può conservare le credenziali di push in chiaro
  se non si usa un credential helper con keychain. Ispezionarlo dopo il push:
  `cat .git/config` — se contiene `<HF_TOKEN>` in chiaro, rimuoverlo
  con `git remote set-url origin https://huggingface.co/spaces/<HF_USERNAME>/<SPACE_NAME>`
  e configurare il credential helper per i push futuri.

- Il token HF **write** non va MAI committato nel repo: già escluso dal .gitignore
  ma verificare che non appaia in file di configurazione o script.
