# BhagwadGitaReadingAgent — Architecture

Visual reference for how the app is wired together. See [PLAN.md](PLAN.md) for the
design rationale and decision log.

---

## 1. System overview

High-level components. **Reading is deterministic Python** (no LLM); the **LLM
serves only the chat panel and per-verse reflections**. Verses live in a
read-only `gita.sqlite`; user data and reflections have their own databases,
backed up to a private HF dataset.

```mermaid
flowchart TB
    user(["User (browser)"])
    ui["Gradio UI — app.py"]

    reader["Reading engine\n(deterministic, no LLM)"]
    agent["Ask the Sage + reflections\n(LLM: Llama-3.1-8B)"]
    reminders["Reminders\n(email + .ics)"]

    verses[("gita.sqlite\nverses + audio")]
    userdb[("users.sqlite\nprofiles + bookmarks")]
    refldb[("reflections.sqlite")]
    hfds[("HF dataset\ndurable backup")]

    user <--> ui
    ui --> reader
    ui --> agent
    ui --> reminders

    reader <--> verses
    ui <--> userdb
    ui <--> refldb
    agent --> verses
    reminders --> userdb

    userdb <-. sync .-> hfds
    refldb <-. sync .-> hfds
```

---

## 2. Data ingestion pipeline (Phase A)

One-time (idempotent) build that turns the HF dataset into the SQLite corpus,
the Chroma index, and the audio cache. `ensure_corpus()` / `ensure_audio()` run
this lazily on cold start and skip work already done.

```mermaid
flowchart LR
    hf[("HF dataset\nOEvortex/Bhagavad_Gita\n700 rows")]

    subgraph fetch["fetch_dataset.py"]
        load["load_dataset(split=train)"]
        norm["normalize_row()\nverse_id = BG{ch}.{v}\nhandle 'Enlgish' typo"]
    end

    subgraph corpus["build_corpus.py"]
        writesql["_write_sqlite()\nverses table"]
        embed["Embedder\nall-MiniLM-L6-v2 (384d)"]
        writechroma["_write_chroma()\ngita_verses (cosine)"]
    end

    subgraph audiob["build_audio.py"]
        tts["gTTS synth\nhi = Sanskrit, en = English"]
        dur["mutagen duration probe"]
        back["write sa_seconds / en_seconds"]
    end

    hf --> load --> norm
    norm --> writesql
    norm --> embed --> writechroma
    writesql --> tts --> dur --> back
    back -. updates .-> writesql
```

---

## 3. Reading session — resume from bookmark (Phase B + D)

The core user loop: identify by email, resume from the saved verse, play verses
until the wall-clock budget is spent, then persist the next bookmark.

```mermaid
sequenceDiagram
    actor U as User
    participant App as app.py
    participant BM as BookmarkStore
    participant RS as ReadingSession
    participant VS as VerseStore
    participant FS as audio_cache

    U->>App: enter email + click Start
    App->>BM: load_position(email)
    BM-->>App: last_verse_id (or BG1.1 for new user)
    App->>RS: ReadingSession(start_verse_id, budget_seconds)

    loop until budget exhausted or book end
        App->>RS: next verse
        RS->>VS: get_verse / next_verse_after
        VS-->>RS: Verse (sanskrit, english, durations)
        RS->>RS: played_any && cost > remaining ? stop : play
        RS-->>App: VersePlayback + audio paths
        App->>FS: serve sanskrit.mp3 then english.mp3
        App-->>U: render verse + autoplay audio
    end

    RS-->>App: next_bookmark (verse that didn't fit)
    U->>App: click Stop (or budget ends)
    App->>BM: save_position(email, next_bookmark)
    BM-->>App: ok
    App-->>U: "Reading from BGx.y — saved"
```

---

## 4. Reminder scheduling (Phase C)

Subscribed users get one daily APScheduler job that emails a resume link with
their current bookmark. In-process scheduler is a v1 local-only limitation.

```mermaid
flowchart TB
    start(["App cold start"]) --> loadall["scheduler.load_all()"]
    loadall --> scan["ProfileStore.list_subscribers()"]
    scan --> jobs{"per subscriber"}
    jobs --> cron["CronTrigger @ reminder_time_local"]

    subgraph fire["When a job fires"]
        getbm["BookmarkStore.load_position(email)"]
        build["build_reminder()\nsubject + body w/ resume link"]
        send["mailer.send_email() via SMTP STARTTLS"]
    end

    cron --> getbm --> build --> send --> inbox[("User inbox")]

    settings["UI: reminder opt-in + time"] -->|subscribe / unsubscribe / reschedule| loadall
```

---

## 5. Chat layer — "Ask the Sage" (Phase E)

A grounded Q&A agent. The LLM may only answer from verses returned by the tools;
it cites refs in `[BGx.y]` form and refuses ungrounded questions.

```mermaid
flowchart TB
    q(["User question"]) --> agent["ToolCallingAgent\nGROUNDED_PREAMBLE, max_steps=4"]
    agent --> model["InferenceClientModel\nLlama-3.1-8B-Instruct, temp=0.0"]

    agent --> t1["VerseLookupTool\nforward(chapter, verse)"]
    agent --> t2["VerseSearchTool\nforward(question) → top-3"]
    agent --> t3["JumpToTool\nset reader position"]

    t1 --> store["VerseStore → gita.sqlite"]
    t2 --> retr["VerseRetriever → Chroma gita_verses"]
    t3 --> sink["jump_sink (app applies)"]

    model --> ans["Grounded answer + [BGx.y] citations"]
    ans --> q
```

---

## 6. Data model

Single SQLite database `data/gita.sqlite` with three tables; Chroma holds the
parallel vector index keyed by `verse_id`.

```mermaid
erDiagram
    VERSES {
        text verse_id PK "BG{ch}.{v}"
        int chapter
        int verse
        text title
        text sanskrit
        text english
        text hindi
        real sa_seconds
        real en_seconds
    }
    USERS {
        text email PK
        int max_minutes "10-60"
        bool reminder_opt_in
        text reminder_time_local "HH:MM"
        text created_at
        text updated_at
    }
    BOOKMARKS {
        text email PK_FK
        text last_verse_id FK
        text updated_at
    }
    USERS ||--|| BOOKMARKS : "has position"
    VERSES ||--o{ BOOKMARKS : "points at"
```

---

## 7. Deployment topology (Phase F)

Local dev runs everything in-process. The HF Space bakes the prebuilt `data/`
artifacts to avoid cold-start audio synthesis; SMTP and HF tokens are Space secrets.

```mermaid
flowchart LR
    subgraph local["Local dev — D:/Huggingface_ai_learning"]
        venv["venv python"]
        appL["app.py @ 0.0.0.0:7860"]
        dataL[("data/ artifacts")]
        tok["AccessToken.txt"]
    end

    subgraph space["HF Space — kanika23oct/BhagwadGitaReadingAgent"]
        appS["app.py (gradio sdk)"]
        baked[("baked data/\nsqlite + chroma + audio")]
        secrets["Secrets:\nHF_TOKEN, SMTP_*"]
    end

    inf["HF Inference Providers"]
    smtp["SMTP server"]

    venv --> appL --> dataL
    appL -.->|chat| inf
    appL -.->|reminders| smtp

    local -->|_deploy.py upload| space
    appS --> baked
    appS -.->|chat| inf
    appS -.->|reminders| smtp
    secrets --> appS
```
